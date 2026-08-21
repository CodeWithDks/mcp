"""
Expense Tracker MCP Server

Known trade-off (not fixed here, flagged for you to decide):
    Tool functions are declared `async def` so ctx.info()/ctx.elicit()
    can be awaited, but the DB calls inside them are still synchronous
    (blocking) psycopg calls. That's fine for stdio / low concurrency.
    If you run this over HTTP with real concurrent traffic, look at
    asyncpg or running the DB calls in a thread pool
    (anyio.to_thread.run_sync).
"""

import csv
import io
from datetime import date
from typing import Annotated, Optional

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

# pyrefly: ignore [missing-import]
from database import get_connection


mcp = FastMCP("Expense Tracker MCP")


# ============================================================
# Shared parameter types (constraints live in the schema, not
# just in code, so the model can see them before calling)
# ============================================================

Amount = Annotated[
    float,
    Field(gt=0, description="Expense amount in your base currency. Must be greater than zero."),
]

Category = Annotated[
    str,
    Field(
        min_length=1,
        max_length=50,
        description=(
            "Expense category. Common values: Food, Travel, Shopping, "
            "Bills, Entertainment, Health, Other. Free text, but keep it "
            "consistent — get_category_summary groups by exact string match."
        ),
    ),
]

DateStr = Annotated[
    str,
    Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Date in YYYY-MM-DD format.",
        examples=["2026-08-19"],
    ),
]

ExpenseId = Annotated[int, Field(gt=0, description="The unique ID of the expense.")]


# ============================================================
# Helpers
# ============================================================

def expense_to_dict(row) -> dict:
    """Convert a PostgreSQL row into a JSON-friendly dictionary."""
    return {
        "id": row[0],
        "amount": float(row[1]),
        "category": row[2],
        "description": row[3],
        "expense_date": row[4].isoformat() if row[4] else None,
        "payment_method": row[5],
        "created_at": row[6].isoformat() if row[6] else None,
        "updated_at": row[7].isoformat() if row[7] else None,
    }


def _normalize_category(category: str) -> str:
    """Normalize category casing so 'food' and 'Food' don't become separate buckets."""
    return category.strip().title()


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _shift_months(d: date, delta: int) -> date:
    """Return the 1st of the month `delta` months away from d (delta can be negative)."""
    month_index = d.month - 1 + delta
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _validate_date(value: Optional[str], field_name: str) -> None:
    """Raise ToolError if value is set but not a valid ISO date."""
    if not value:
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"{field_name} must use YYYY-MM-DD format, got {value!r}.")


EXPENSE_COLUMNS = """
    id,
    amount,
    category,
    description,
    expense_date,
    payment_method,
    created_at,
    updated_at
"""


# ============================================================
# TOOLS
# ============================================================

