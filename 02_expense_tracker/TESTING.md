# Testing Notes

This project was tested manually through Claude Desktop, in two rounds. This
is not an automated test suite (there is no `pytest` harness in this repo
yet — see Roadmap in the README) — it's a documented, deliberate QA pass
using natural-language prompts against the live MCP server, which is a
realistic way to test a tool an LLM is meant to call.

## Round 1 — Initial QA sweep (50 scenarios)

Covered all 11 tools: CRUD operations, filtered search, aggregation
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

## Known gaps (honest, not hidden)

- No automated test suite yet (`pytest` + a disposable test DB is the
  natural next step — see README Roadmap).
- CSV quoting for fields containing commas was exercised but not
  byte-for-byte confirmed in this round.
- Resources/prompts are implemented but effectively unverified through the
  Desktop client for the reason above; verify via MCP Inspector before
  relying on them in a demo.
- All manual testing so far has been single-user, single-session — no
  concurrency/load testing has been done.
