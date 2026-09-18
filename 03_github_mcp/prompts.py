"""
MCP prompts — reusable workflow templates that chain multiple tools for tasks
users repeat often. Prompts don't call the GitHub API themselves; they return
instructions guiding the agent through the right tool sequence.
"""

from mcp_instance import mcp


@mcp.prompt(name="review_pull_request")
def review_pull_request(owner: str, repo: str, pr_number: int) -> str:
    """Guide a full review of a pull request: what changed, CI status, and a
    structured verdict."""
    return (
        f"Review pull request #{pr_number} in {owner}/{repo}. Steps:\n"
        f"1. Call get_open_pull_requests or fetch PR #{pr_number} directly to see the "
        f"title, description, base/head branches, and mergeable status.\n"
        f"2. Call get_pull_request_files to see which files changed and how much, then "
        f"get_pull_request_diff if you need to read the actual code changes.\n"
        f"3. Call get_workflow_runs filtered to the PR's head branch to check CI status; "
        f"if a run failed, call get_workflow_run_summary and get_workflow_run_logs on it "
        f"to see exactly what failed.\n"
        f"4. Summarize: what the PR does, whether CI is green, any risk areas based on "
        f"the files touched, and a clear recommend/request-changes verdict.\n"
        f"Do not merge or approve anything — only report findings unless the user "
        f"explicitly asks you to request reviewers or comment."
    )


@mcp.prompt(name="triage_issue")
def triage_issue(owner: str, repo: str, issue_number: int) -> str:
    """Guide triage of a single issue: read it, judge priority/labels, and
    draft (not send) a first response."""
    return (
        f"Triage issue #{issue_number} in {owner}/{repo}. Steps:\n"
        f"1. Fetch the issue (via get_open_issues, filtering, or a direct lookup) to "
        f"read its title, body, existing labels, and age.\n"
        f"2. Judge whether it's a bug, feature request, question, or duplicate, and "
        f"whether it looks urgent (crashes, data loss, security) vs. minor.\n"
        f"3. Suggest labels and, if relevant, an assignee — but only apply them if "
        f"the user confirms, since create/update calls are write operations.\n"
        f"4. Draft a first-response comment (don't post it yet) that either asks for "
        f"missing repro details or acknowledges the report.\n"
        f"Present your triage summary and draft comment for the user to approve "
        f"before calling add_issue_comment or update_issue_state."
    )


@mcp.prompt(name="write_release_notes")
def write_release_notes(owner: str, repo: str, base: str, head: str) -> str:
    """Guide drafting release notes from the commit range between two refs
    (e.g. last release tag vs. main)."""
    return (
        f"Draft release notes for {owner}/{repo} covering changes from '{base}' to '{head}'. "
        f"Steps:\n"
        f"1. Call compare_commits with base='{base}' and head='{head}' to get the commit "
        f"count and overall diff stats.\n"
        f"2. Call get_commits (with branch='{head}') and cross-reference against the "
        f"compare result to pull the individual commit messages in range.\n"
        f"3. Group commits into categories (Features, Fixes, Chores/Docs, Breaking "
        f"Changes) based on message content and conventional-commit prefixes if present.\n"
        f"4. Write the notes in Markdown with a heading per category and one bullet per "
        f"commit, using the commit message (cleaned up) and linking the short SHA.\n"
        f"Skip merge commits and any commit that only touches CI config unless the user "
        f"wants full verbosity."
    )


@mcp.prompt(name="debug_failed_workflow")
def debug_failed_workflow(owner: str, repo: str, run_id: int) -> str:
    """Guide root-causing a failed GitHub Actions run."""
    return (
        f"Debug why workflow run {run_id} in {owner}/{repo} failed. Steps:\n"
        f"1. Call get_workflow_run_summary with run_id={run_id} to see per-job status "
        f"and identify which job(s) failed and roughly when.\n"
        f"2. Call get_workflow_run_logs with the same run_id to read the actual error "
        f"output from the failing job.\n"
        f"3. Call get_commits (or compare_commits against the previous known-good ref, "
        f"if the user provides one) to see what changed on the branch around that time.\n"
        f"4. If the failure looks related to a specific file, use get_file_content to "
        f"inspect the relevant workflow YAML or source file at the failing commit's ref.\n"
        f"5. Summarize the likely root cause and suggest a fix. If the user confirms, "
        f"you can call trigger_workflow to re-run after a fix is pushed — do not "
        f"trigger it speculatively without confirmation."
    )


@mcp.prompt(name="organize_and_document_code")
def organize_and_document_code(owner: str, repo: str, path_prefix: str = "") -> str:
    """Guide reading an existing repo's code, reorganizing it into a cleaner
    structure, and adding useful comments/docstrings — delivered as a PR,
    never pushed directly to the base branch."""
    scope_note = f" (scoped to paths starting with '{path_prefix}')" if path_prefix else ""
    return (
        f"Read, reorganize, and document the code in {owner}/{repo}{scope_note}. "
        f"This is a structural change touching many files, so it must go through a "
        f"branch and a pull request — never push straight to the base branch. Steps:\n"
        f"\n"
        f"1. DISCOVER: Call get_repository_tree to see the full file structure"
        f"{' filtered by path_prefix' if path_prefix else ''}. Identify the language(s), "
        f"existing folder conventions, and obvious problems (files in the wrong place, "
        f"inconsistent naming, dead code, missing docs).\n"
        f"2. READ: Use get_file_content to read the key files — entry points, config, "
        f"README, and anything in scope. Don't try to read every file in a large repo "
        f"at once; read what you need to understand the structure and dependencies "
        f"between files before proposing changes.\n"
        f"3. PLAN: Before changing anything, present the user with a concrete plan: "
        f"which files move where, what naming/structure conventions you'll apply, and "
        f"what kind of comments/docstrings you'll add (module-level purpose, function-level "
        f"'why' not just 'what', not exhaustive line noise). Wait for approval before "
        f"proceeding — this step is not optional for a multi-file change.\n"
        f"4. PRESERVE BEHAVIOR: Reorganizing and commenting should not change what the code "
        f"does. If you notice an actual bug or think a real behavior change is warranted, "
        f"flag it separately and get explicit confirmation — don't fold it into the "
        f"'organize' change.\n"
        f"5. BRANCH: Call create_branch to make a branch off the default branch "
        f"(e.g. 'refactor/organize-code'). Do this before making any file changes.\n"
        f"6. APPLY CHANGES on that branch:\n"
        f"   - For files that just need better comments/formatting at the same path, use "
        f"update_file (or push_files if changing several together).\n"
        f"   - For moving/renaming a file, there is no rename primitive — create the file "
        f"at its new path with create_file, then remove the old one with delete_file, "
        f"in the same push_files call or paired commits.\n"
        f"   - Group related changes into logical commits (e.g. one commit per module) "
        f"rather than one giant commit, using push_files for each group with a clear "
        f"commit message.\n"
        f"7. OPEN A PR: Call create_pull_request from your branch into the base branch, "
        f"with a description summarizing what was reorganized and why. Do not merge it — "
        f"leave that for the user to review.\n"
        f"\n"
        f"If get_repository_tree reports github_truncated=true, the repo is too large to "
        f"see in one call — narrow scope with path_prefix and repeat this process per area."
    )