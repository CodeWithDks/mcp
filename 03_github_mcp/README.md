# GitHub MCP Server

An MCP server that gives Claude read and write access to GitHub —
repositories, files, commits, branches, pull requests, issues, code
review comments, and GitHub Actions — through the GitHub REST and Git
Data APIs.

## Why this exists

Most GitHub MCP examples stop at "list my repos." This one is organized
the way a real DevOps tool should be: **read tools, update tools, and
create tools live in separate files**, specifically so a bug in a read
operation can never accidentally become a write. Every write-capable tool
is explicitly annotated `readOnlyHint: false` as a visible safety marker.
It also goes further than most examples by implementing real `git push`
semantics — atomic multi-file commits via the low-level Git Data API,
not just single-file edits through the simpler Contents API.

## Project structure

```
03_github_mcp/
├── server.py           Entry point — imports every module below, runs the server
├── mcp_instance.py      Shared FastMCP + GitHubClient instances (the glue)
├── github_client.py     All GitHub REST/Git Data API calls (auth, requests, error surface)
├── helpers.py            Error handling, pagination envelope, response simplifiers
├── schemas.py             Pydantic input models + enums, shared across tool files
├── read_tools.py         Read-only tools (no confirmation needed) — 19 tools
├── update_tools.py     Tools that modify existing resources — 4 tools
├── create_tools.py     Tools that create new resources — 7 tools
├── resources.py          MCP resources (devops://github/...) — 3
└── prompts.py             MCP prompts (multi-tool workflow templates) — 5
```

## What it can do — 30 tools, 3 resources, 5 prompts

**Read (19 tools, `read_tools.py`)** — safe, no confirmation needed

| Category | Tools |
|---|---|
| Account | `get_github_user`, `get_rate_limit` |
| Repositories | `list_repositories`, `search_repositories`, `get_repository`, `list_branches`, `get_branch_protection`, `get_file_content`, `get_repository_tree` |
| Commits | `get_commits`, `compare_commits` |
| Issues | `get_open_issues` |
| Pull Requests | `get_open_pull_requests`, `get_pull_request_files`, `get_pull_request_diff` |
| GitHub Actions | `get_github_workflows`, `get_workflow_runs`, `get_workflow_run_summary`, `get_workflow_run_logs` |

`get_repository_tree` lists every file/directory in a repo, recursively,
at a given ref — the tool to call first when understanding or
reorganizing a whole codebase, before reading individual files.

**Create (7 tools, `create_tools.py`)**

| Tool | What it does |
|---|---|
| `create_issue` | title, body, labels, assignees |
| `create_branch` | branch off an existing base branch (defaults to the repo's default) |
| `create_pull_request` | open a PR from a head branch into a base branch |
| `create_file` | create a new file as a single commit |
| `push_files` | push one or more files as **one atomic commit** — real `git push` semantics via the Git Data API (blobs → tree → commit → ref update), not one commit per file |
| `create_review_comment` | comment on a specific line of a specific file within a PR's diff |
| `create_commit_comment` | comment on a commit, optionally anchored to a file/line |

**Update (4 tools, `update_tools.py`)**

- `update_issue_state` (close/reopen)
- `add_issue_comment`
- `request_pull_request_reviewers`
- `trigger_workflow`

**Resources (3, `resources.py`)**
`devops://github/repositories`, `devops://github/{owner}/{repo}/commits`,
`devops://github/{owner}/{repo}/workflows`

**Prompts (5, `prompts.py`)** — multi-tool workflow templates
- `review_pull_request` — PR details + diff + CI status → structured verdict
- `triage_issue` — read, judge priority, draft a first response for approval
- `write_release_notes` — commit range → categorized Markdown notes
- `debug_failed_workflow` — job summary + logs + recent commits → root cause
- `organize_and_document_code` — read a repo's structure, propose a
  reorganization + documentation plan, **wait for explicit approval**,
  then apply changes on a branch and open a PR — never pushes straight
  to the base branch, and never merges automatically

## Setup

### 1. GitHub token

Create a [GitHub Personal Access Token](https://github.com/settings/tokens)
with `repo` and `workflow` scopes.

Create a `.env` file in this folder:

```
GITHUB_TOKEN=your_token_here
```

### 2. Install & run

```bash
uv sync
uv run server.py
```

### 3. Connect it to Claude Desktop

```json
{
  "mcpServers": {
    "github-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/03_github_mcp",
        "run",
        "server.py"
      ]
    }
  }
}
```

## Under the hood: how `push_files` actually works

Most "write a file to GitHub" examples use the Contents API — fine for
one file, but calling it repeatedly for a multi-file change creates one
commit per file, not one atomic commit. `push_files` instead uses the
lower-level Git Data API, the same primitives `git push` itself is built
on:

1. Read the target branch's current tip commit
2. Create a blob for each file's content (done **in parallel** via
   `ThreadPoolExecutor` — blob creation per file is independent work, and
   doing this serially was the main source of slow/timed-out pushes for
   multi-file commits)
3. Create a new tree on top of the current tree, pointing at the new blobs
4. Create one commit referencing that tree
5. Fast-forward the branch ref to the new commit

The `github_client.py` HTTP layer was also hardened alongside this: a
persistent `httpx.Client` reuses TLS/TCP connections instead of
reconnecting per call, timeouts are split (connect/read/write/pool)
so a dead connection fails fast instead of sitting on one generic budget,
and every request is logged with timing to stderr — visible in Claude
Desktop's MCP log files when something is slow or failing.

## ⚠️ Safety note on write tools

Every tool in `update_tools.py` and `create_tools.py` executes a real
change against GitHub — closing issues, commenting, requesting reviewers,
triggering workflows, creating branches/PRs/files, pushing commits. Each
is annotated `readOnlyHint: false`, but **that annotation alone does not
block execution** — it's metadata, not a gate. If this server is ever
exposed to an agent running without a human reviewing each action, add an
explicit confirmation step at the client/agent level before these tools
run. The `organize_and_document_code` prompt already builds this in at
the workflow level (plan → wait for approval → branch → PR, never a
direct push to the base branch or an automatic merge) — the same
discipline should extend to any other multi-step write workflow built on
top of this server.

## Roadmap

- [ ] `update_file`, `delete_file` — schemas (`UpdateFileInput`,
      `DeleteFileInput`) already exist in `schemas.py`; tool
      implementations in `update_tools.py` are next
- [ ] `update_repository` — rename, change description/topics/default
      branch/visibility
- [ ] `merge_pull_request` — merge/squash/rebase, gated behind explicit
      confirmation
- [ ] `update_branch_protection` — write counterpart to
      `get_branch_protection`
- [ ] `cancel_workflow_run` / `rerun_workflow_run`
- [ ] `delete_branch` — cleanup after merge
- [ ] Security tools: `get_dependabot_alerts`, `get_code_scanning_alerts`
- [ ] Org-level tools: `list_organization_members`,
      `get_organization_repositories`
- [ ] `response_format` (markdown | json) option on read-heavy tools
- [ ] GitHub App / OAuth auth as an alternative to a single static PAT
- [ ] A structured eval suite to regression-test the server as it grows

See [`GITHUB_MCP_FEATURES.md`](./GITHUB_MCP_FEATURES.md) for the detailed
build log this README is based on.