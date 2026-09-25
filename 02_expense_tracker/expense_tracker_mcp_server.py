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
import re
from datetime import date
from typing import Annotated, Optional

import dateparser

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
    Field(
        gt=0,
        description=(
            "Expense amount, in the currency given by the `currency` parameter "
            "(defaults to INR if not specified). Always pass the currency via "
            "that parameter — never embed it in the description text instead."
        ),
    ),
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

Currency = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z]{3}$",
        description="3-letter currency code, e.g. INR, USD, EUR. Defaults to INR.",
    ),
]

FlexibleDateStr = Annotated[
    str,
    Field(
        description=(
            "A date. Accepts strict YYYY-MM-DD, or natural language like "
            "'yesterday', 'last Tuesday', '3 days ago'. Ambiguous phrases "
            "resolve to the most recent matching past date."
        ),
        examples=["2026-08-19", "yesterday", "last Friday"],
    ),
]

DayOfMonth = Annotated[
    int,
    Field(ge=1, le=28, description="Day of the month this recurs on (1-28, to stay valid in every month)."),
]


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
        "currency": row[8],
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


# Static rates relative to 1 INR. Good enough for a personal tracker demo —
# swap for a live FX API if this ever needs to be accurate day-to-day.
EXCHANGE_RATES_PER_INR = {
    "INR": 1.0,
    "USD": 0.012,
    "EUR": 0.011,
    "GBP": 0.0095,
    "AED": 0.044,
    "JPY": 1.78,
}


def _convert_currency(amount: float, from_currency: str, to_currency: str) -> float:
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    if from_currency not in EXCHANGE_RATES_PER_INR:
        raise ToolError(f"Unsupported currency: {from_currency!r}.")
    if to_currency not in EXCHANGE_RATES_PER_INR:
        raise ToolError(f"Unsupported currency: {to_currency!r}.")
    amount_in_inr = amount / EXCHANGE_RATES_PER_INR[from_currency]
    return round(amount_in_inr * EXCHANGE_RATES_PER_INR[to_currency], 2)


def _resolve_expense_date(value: Optional[str]) -> Optional[str]:
    """
    Accept either strict YYYY-MM-DD or a natural-language phrase
    ('yesterday', 'last Tuesday') and return a strict YYYY-MM-DD string.
    """
    if not value:
        return None

    try:
        date.fromisoformat(value)
        return value
    except ValueError:
        pass

    # dateparser has a known quirk: "last Tuesday" / "this Friday" return
    # None even though the bare weekday name ("Tuesday") parses correctly
    # to the most recent past occurrence. Strip that prefix before parsing.
    cleaned = re.sub(r"^(last|this)\s+", "", value.strip(), flags=re.IGNORECASE)

    parsed = dateparser.parse(cleaned, settings={"PREFER_DATES_FROM": "past"})
    if parsed is None:
        raise ToolError(
            f"Could not understand expense_date {value!r}. "
            "Use YYYY-MM-DD or a phrase like 'yesterday' or 'last Tuesday'."
        )
    return parsed.date().isoformat()


