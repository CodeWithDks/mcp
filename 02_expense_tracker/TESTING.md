# Testing Notes

This project was tested manually through Claude Desktop, in three rounds. This
is not an automated test suite (there is no `pytest` harness in this repo
yet — see Roadmap in the README) — it's a documented, deliberate QA pass
using natural-language prompts against the live MCP server, which is a
realistic way to test a tool an LLM is meant to call.

## Round 1 — Initial QA sweep (50 scenarios)

Covered all 11 original tools: CRUD operations, filtered search, aggregation
(monthly/category summaries, top expenses, spending trend), CSV export, and
input validation (rejecting zero/negative amounts, malformed dates).

**Result: 44 pass / 5 partial / 1 fail.**

Findings:

| Issue | Severity | Root cause |
|---|---|---|
| `delete_expense` returned "Method not found" | Critical | The tool used `ctx.elicit()` for confirmation; the connected client didn't implement the `elicitation/create` RPC method, so the round-trip failed outright |
| `get_spending_trend` silently skipped zero-spend months | Medium | `GROUP BY` on the expenses table can only produce rows for months that already have data — there was no month scaffold to `LEFT JOIN` against |
| `search_expenses` (case-insensitive) and `get_category_summary` (exact match) disagreed on category casing | Medium | Nothing normalized category casing at write time, so `"Food"` and `"food"` were stored as distinct values |
| Expense count in a model-generated summary didn't match the actual row count | Low | Not a server bug — the model miscounted while summarizing a 15-row result in prose during that session |

## Fixes applied

1. **`delete_expense`** — added an explicit `confirm: bool` parameter as the
   primary, client-agnostic path. Elicitation is still attempted first for
   clients that support it (a nicer UX — an in-chat confirmation dialog),
   but a failure to elicit now falls back to a clear "call again with
   `confirm=true`" message instead of an opaque RPC error.
2. **`get_spending_trend`** — rewritten to `generate_series()` the full
   month range first, then `LEFT JOIN` expenses onto it, so every month in
   the window is represented, zero-spend or not.
3. **Category normalization** — `add_expense` and `update_expense` now
   title-case and strip category input before writing, so `"food"` and
   `"Food"` collapse into a single canonical value at the source instead of
   being reconciled at every read site.

## Round 2 — Regression + edge-case pass (15 scenarios)

Re-ran the three fixed behaviors, then pushed on cases the first pass hadn't
covered:

| Area | Scenarios | Result |
|---|---|---|
| Delete regression | Delete with no `confirm`, with `confirm=true`, on a second distinct ID | Pass — confirmed twice, on two different rows |
| Delete idempotency | Delete the same ID twice in a row | Pass — 2nd call returns "not found," not an error or silent no-op |
| Delete decline path | Elicitation prompt shown, user declines, row re-fetched | Pass — declining leaves the row untouched |
| Category normalization regression | Add same category in two different cases, check summary | Pass — merged into one row |
| SQL injection attempt | Category field set to a `'; DROP TABLE ...` payload | Pass — stored as an inert literal string; table unaffected |
| Not-found handling | `update_expense` / `delete_expense` on a nonexistent ID | Pass — clean `"not found"` message, no crash |
| Spending trend regression | 6-month trend request | Pass — 6 consecutive months returned, zero-fill confirmed |
| Date validation | Wrong format (`30-08-2026`), invalid calendar date (`2026-02-30`) | Pass — both rejected, including the shape-valid-but-calendar-invalid case |
| Field length limit | 75-character category (limit is 50) | Pass — rejected before any write; row confirmed unchanged afterward |
| List pagination | `limit=5`, `limit=100` against a smaller actual dataset | Pass — correct count both times, no error when limit exceeds row count |
| Resources / Prompts | Read `expense://stats`, invoke `analyze_spending` prompt, via Claude Desktop | **Not reachable** — Claude Desktop's chat UI currently exposes only the MCP *tools* primitive, not *resources* or *prompts*. This is a client-side limitation, not a server bug; both primitives are implemented correctly and are reachable via MCP Inspector or Claude Code. |

## Round 3 — New feature testing (9 tools added, ~25 scenarios)

Five new capabilities were added: multi-currency support, natural-language
date parsing, budgets, recurring expenses, and anomaly detection — bringing
the tool count from 11 to 20. Tested feature-by-feature, then cross-checked
where features intersect (currency × aggregation, in particular).

