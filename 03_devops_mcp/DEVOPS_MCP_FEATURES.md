# GitHub DevOps MCP — Feature Summary & Roadmap

**Server name:** `github_mcp`
**Entry point:** `server.py`

---

## 1. Project structure

The server is now split into focused files instead of one monolithic script:

```
devops_mcp/
├── server.py           Entry point — imports every module below, runs the server
├── mcp_instance.py      Shared FastMCP + GitHubClient instances (the glue)
├── github_client.py     All GitHub REST API calls (auth, requests, error surface)
├── helpers.py            Error handling, pagination envelope, response simplifiers
├── schemas.py             Pydantic input models + enums, shared across tool files
├── read_tools.py         Read-only tools (no confirmation needed)
├── update_tools.py       Tools that modify existing resources
├── create_tools.py       Tools that create new resources
├── resources.py          MCP resources (devops://github/...)
└── prompts.py             MCP prompts (multi-tool workflow templates)
```

Why this shape: `read_tools.py` can never accidentally write to GitHub — a bug there is a bad read, not a bad write. `update_tools.py` and `create_tools.py` are where write risk lives, kept small and separate so they're easy to audit. All three import shared logic from `helpers.py`/`schemas.py` rather than duplicating it.

---

## 2. Status: Read phase — complete

All planned read capability is implemented and verified end-to-end (imported `server.py` directly and confirmed registration).

### Tools — 18 read-only (`read_tools.py`)

**Account (2)**
- `get_github_user`
- `get_rate_limit`

**Repositories (6)**
- `list_repositories` — paginated
- `search_repositories` — GitHub search syntax
- `get_repository`
- `list_branches`
- `get_branch_protection` *(added this round)* — protection rules, required reviews/checks, before any write is attempted against a branch
- `get_file_content` — file content at any branch/tag/SHA

**Commits (2)**
- `get_commits` — filterable by branch
- `compare_commits` — ahead/behind/diverged stats between two refs

**Issues (1)**
- `get_open_issues` — filterable by state and labels

**Pull Requests (3)**
- `get_open_pull_requests` — filterable by state
- `get_pull_request_files` — changed files with add/delete counts
- `get_pull_request_diff` *(added this round)* — raw unified diff, for actually reading code changes

**GitHub Actions (4)**
- `get_github_workflows`
- `get_workflow_runs` — filterable by branch and status
- `get_workflow_run_summary` — per-job pass/fail
- `get_workflow_run_logs` *(added this round)* — actual log text from a run, truncated to stay context-friendly

### Resources — 3 (`resources.py`)
- `devops://github/repositories`
- `devops://github/{owner}/{repo}/commits`
- `devops://github/{owner}/{repo}/workflows`

### Prompts — 4 (`prompts.py`)
- `review_pull_request` — PR details + diff + CI status → structured verdict
- `triage_issue` — read, judge priority, draft a first response for approval
- `write_release_notes` — commit range → categorized Markdown notes
- `debug_failed_workflow` — job summary + logs + recent commits → root cause

---

## 3. Status: Write tools — partially built, carried over and re-verified

These already existed and were tested working in Claude Desktop before the file split; they're now organized by category.

### `update_tools.py` — 4 tools
- `update_issue_state` — close/reopen
- `add_issue_comment` — comment on an issue or PR
- `request_pull_request_reviewers`
- `trigger_workflow` — manual `workflow_dispatch`

### `create_tools.py` — 1 tool
- `create_issue` — title, body, labels, assignees

**Total tools across the server: 23**

---

## 4. Roadmap — what's next (per our discussion: repo update/create)

### `create_tools.py` — next up
- **`create_repository`** — name, description, private/public, auto-init, `.gitignore`/license template
- **`create_pull_request`** — head → base, title, body, draft flag
- **`create_branch`** — from a given ref (needed before `create_pull_request` is useful for net-new work)

### `update_tools.py` — next up
- **`update_repository`** — rename, change description/topics/default branch/visibility
- **`merge_pull_request`** — merge/squash/rebase, gated behind explicit confirmation
- **`update_branch_protection`** — now that `get_branch_protection` exists on the read side, the write counterpart
- **`cancel_workflow_run` / `rerun_workflow_run`**

### Later / lower priority
- **`delete_branch`** — cleanup after merge
- **Security:** `get_dependabot_alerts`, `get_code_scanning_alerts`
- **Org-level:** `list_organization_members`, `get_organization_repositories`
- **`response_format` (markdown | json)** option on read-heavy tools for nicer raw chat rendering
- **GitHub App / OAuth auth** as an alternative to the single static PAT, for multi-user deployments
- **10-question eval suite** (per MCP best practices) to regression-test the server as it grows

### Safety note carried forward
Every tool in `update_tools.py` and `create_tools.py` is annotated `readOnlyHint: false`. Annotations alone don't block execution — if this server is ever exposed without a human-in-the-loop step, add a confirmation gate at the client/agent level before these run unattended. This matters more, not less, as `merge_pull_request` and `create_repository` get added.

---

*Companion doc to the `devops_mcp/` project. Supersedes the previous single-file feature summary.*