EXPENSE_COLUMNS = """
    id,
    amount,
    category,
    description,
    expense_date,
    payment_method,
    created_at,
    updated_at,
    currency
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
    expense_date: Optional[FlexibleDateStr] = None,
    payment_method: str = "",
    currency: Currency = "INR",
) -> dict:
    """
    Add a new expense to the expense tracker.

    Returns the created expense record, including its generated id.
    """
    resolved_date = _resolve_expense_date(expense_date)

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO expenses
                        (amount, category, description, expense_date, payment_method, currency)
                    VALUES
                        (%s, %s, %s, COALESCE(%s::date, CURRENT_DATE), %s, %s)
                    RETURNING {EXPENSE_COLUMNS};
                    """,
                    (
                        amount,
                        _normalize_category(category),
                        description.strip(),
                        resolved_date,
                        payment_method.strip(),
                        currency.upper(),
                    ),
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
                    f"SELECT {EXPENSE_COLUMNS} FROM expenses WHERE id = %s AND deleted_at IS NULL;",
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
                    WHERE deleted_at IS NULL
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

    conditions = ["deleted_at IS NULL"]
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

    query = f"SELECT {EXPENSE_COLUMNS} FROM expenses WHERE " + " AND ".join(conditions)
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
    expense_date: Optional[FlexibleDateStr] = None,
    payment_method: Optional[str] = None,
    currency: Optional[Currency] = None,
) -> dict:
    """Update an existing expense. Only the fields you provide are changed."""
    resolved_date = _resolve_expense_date(expense_date) if expense_date is not None else None

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
    if resolved_date is not None:
        fields.append("expense_date = %s")
        parameters.append(resolved_date)
    if payment_method is not None:
        fields.append("payment_method = %s")
        parameters.append(payment_method.strip())
    if currency is not None:
        fields.append("currency = %s")
        parameters.append(currency.upper())

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
    Delete an expense by ID. This is a soft delete — the row is hidden from
    all normal reads immediately, but recoverable via restore_expense.

    Set confirm=true to delete immediately. If confirm is omitted, this tries
    to ask for interactive confirmation; on a client that doesn't support that,
    it returns a message telling you to call again with confirm=true instead
    of failing outright.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {EXPENSE_COLUMNS} FROM expenses WHERE id = %s AND deleted_at IS NULL;",
                    (expense_id,),
                )
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
                    f"{expense['category']} on {expense['expense_date']}? "
                    f"(This can be undone with restore_expense afterward.)"
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
                    f"This client can't prompt for confirmation. To delete "
                    f"expense #{expense_id} ({expense['amount']} in {expense['category']}), "
                    f"call delete_expense again with confirm=true."
                ),
            }

        if result.action != "accept" or not result.data.confirm:
            return {"success": False, "message": "Deletion cancelled."}

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE expenses SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING id;",
                    (expense_id,),
                )
                row = cursor.fetchone()
            conn.commit()
    except Exception as exc:
        raise ToolError(f"Failed to delete expense {expense_id}: {exc}") from exc

    await ctx.info(f"Soft-deleted expense {expense_id}.")
    return {"success": True, "message": f"Expense {expense_id} deleted (recoverable via restore_expense)."}