| Area | Scenarios | Result |
|---|---|---|
| Currency storage | Add expense with explicit `currency="USD"`; add without (defaults to INR) | Pass — correct default; explicit currency round-tripped correctly *when the parameter was actually passed* (see finding below) |
| `convert_currency` | USD→INR, unsupported currency code | Pass — real conversion; unsupported code rejected cleanly |
| Natural-language dates | `"yesterday"`, `"last Tuesday"`, `"3 days ago"`, strict `YYYY-MM-DD`, garbage input | Pass — all four valid phrasings resolved to correct calendar dates relative to real current date; garbage input rejected with a clear message, not a silent bad insert |
| Budgets | `set_budget` (including upserting an existing budget both up and down), `get_budgets`, `check_budget_status` for a budgeted and an un-budgeted category | Pass — upsert confirmed bidirectional; un-budgeted categories correctly absent from status rather than shown as zero |
| Recurring expenses | Add template, invalid `day_of_month` (30, rejected — max is 28), generate for a month, generate again for the *same* month (idempotency), deactivate, generate for a *future* month post-deactivation | Pass on all — repeat generation correctly skipped rather than duplicating; deactivation stopped future generation without touching already-generated history |
| Anomaly detection | Default threshold (2x), lowered threshold (1.2x, more sensitive), threshold above the allowed max (rejected), single-entry category (correctly excluded, not flagged) | Pass — threshold genuinely changes sensitivity; the "needs ≥2 expenses per category" guard correctly prevented a brand-new large expense from being flagged against a nonexistent average |
| Not-found / idempotency regression | `update_expense` / `delete_expense` on a nonexistent ID; delete the same ID twice; decline an elicitation prompt and re-fetch | Pass — consistent with Round 2 results, still holding after 9 new tools were added |

### Findings

| Issue | Severity | Root cause |
|---|---|---|
| A USD expense was stored as `currency: "INR"` despite the user's prompt saying "currency USD" | Not a server bug | The model wrote "USD" into the free-text `description` field instead of passing the dedicated `currency` argument — a tool-calling interpretation issue, not a validation gap. Traced by checking what was *actually* in the stored `description` ("Hotel booking (USD)") vs what should have been in `currency`. |
| Cross-currency aggregation was silently wrong | **High** | `get_category_summary`, `get_monthly_summary`, `get_spending_trend`, `get_expense_anomalies`, and `check_budget_status` all did `SUM()`/`AVG()` across the `amount` column with no regard for `currency` — a ₹100 row and a $100 row were added as if they were the same unit. |
| `export_expenses_csv` had no `currency` column | **Medium** | The column was added to the `expenses` table and to every other output path (`expense_to_dict`, all JSON-returning tools) when currency support was built, but the CSV writer builds its row manually and was missed in that pass. |
| A duplicate expense (two identical hotel-booking rows) appeared | Not a server bug | Root cause not conclusively identified — could be the model calling `add_expense` twice for one user prompt, or the user's own prompt being sent twice. `add_expense` has no built-in duplicate-request protection either way; flagged as a possible future improvement, not fixed. |
| A model-generated prose total (₹7,710) didn't match the tool-computed total (₹7,810) for the same 11 rows | Not a server bug | Same class of issue as the Round 1 "14 vs 15" count slip — the model hand-summed a displayed table instead of trusting `get_monthly_summary`'s actual `SUM()`. Confirms the value of using aggregation tools over asking the model to add up displayed rows. |

### Fixes applied

1. **Currency-scoped aggregation.** `get_category_summary`, `get_monthly_summary`,
   and `get_spending_trend` each gained a `currency: Currency = "INR"` parameter
   and now filter to a single currency per call rather than mixing units — the
   response includes which currency it's reporting so it's never ambiguous.
   `get_expense_anomalies` does the same, so a category's average is never
   computed across mixed currencies. `check_budget_status` (which has no
   currency parameter of its own, since `budgets` is INR-only) now explicitly
   filters `spent` to `currency = 'INR'` instead of summing everything.
   This is a deliberate **partition, not merge** design: there's no unified
   "total across all currencies" anywhere in the server, by choice — a true
   converted rollup is listed as a roadmap item instead of being faked.
2. **`export_expenses_csv`** — added the missing `currency` column to both
   the header and each row.
3. **`Amount` field description** — reworded to explicitly point the model at
   the `currency` parameter ("always pass the currency via that parameter —
   never embed it in the description text instead"), to reduce the chance of
   a repeat of the USD-in-description finding above.

## Known gaps (honest, not hidden)

- No automated test suite yet (`pytest` + a disposable test DB is the
  natural next step — see README Roadmap).
- CSV quoting for fields containing commas was exercised but not
  byte-for-byte confirmed in any round — worth a dedicated check before
  relying on this for anything that gets opened outside a spreadsheet
  program (which auto-handles quoting and would hide a real bug).
- Resources/prompts are implemented but effectively unverified through the
  Desktop client for the reason above; verify via MCP Inspector before
  relying on them in a demo.
- All manual testing so far has been single-user, single-session — no
  concurrency/load testing has been done.
- `add_expense` has no duplicate-request protection — sending (or the model
  issuing) the same call twice creates two identical rows with no warning.
- Currency handling is a deliberate per-currency partition, not a true
  multi-currency rollup — there is no single "total across all currencies"
  view anywhere in the server. Correct as far as it goes, but a real gap if
  the project ever needs one number that blends currencies.
- Recurring expense templates have no `currency` field — every generated
  row comes out in the default `INR` regardless of what currency the
  underlying subscription is actually billed in.