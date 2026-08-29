# Expense Tracker MCP Server

A Model Context Protocol (MCP) server that turns Claude into a personal
finance assistant — add, search, update, delete, and analyze expenses
stored in PostgreSQL, entirely through natural language.

Built with [FastMCP](https://gofastmcp.com), backed by PostgreSQL, and
tested through real usage in Claude Desktop rather than left as an
unverified script.

## Why this exists

Most MCP demo servers stop at "here's a tool that adds a row." This one
tries to go further: proper input validation with schema-level constraints,
graceful error handling instead of raw stack traces reaching the model,
a destructive-action confirmation flow, and a documented QA pass that
actually found and fixed several real bugs. See [TESTING.md](./TESTING.md)
for the full writeup.

## Features

- **Full CRUD** on expenses — add, get, update, delete
- **Search & filter** by category, payment method, and date range
- **Analytics** — monthly totals, category breakdown, top expenses,
  a zero-filled month-over-month spending trend, statistical anomaly
  detection (flags expenses that are N× a category's average)
- **Budgets** — set a monthly limit per category, check spend against it
- **Recurring expenses** — templates for rent/subscriptions/etc., safely
  re-runnable materialization into real expense rows (no duplicates)
- **Multi-currency** — per-expense currency, static-rate conversion, and
  currency-scoped aggregation (every summary tool reports one currency at
  a time rather than silently mixing units — see [Architecture Notes](#architecture-notes))
- **Natural-language dates** — `"yesterday"`, `"last Tuesday"`, `"3 days ago"`,
  as well as strict `YYYY-MM-DD`
- **CSV export** for bulk data (cheaper on tokens than JSON for large
  result sets)
- **Safe deletes** — asks for confirmation via MCP elicitation where the
  client supports it, with a client-agnostic `confirm=true` fallback
  otherwise (see [Architecture Notes](#architecture-notes))
- **Read-only resources** (`expense://stats`, `expense://{id}`, etc.) and
  **reusable prompts** (`analyze_spending`, `budget_advice`) for MCP
  clients that support those primitives

## Tools

| Tool | Type | Description |
|---|---|---|
| `add_expense` | write | Add a new expense (accepts currency, natural-language dates) |
| `get_expense` | read | Fetch one expense by ID |
| `list_expenses` | read | Most recent expenses, newest first |
| `search_expenses` | read | Filter by category / payment method / date range |
| `update_expense` | write | Partial update — only provided fields change |
| `delete_expense` | write, destructive | Delete by ID, with confirmation |
| `get_monthly_summary` | read | Total spent + count for a given month, one currency |
| `get_category_summary` | read | Totals grouped by category, one currency, highest first |
| `get_top_expenses` | read | Largest N expenses, optional category filter |
| `get_spending_trend` | read | Month-over-month totals, one currency (zero-filled) |
| `export_expenses_csv` | read | Bulk export as CSV text |
| `convert_currency` | read | Convert an amount between currencies (static rates) |
| `set_budget` | write | Set/update a category's monthly budget (INR) |
| `get_budgets` | read | List all configured budgets |
| `check_budget_status` | read | Spend vs. budget per category for a month |
| `add_recurring_expense` | write | Create a recurring expense template |
| `list_recurring_expenses` | read | List recurring templates |
| `deactivate_recurring_expense` | write | Stop future generation from a template |
| `generate_recurring_expenses` | write | Materialize a month's recurring expenses (idempotent) |
| `get_expense_anomalies` | read | Flag expenses that are N× their category's average |

## Architecture

```mermaid
flowchart LR
    A[Claude Desktop / Claude Code] -- MCP over stdio --> B[Expense Tracker MCP Server]
    B -- psycopg3 --> C[(PostgreSQL)]
    B -- ctx.elicit / ctx.info --> A
```

The server exposes 20 tools, 5 resources, and 2 prompts on top of the
`expenses`, `budgets`, and `recurring_expenses` tables (schema in
[`schema.sql`](./schema.sql)).

## Architecture notes

**Why `confirm=true` exists alongside elicitation.** MCP defines
elicitation (the server asking the client to show a confirmation dialog) as
an optional capability. Not every client implements it — Claude Desktop's
chat interface, for instance, currently supports the *tools* primitive
fully but not *resources* or *prompts*, and elicitation support varies by
client version. `delete_expense` tries elicitation first for a better UX,
but falls back to requiring an explicit `confirm=true` argument so the tool
still works — safely — on clients that can't show a native prompt. Details
and the bug this fixes are in [TESTING.md](./TESTING.md).

**Why categories are normalized at write time, not read time.** Early
testing showed `"food"` and `"Food"` being treated as the same category by
search (case-insensitive matching) but as different categories by the
summary tool (exact grouping). Rather than patch every read query to agree
on a matching rule, `add_expense`/`update_expense` normalize casing once,
at the point of insertion — so every downstream query is naturally
consistent without special-casing.

**Why currency is partitioned, not merged.** Every aggregation tool
(`get_category_summary`, `get_monthly_summary`, `get_spending_trend`,
`get_expense_anomalies`) takes a `currency` parameter (default `INR`) and
only ever sums/averages within that one currency. There is deliberately no
"total across all currencies" anywhere — adding ₹100 and $100 together as
if they were the same unit is worse than not answering at all. A true
converted rollup (via `convert_currency`) is a possible future feature, not
something faked here. `check_budget_status` follows the same principle:
budgets are INR-only, so it explicitly filters spend to INR rather than
quietly including foreign-currency expenses in a category's budget check.

## Setup

### 1. Database

```bash
createdb expense_tracker
psql -d expense_tracker -f schema.sql
```

### 2. Environment

Copy the example file and fill in your own database connection string:

```bash
cp .env.example .env
```

`.env` should contain:

```
DATABASE_URL=postgresql://username:password@localhost:5432/expense_tracker
```

`.env` is git-ignored — never commit real credentials.

### 3. Install & run

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency
management:

```bash
uv sync
uv run expense_tracker_mcp_server.py
```

*(No `uv`? A plain `pip install -r requirements.txt` followed by
`python expense_tracker_mcp_server.py` works too — `uv` just handles the
virtual environment and lockfile for you.)*

### 4. Connect it to an MCP client

**Claude Desktop** — add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "expense-tracker": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/02_expense_tracker",
        "run",
        "expense_tracker_mcp_server.py"
      ]
    }
  }
}
```

Replace `/absolute/path/to/02_expense_tracker` with this folder's actual
path on your machine, then restart Claude Desktop. The tools will be
available in a new conversation. See [`mcp.json`](./mcp.json) for the
same configuration as a standalone file.

## Tech stack

- **[FastMCP](https://gofastmcp.com)** — Python MCP server framework
- **PostgreSQL** + **psycopg3** — data layer
- **Pydantic** — schema validation (`Annotated` + `Field` constraints on
  every tool parameter)
- **Model Context Protocol** — tools, resources, prompts, elicitation

## Testing

See [TESTING.md](./TESTING.md) for the full QA writeup: three rounds,
90+ manually-run scenarios, real bugs found and fixed at each stage —
a broken delete path, a spending-trend query that silently dropped
zero-spend months, a category-casing inconsistency, cross-currency
aggregation silently mixing units, and a missing CSV column — plus
adversarial checks (SQL injection attempt, malformed dates, oversized
input, delete idempotency, recurring-expense re-generation idempotency).

## Known limitations

- DB calls are synchronous `psycopg` calls inside `async def` tool
  functions — fine for stdio / single-user use, but under real concurrent
  HTTP traffic they'd block the event loop. `asyncpg` or a thread pool
  would be the next step if this ever needs to scale.
- `amount` is stored as `NUMERIC` in Postgres but surfaced as Python
  `float` in tool responses — acceptable for a personal tracker, not
  something I'd ship for a system doing real accounting.
- Resources and prompts are implemented to spec but not exercisable
  through Claude Desktop's current chat UI (tools-only support at this
  writing) — verified instead via MCP Inspector.
- No automated test suite yet — testing so far has been structured manual
  QA through the live client (see Roadmap).
- No true multi-currency rollup — every aggregation tool reports one
  currency at a time by design (see Architecture Notes above), not a
  blended total across currencies.
- `add_expense` has no duplicate-request protection.
- Recurring expense templates don't carry a currency field — generated
  rows are always INR.

## Roadmap

- [ ] `pytest` suite against a disposable test database
- [x] ~~Budget-limit tool~~ — done: `set_budget` / `check_budget_status`
- [x] ~~Recurring-expense support~~ — done: `add_recurring_expense` /
      `generate_recurring_expenses`
- [x] ~~Multi-currency handling~~ — done, currency-scoped (see Known
      Limitations for what's still not covered)
- [ ] True multi-currency rollup (convert-and-sum across currencies)
- [ ] Async DB layer for HTTP-transport deployment
- [ ] LangGraph agent as a dedicated client on top of this server
- [ ] Docker Compose for one-command local setup

## License

MIT — see [LICENSE](../LICENSE).

## Author

Built by [Deepak Kumar Singh](https://github.com/CodeWithDks) as part of a
hands-on Generative AI / agentic tooling learning path (LangChain,
LangGraph, and the MCP ecosystem).