@mcp.tool(
    annotations={
        "title": "Restore Expense",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def restore_expense(expense_id: ExpenseId, ctx: Context) -> dict:
    """Undo a delete — bring a soft-deleted expense back."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE expenses
                    SET deleted_at = NULL
                    WHERE id = %s AND deleted_at IS NOT NULL
                    RETURNING {EXPENSE_COLUMNS};
                    """,
                    (expense_id,),
                )
                row = cursor.fetchone()
    except Exception as exc:
        raise ToolError(f"Failed to restore expense {expense_id}: {exc}") from exc

    if row is None:
        return {
            "success": False,
            "message": f"Expense {expense_id} isn't in the deleted list (either it doesn't exist or was never deleted).",
        }

    await ctx.info(f"Restored expense {expense_id}.")
    return {"success": True, "message": f"Expense {expense_id} restored.", "expense": expense_to_dict(row)}


@mcp.tool(
    annotations={
        "title": "List Deleted Expenses",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def list_deleted_expenses(ctx: Context, limit: Annotated[int, Field(ge=1, le=100)] = 20) -> list[dict]:
    """List soft-deleted expenses that can still be restored."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {EXPENSE_COLUMNS} FROM expenses
                    WHERE deleted_at IS NOT NULL
                    ORDER BY deleted_at DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to list deleted expenses: {exc}") from exc

    return [expense_to_dict(row) for row in rows]


@mcp.tool(
    annotations={
        "title": "Monthly Summary",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_monthly_summary(year: int, month: Annotated[int, Field(ge=1, le=12)], ctx: Context, currency: Currency = "INR") -> dict:
    """Calculate total spending and expense count for a given month, in one currency (default INR)."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0), COUNT(*)
                    FROM expenses
                    WHERE EXTRACT(YEAR FROM expense_date) = %s
                      AND EXTRACT(MONTH FROM expense_date) = %s
                      AND currency = %s
                      AND deleted_at IS NULL;
                    """,
                    (year, month, currency.upper()),
                )
                # pyrefly: ignore [not-iterable]
                total, count = cursor.fetchone()
    except Exception as exc:
        raise ToolError(f"Failed to summarize {year}-{month}: {exc}") from exc

    return {"year": year, "month": month, "currency": currency.upper(), "total_spent": float(total), "expense_count": count}


@mcp.tool(
    annotations={
        "title": "Category Summary",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_category_summary(ctx: Context, currency: Currency = "INR") -> list[dict]:
    """
    Return total spending grouped by expense category, highest first,
    for a single currency (default INR). Amounts are never summed across
    currencies — pass `currency` to view a different one.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT category, SUM(amount) AS total_spent, COUNT(*) AS expense_count
                    FROM expenses
                    WHERE currency = %s AND deleted_at IS NULL
                    GROUP BY category
                    ORDER BY total_spent DESC;
                    """,
                    (currency.upper(),),
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to summarize categories: {exc}") from exc

    return [{"category": r[0], "currency": currency.upper(), "total_spent": float(r[1]), "expense_count": r[2]} for r in rows]


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
    conditions = ["deleted_at IS NULL"]
    parameters: list = []
    if category:
        conditions.append("LOWER(category) = LOWER(%s)")
        parameters.append(category.strip())

    query = f"SELECT {EXPENSE_COLUMNS} FROM expenses WHERE " + " AND ".join(conditions)
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
async def get_spending_trend(ctx: Context, months: Annotated[int, Field(ge=1, le=24)] = 6, currency: Currency = "INR") -> list[dict]:
    """
    Return total spending per month for the last N months, oldest first,
    in a single currency (default INR). Every month in the range is
    included, even ones with zero spending in that currency.
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
                        AND e.currency = %s
                        AND e.deleted_at IS NULL
                    GROUP BY gs.month_start
                    ORDER BY gs.month_start ASC;
                    """,
                    (start_month, end_month, currency.upper()),
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to compute spending trend: {exc}") from exc

    return [
        {"month": row[0].strftime("%Y-%m"), "currency": currency.upper(), "total_spent": float(row[1]), "expense_count": row[2]}
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

    conditions = ["deleted_at IS NULL"]
    parameters: list = []
    if start_date:
        conditions.append("expense_date >= %s")
        parameters.append(start_date)
    if end_date:
        conditions.append("expense_date <= %s")
        parameters.append(end_date)

    query = f"SELECT {EXPENSE_COLUMNS} FROM expenses WHERE " + " AND ".join(conditions)
    query += " ORDER BY expense_date ASC;"

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # pyrefly: ignore [arg-type, bad-argument-type]
                cursor.execute(query, parameters)
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to export expenses: {exc}") from exc

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "amount", "currency", "category", "description", "expense_date", "payment_method"])
    for row in rows:
        writer.writerow([row[0], float(row[1]), row[8], row[2], row[3], row[4], row[5]])

    await ctx.debug(f"Exported {len(rows)} expenses as CSV.")
    return buffer.getvalue()


@mcp.tool(
    annotations={
        "title": "Convert Currency",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def convert_currency(amount: Amount, from_currency: Currency, to_currency: Currency, ctx: Context) -> dict:
    """
    Convert an amount between currencies using a static rate table.
    Rates are fixed in this server (not live) — good for rough comparisons,
    not for anything that needs today's real exchange rate.
    """
    converted = _convert_currency(amount, from_currency, to_currency)
    return {
        "amount": amount,
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper(),
        "converted_amount": converted,
    }


@mcp.tool(
    annotations={
        "title": "Set Budget",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def set_budget(category: Category, monthly_limit: Annotated[float, Field(gt=0)], ctx: Context) -> dict:
    """Set (or update) the monthly spending limit for a category, in INR."""
    normalized = _normalize_category(category)
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO budgets (category, monthly_limit, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (category)
                    DO UPDATE SET monthly_limit = EXCLUDED.monthly_limit, updated_at = CURRENT_TIMESTAMP;
                    """,
                    (normalized, monthly_limit),
                )
            conn.commit()
    except Exception as exc:
        raise ToolError(f"Failed to set budget for {normalized}: {exc}") from exc

    await ctx.info(f"Set budget for {normalized}: {monthly_limit}/month.")
    return {"success": True, "category": normalized, "monthly_limit": monthly_limit}


@mcp.tool(
    annotations={
        "title": "Get Budgets",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_budgets(ctx: Context) -> list[dict]:
    """List all configured category budgets."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT category, monthly_limit FROM budgets ORDER BY category;")
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to fetch budgets: {exc}") from exc

    return [{"category": r[0], "monthly_limit": float(r[1])} for r in rows]


@mcp.tool(
    annotations={
        "title": "Check Budget Status",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def check_budget_status(year: int, month: Annotated[int, Field(ge=1, le=12)], ctx: Context) -> list[dict]:
    """
    Compare actual spending against each category's budget for a given month.
    Only categories that have a budget set (via set_budget) are returned.
    Budgets are INR-only, so `spent` only counts INR expenses — non-INR
    expenses in a budgeted category are excluded, not silently mixed in.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        b.category,
                        b.monthly_limit,
                        COALESCE(SUM(e.amount), 0) AS spent
                    FROM budgets b
                    LEFT JOIN expenses e
                        ON e.category = b.category
                        AND e.currency = 'INR'
                        AND e.deleted_at IS NULL
                        AND EXTRACT(YEAR FROM e.expense_date) = %s
                        AND EXTRACT(MONTH FROM e.expense_date) = %s
                    GROUP BY b.category, b.monthly_limit
                    ORDER BY b.category;
                    """,
                    (year, month),
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to check budget status for {year}-{month}: {exc}") from exc

    results = []
    for category, monthly_limit, spent in rows:
        monthly_limit = float(monthly_limit)
        spent = float(spent)
        results.append(
            {
                "category": category,
                "monthly_limit": monthly_limit,
                "spent": spent,
                "remaining": round(monthly_limit - spent, 2),
                "over_budget": spent > monthly_limit,
            }
        )
    return results


@mcp.tool(
    annotations={
        "title": "Add Recurring Expense",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def add_recurring_expense(
    amount: Amount,
    category: Category,
    day_of_month: DayOfMonth,
    ctx: Context,
    description: str = "",
    payment_method: str = "",
) -> dict:
    """Create a recurring expense template (e.g. rent on the 1st, Netflix on the 5th)."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO recurring_expenses
                        (amount, category, description, payment_method, day_of_month)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, amount, category, description, payment_method, day_of_month, active;
                    """,
                    (amount, _normalize_category(category), description.strip(), payment_method.strip(), day_of_month),
                )
                row = cursor.fetchone()
            conn.commit()
    except Exception as exc:
        raise ToolError(f"Failed to add recurring expense: {exc}") from exc

    # pyrefly: ignore [unsupported-operation]
    await ctx.info(f"Added recurring expense {row[0]}: {amount} in {category} on day {day_of_month}.")
    return {
        "success": True,
        "recurring_expense": {
            # pyrefly: ignore [unsupported-operation]
            "id": row[0], "amount": float(row[1]), "category": row[2],
            # pyrefly: ignore [unsupported-operation]
            "description": row[3], "payment_method": row[4],
            # pyrefly: ignore [unsupported-operation]
            "day_of_month": row[5], "active": row[6],
        },
    }


@mcp.tool(
    annotations={
        "title": "List Recurring Expenses",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def list_recurring_expenses(ctx: Context, active_only: bool = True) -> list[dict]:
    """List recurring expense templates."""
    query = "SELECT id, amount, category, description, payment_method, day_of_month, active FROM recurring_expenses"
    if active_only:
        query += " WHERE active = TRUE"
    query += " ORDER BY day_of_month;"

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to list recurring expenses: {exc}") from exc

    return [
        {
            "id": r[0], "amount": float(r[1]), "category": r[2],
            "description": r[3], "payment_method": r[4],
            "day_of_month": r[5], "active": r[6],
        }
        for r in rows
    ]


@mcp.tool(
    annotations={
        "title": "Deactivate Recurring Expense",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def deactivate_recurring_expense(recurring_id: Annotated[int, Field(gt=0)], ctx: Context) -> dict:
    """Stop a recurring expense from being generated in future months. Past generated rows are untouched."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE recurring_expenses SET active = FALSE WHERE id = %s RETURNING id;",
                    (recurring_id,),
                )
                row = cursor.fetchone()
            conn.commit()
    except Exception as exc:
        raise ToolError(f"Failed to deactivate recurring expense {recurring_id}: {exc}") from exc

    if row is None:
        return {"success": False, "message": f"Recurring expense {recurring_id} not found."}
    return {"success": True, "message": f"Recurring expense {recurring_id} deactivated."}


@mcp.tool(
    annotations={
        "title": "Generate Recurring Expenses",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def generate_recurring_expenses(
    ctx: Context,
    year: int,
    month: Annotated[int, Field(ge=1, le=12)],
) -> dict:
    """
    Materialize active recurring templates into real expense rows for the
    given month. Safe to call more than once for the same month — templates
    already materialized for that month are skipped, not duplicated.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, amount, category, description, payment_method, day_of_month "
                    "FROM recurring_expenses WHERE active = TRUE;"
                )
                templates = cursor.fetchall()

                created = []
                skipped = []
                for template_id, amount, category, description, payment_method, day_of_month in templates:
                    cursor.execute(
                        """
                        SELECT id FROM expenses
                        WHERE source_recurring_id = %s
                          AND EXTRACT(YEAR FROM expense_date) = %s
                          AND EXTRACT(MONTH FROM expense_date) = %s;
                        """,
                        (template_id, year, month),
                    )
                    if cursor.fetchone() is not None:
                        skipped.append(template_id)
                        continue

                    expense_date = date(year, month, min(day_of_month, 28))
                    cursor.execute(
                        f"""
                        INSERT INTO expenses
                            (amount, category, description, expense_date, payment_method, source_recurring_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING {EXPENSE_COLUMNS};
                        """,
                        (amount, category, description, expense_date, payment_method, template_id),
                    )
                    created.append(expense_to_dict(cursor.fetchone()))
            conn.commit()
    except Exception as exc:
        raise ToolError(f"Failed to generate recurring expenses for {year}-{month}: {exc}") from exc

    await ctx.info(f"Generated {len(created)} recurring expenses for {year}-{month}, skipped {len(skipped)} already-existing.")
    return {"created": created, "skipped_template_ids": skipped}


@mcp.tool(
    annotations={
        "title": "Get Expense Anomalies",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_expense_anomalies(
    ctx: Context,
    threshold: Annotated[float, Field(gt=1.0, le=10.0)] = 2.0,
    currency: Currency = "INR",
) -> list[dict]:
    """
    Flag expenses that are unusually large for their category — anything
    more than `threshold` times that category's average — within a single
    currency (default INR), so a $5 coffee is never compared against a
    ₹500 coffee. Categories need at least 2 expenses in that currency to
    have a meaningful average.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    WITH category_avg AS (
                        SELECT category, AVG(amount) AS avg_amount, COUNT(*) AS n
                        FROM expenses
                        WHERE currency = %s AND deleted_at IS NULL
                        GROUP BY category
                        HAVING COUNT(*) >= 2
                    )
                    SELECT
                        e.id, e.amount, e.category, e.description, e.expense_date,
                        e.payment_method, e.created_at, e.updated_at, e.currency,
                        ca.avg_amount
                    FROM expenses e
                    JOIN category_avg ca ON ca.category = e.category
                    WHERE e.currency = %s
                      AND e.deleted_at IS NULL
                      AND e.amount > ca.avg_amount * %s
                    ORDER BY e.amount DESC;
                    """,
                    (currency.upper(), currency.upper(), threshold),
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise ToolError(f"Failed to compute anomalies: {exc}") from exc

    results = []
    for row in rows:
        expense = expense_to_dict(row[:9])
        avg_amount = float(row[9])
        expense["category_average"] = round(avg_amount, 2)
        expense["times_average"] = round(float(row[1]) / avg_amount, 2)
        results.append(expense)
    return results


# ============================================================
# RESOURCES
# ============================================================

@mcp.resource("expense://recent", mime_type="application/json")
def recent_expenses_resource() -> list[dict]:
    """Read-only resource containing the 20 most recent expenses."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {EXPENSE_COLUMNS} FROM expenses WHERE deleted_at IS NULL ORDER BY expense_date DESC, id DESC LIMIT 20;"
            )
            rows = cursor.fetchall()
    return [expense_to_dict(row) for row in rows]


@mcp.resource("expense://{expense_id}", mime_type="application/json")
def single_expense_resource(expense_id: int) -> dict:
    """Read-only resource for a single expense by ID."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {EXPENSE_COLUMNS} FROM expenses WHERE id = %s AND deleted_at IS NULL;",
                (expense_id,),
            )
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
                  AND EXTRACT(MONTH FROM expense_date) = %s
                  AND deleted_at IS NULL;
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
                "SELECT category, SUM(amount), COUNT(*) FROM expenses WHERE deleted_at IS NULL GROUP BY category ORDER BY SUM(amount) DESC;"
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
                FROM expenses
                WHERE deleted_at IS NULL;
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