@mcp.tool(
    annotations={
        "title": "Add Expense",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def add_expense(
    amount: Amount,
    category: Category,
    ctx: Context,
    description: str = "",
    expense_date: Optional[DateStr] = None,
    payment_method: str = "",
) -> dict:
    """
    Add a new expense to the expense tracker.

    Returns the created expense record, including its generated id.
    """
    _validate_date(expense_date, "expense_date")

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO expenses
                        (amount, category, description, expense_date, payment_method)
                    VALUES
                        (%s, %s, %s, COALESCE(%s::date, CURRENT_DATE), %s)
                    RETURNING {EXPENSE_COLUMNS};
                    """,
                    (amount, _normalize_category(category), description.strip(), expense_date, payment_method.strip()),
                )
                row = cursor.fetchone()
            conn.commit()
    except Exception as exc:
        raise ToolError(f"Failed to add expense: {exc}") from exc

    # pyrefly: ignore [unsupported-operation]
    await ctx.info(f"Added expense {row[0]}: {amount} in {category}.")

    return {
        "success": True,
        "message": "Expense added successfully.",
        "expense": expense_to_dict(row),
    }


@mcp.tool(
    annotations={
        "title": "Get Expense",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_expense(expense_id: ExpenseId, ctx: Context) -> dict:
    """Get a single expense by its ID."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {EXPENSE_COLUMNS} FROM expenses WHERE id = %s;",
                    (expense_id,),
                )
                row = cursor.fetchone()
    except Exception as exc:
        raise ToolError(f"Failed to fetch expense {expense_id}: {exc}") from exc

    if row is None:
        await ctx.debug(f"Expense {expense_id} not found.")
        return {"success": False, "message": f"Expense {expense_id} not found."}

    return {"success": True, "expense": expense_to_dict(row)}


@mcp.tool(
    annotations={
        "title": "List Recent Expenses",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def list_expenses(ctx: Context, limit: Annotated[int, Field(ge=1, le=100)] = 20) -> list[dict]:
    """Return the most recent expenses, newest first."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {EXPENSE_COLUMNS} FROM expenses
                    ORDER BY expense_date DESC, id DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to list expenses: {exc}") from exc

    await ctx.debug(f"Returned {len(rows)} expenses.")
    return [expense_to_dict(row) for row in rows]


@mcp.tool(
    annotations={
        "title": "Search Expenses",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def search_expenses(
    ctx: Context,
    category: Optional[Category] = None,
    payment_method: Optional[str] = None,
    start_date: Optional[DateStr] = None,
    end_date: Optional[DateStr] = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 100,
) -> list[dict]:
    """Search expenses using optional filters. All filters are AND-combined."""
    _validate_date(start_date, "start_date")
    _validate_date(end_date, "end_date")

    conditions = []
    parameters: list = []

    if category:
        conditions.append("LOWER(category) = LOWER(%s)")
        parameters.append(category.strip())
    if payment_method:
        conditions.append("LOWER(payment_method) = LOWER(%s)")
        parameters.append(payment_method.strip())
    if start_date:
        conditions.append("expense_date >= %s")
        parameters.append(start_date)
    if end_date:
        conditions.append("expense_date <= %s")
        parameters.append(end_date)

    query = f"SELECT {EXPENSE_COLUMNS} FROM expenses"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY expense_date DESC, id DESC LIMIT %s;"
    parameters.append(limit)

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # pyrefly: ignore [bad-argument-type]
                cursor.execute(query, parameters)
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Search failed: {exc}") from exc

    await ctx.debug(f"Search matched {len(rows)} expenses.")
    return [expense_to_dict(row) for row in rows]


@mcp.tool(
    annotations={
        "title": "Update Expense",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def update_expense(
    expense_id: ExpenseId,
    ctx: Context,
    amount: Optional[Amount] = None,
    category: Optional[Category] = None,
    description: Optional[str] = None,
    expense_date: Optional[DateStr] = None,
    payment_method: Optional[str] = None,
) -> dict:
    """Update an existing expense. Only the fields you provide are changed."""
    _validate_date(expense_date, "expense_date")

    fields = []
    parameters: list = []

    if amount is not None:
        fields.append("amount = %s")
        parameters.append(amount)
    if category is not None:
        fields.append("category = %s")
        parameters.append(_normalize_category(category))
    if description is not None:
        fields.append("description = %s")
        parameters.append(description.strip())
    if expense_date is not None:
        fields.append("expense_date = %s")
        parameters.append(expense_date)
    if payment_method is not None:
        fields.append("payment_method = %s")
        parameters.append(payment_method.strip())

    if not fields:
        raise ToolError("No fields were provided to update.")

    fields.append("updated_at = CURRENT_TIMESTAMP")
    parameters.append(expense_id)

    query = f"""
        UPDATE expenses
        SET {", ".join(fields)}
        WHERE id = %s
        RETURNING {EXPENSE_COLUMNS};
    """

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # pyrefly: ignore [bad-argument-type]
                cursor.execute(query, parameters)
                row = cursor.fetchone()
            conn.commit()
    except Exception as exc:
        raise ToolError(f"Failed to update expense {expense_id}: {exc}") from exc

    if row is None:
        return {"success": False, "message": f"Expense {expense_id} not found."}

    await ctx.info(f"Updated expense {expense_id}.")
    return {"success": True, "message": "Expense updated successfully.", "expense": expense_to_dict(row)}


class DeleteConfirmation(BaseModel):
    confirm: bool = Field(description="Set to true to confirm permanent deletion.")


@mcp.tool(
    annotations={
        "title": "Delete Expense",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def delete_expense(expense_id: ExpenseId, ctx: Context, confirm: bool = False) -> dict:
    """
    Delete an expense by ID. This is permanent.

    Set confirm=true to delete immediately. If confirm is omitted, this tries
    to ask for interactive confirmation; on a client that doesn't support that,
    it returns a message telling you to call again with confirm=true instead
    of failing outright.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT {EXPENSE_COLUMNS} FROM expenses WHERE id = %s;", (expense_id,))
                existing = cursor.fetchone()
    except Exception as exc:
        raise ToolError(f"Failed to look up expense {expense_id}: {exc}") from exc

    if existing is None:
        return {"success": False, "message": f"Expense {expense_id} not found."}

    expense = expense_to_dict(existing)

    if not confirm:
        try:
            result = await ctx.elicit(
                message=(
                    f"Delete expense #{expense_id} — {expense['amount']} in "
                    f"{expense['category']} on {expense['expense_date']}? This cannot be undone."
                ),
                response_type=DeleteConfirmation,
            )
        except Exception:
            # Client doesn't support elicitation (this is what produced the
            # "Method not found" error in testing). Fall back to requiring an
            # explicit confirm flag instead of failing the call outright.
            return {
                "success": False,
                "message": (
                    f"This client can't prompt for confirmation. To permanently delete "
                    f"expense #{expense_id} ({expense['amount']} in {expense['category']}), "
                    f"call delete_expense again with confirm=true."
                ),
            }

        if result.action != "accept" or not result.data.confirm:
            return {"success": False, "message": "Deletion cancelled."}

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM expenses WHERE id = %s RETURNING id;", (expense_id,))
                row = cursor.fetchone()
            conn.commit()
    except Exception as exc:
        raise ToolError(f"Failed to delete expense {expense_id}: {exc}") from exc

    await ctx.info(f"Deleted expense {expense_id}.")
    return {"success": True, "message": f"Expense {expense_id} deleted."}


@mcp.tool(
    annotations={
        "title": "Monthly Summary",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_monthly_summary(year: int, month: Annotated[int, Field(ge=1, le=12)], ctx: Context) -> dict:
    """Calculate total spending and expense count for a given month."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0), COUNT(*)
                    FROM expenses
                    WHERE EXTRACT(YEAR FROM expense_date) = %s
                      AND EXTRACT(MONTH FROM expense_date) = %s;
                    """,
                    (year, month),
                )
                # pyrefly: ignore [not-iterable]
                total, count = cursor.fetchone()
    except Exception as exc:
        raise ToolError(f"Failed to summarize {year}-{month}: {exc}") from exc

    return {"year": year, "month": month, "total_spent": float(total), "expense_count": count}


@mcp.tool(
    annotations={
        "title": "Category Summary",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_category_summary(ctx: Context) -> list[dict]:
    """Return total spending grouped by expense category, highest first."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT category, SUM(amount) AS total_spent, COUNT(*) AS expense_count
                    FROM expenses
                    GROUP BY category
                    ORDER BY total_spent DESC;
                    """
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to summarize categories: {exc}") from exc

    return [{"category": r[0], "total_spent": float(r[1]), "expense_count": r[2]} for r in rows]


@mcp.tool(
    annotations={
        "title": "Top Expenses",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_top_expenses(
    ctx: Context,
    limit: Annotated[int, Field(ge=1, le=50)] = 5,
    category: Optional[Category] = None,
) -> list[dict]:
    """Return the largest N expenses by amount, optionally filtered by category."""
    conditions = []
    parameters: list = []
    if category:
        conditions.append("LOWER(category) = LOWER(%s)")
        parameters.append(category.strip())

    query = f"SELECT {EXPENSE_COLUMNS} FROM expenses"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY amount DESC LIMIT %s;"
    parameters.append(limit)

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # pyrefly: ignore [bad-argument-type]
                cursor.execute(query, parameters)
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to fetch top expenses: {exc}") from exc

    return [expense_to_dict(row) for row in rows]


@mcp.tool(
    annotations={
        "title": "Spending Trend",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_spending_trend(ctx: Context, months: Annotated[int, Field(ge=1, le=24)] = 6) -> list[dict]:
    """
    Return total spending per month for the last N months, oldest first.
    Every month in the range is included, even ones with zero spending.
    """
    end_month = _month_start(date.today())
    start_month = _shift_months(end_month, -(months - 1))

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        gs.month_start,
                        COALESCE(SUM(e.amount), 0) AS total_spent,
                        COUNT(e.id) AS expense_count
                    FROM generate_series(%s::date, %s::date, interval '1 month') AS gs(month_start)
                    LEFT JOIN expenses e
                        ON DATE_TRUNC('month', e.expense_date) = gs.month_start
                    GROUP BY gs.month_start
                    ORDER BY gs.month_start ASC;
                    """,
                    (start_month, end_month),
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to compute spending trend: {exc}") from exc

    return [
        {"month": row[0].strftime("%Y-%m"), "total_spent": float(row[1]), "expense_count": row[2]}
        for row in rows
    ]


@mcp.tool(
    annotations={
        "title": "Export Expenses as CSV",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def export_expenses_csv(
    ctx: Context,
    start_date: Optional[DateStr] = None,
    end_date: Optional[DateStr] = None,
) -> str:
    """
    Export expenses as CSV text (id, amount, category, description, date, payment_method).
    Use this instead of search_expenses when you need many rows — CSV uses far fewer
    tokens than JSON for the same tabular data.
    """
    _validate_date(start_date, "start_date")
    _validate_date(end_date, "end_date")

    conditions = []
    parameters: list = []
    if start_date:
        conditions.append("expense_date >= %s")
        parameters.append(start_date)
    if end_date:
        conditions.append("expense_date <= %s")
        parameters.append(end_date)

    query = f"SELECT {EXPENSE_COLUMNS} FROM expenses"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY expense_date ASC;"

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # pyrefly: ignore [bad-argument-type]
                cursor.execute(query, parameters)
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to export expenses: {exc}") from exc

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "amount", "category", "description", "expense_date", "payment_method"])
    for row in rows:
        writer.writerow([row[0], float(row[1]), row[2], row[3], row[4], row[5]])

    await ctx.debug(f"Exported {len(rows)} expenses as CSV.")
    return buffer.getvalue()


# ============================================================
# RESOURCES
# ============================================================

@mcp.resource("expense://recent", mime_type="application/json")
def recent_expenses_resource() -> list[dict]:
    """Read-only resource containing the 20 most recent expenses."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {EXPENSE_COLUMNS} FROM expenses ORDER BY expense_date DESC, id DESC LIMIT 20;"
            )
            rows = cursor.fetchall()
    return [expense_to_dict(row) for row in rows]


@mcp.resource("expense://{expense_id}", mime_type="application/json")
def single_expense_resource(expense_id: int) -> dict:
    """Read-only resource for a single expense by ID."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT {EXPENSE_COLUMNS} FROM expenses WHERE id = %s;", (expense_id,))
            row = cursor.fetchone()
    if row is None:
        return {"error": f"Expense {expense_id} not found."}
    return expense_to_dict(row)


@mcp.resource("expense://summary/monthly/{year}/{month}", mime_type="application/json")
def monthly_summary_resource(year: int, month: int) -> dict:
    """Read-only monthly expense summary."""
    if month < 1 or month > 12:
        return {"error": "month must be between 1 and 12."}
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(SUM(amount), 0), COUNT(*)
                FROM expenses
                WHERE EXTRACT(YEAR FROM expense_date) = %s
                  AND EXTRACT(MONTH FROM expense_date) = %s;
                """,
                (year, month),
            )
            # pyrefly: ignore [not-iterable]
            total, count = cursor.fetchone()
    return {"year": year, "month": month, "total_spent": float(total), "expense_count": count}


@mcp.resource("expense://summary/categories", mime_type="application/json")
def category_summary_resource() -> list[dict]:
    """Read-only resource containing spending grouped by category."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT category, SUM(amount), COUNT(*) FROM expenses GROUP BY category ORDER BY SUM(amount) DESC;"
            )
            rows = cursor.fetchall()
    return [{"category": r[0], "total_spent": float(r[1]), "expense_count": r[2]} for r in rows]


@mcp.resource("expense://stats", mime_type="application/json")
def expense_stats_resource() -> dict:
    """Read-only overall expense statistics."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(amount), 0),
                    COALESCE(AVG(amount), 0),
                    COALESCE(MIN(amount), 0),
                    COALESCE(MAX(amount), 0)
                FROM expenses;
                """
            )
            # pyrefly: ignore [not-iterable]
            count, total, average, minimum, maximum = cursor.fetchone()
    return {
        "expense_count": count,
        "total_spent": float(total),
        "average_expense": float(average),
        "minimum_expense": float(minimum),
        "maximum_expense": float(maximum),
    }


# ============================================================
# PROMPTS
# ============================================================

@mcp.prompt
def analyze_spending(month: str) -> str:
    """Create a prompt for analyzing a month's spending (month as YYYY-MM)."""
    return f"""
You are a personal finance assistant.

Analyze spending for {month} using the available expense tools.

Instructions:
1. Call get_monthly_summary for the totals.
2. Call get_category_summary and get_top_expenses to see where the money went.
3. Point out any single category or expense that looks unusually large.
4. Summarize in 3-4 plain-language sentences, no jargon.
"""


@mcp.prompt
def budget_advice(monthly_budget: float) -> str:
    """Create a prompt asking for budget advice against a stated monthly budget."""
    return f"""
You are a personal finance assistant.

The user's monthly budget is {monthly_budget}.

Instructions:
1. Use get_spending_trend to see recent months' totals.
2. Compare the most recent month's total against the budget.
3. Use get_category_summary to identify the 1-2 categories most responsible
   for any overspend.
4. Suggest one concrete, specific change per category — not generic advice.
"""


# ============================================================
# SERVER
# ============================================================

if __name__ == "__main__":
    mcp.run()