"""
Read-only GitHub tools: account info, repositories, branches, files, commits,
issues, pull requests, and GitHub Actions. Nothing in this file writes to
GitHub — every tool here is safe to call without confirmation.
"""

from helpers import handle_api_error, paginated_response, simplify_commit, simplify_issue, simplify_pull_request, simplify_repository, DEFAULT_LIST_LIMIT
from mcp_instance import github, mcp
from schemas import (
    CompareCommitsInput,
    GetBranchProtectionInput,
    GetCommitsInput,
    GetFileContentInput,
    GetIssuesInput,
    GetPullRequestDiffInput,
    GetPullRequestFilesInput,
    GetPullRequestsInput,
    GetRepositoryTreeInput,
    GetWorkflowRunLogsInput,
    GetWorkflowRunLogsSummaryInput,
    GetWorkflowRunsInput,
    ListBranchesInput,
    ListRepositoriesInput,
    RepoRef,
    SearchRepositoriesInput,
)

_READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


# ============================================================
# ACCOUNT
# ============================================================

@mcp.tool(
    name="get_github_user",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Authenticated GitHub User"},
)
def get_github_user() -> dict:
    """Get information about the authenticated GitHub user (the token owner).

    Returns:
        dict: login, name, email, public_repositories, followers, following, profile_url.
    """
    try:
        user = github.get_authenticated_user()
    except Exception as e:
        return {"error": handle_api_error(e, "get_github_user")}

    return {
        "login": user["login"],
        "name": user["name"],
        "email": user["email"],
        "public_repositories": user["public_repos"],
        "followers": user["followers"],
        "following": user["following"],
        "profile_url": user["html_url"],
    }


@mcp.tool(
    name="get_rate_limit",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get GitHub API Rate Limit Status"},
)
def get_rate_limit() -> dict:
    """Check current GitHub API rate limit usage. Call this before a large batch
    of requests, or when a tool call fails with a 403/429 error.

    Returns:
        dict: remaining, limit, used, reset_at (ISO timestamp) for the 'core' API category.
    """
    try:
        data = github.get_rate_limit()
    except Exception as e:
        return {"error": handle_api_error(e, "get_rate_limit")}

    core = data["resources"]["core"]
    return {
        "remaining": core["remaining"],
        "limit": core["limit"],
        "used": core["used"],
        "reset_at": core["reset"],
    }


# ============================================================
# REPOSITORIES
# ============================================================

@mcp.tool(
    name="list_repositories",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "List Repositories"},
)
def list_repositories(params: ListRepositoriesInput) -> dict:
    """List repositories accessible to the authenticated GitHub user, paginated.

    Args:
        params (ListRepositoriesInput): limit, offset.

    Returns:
        dict: paginated envelope with 'items' (list of simplified repositories).
    """
    try:
        repositories = github.list_repositories(params.offset + params.limit)
    except Exception as e:
        return {"error": handle_api_error(e, "list_repositories")}

    page = repositories[params.offset : params.offset + params.limit]
    return paginated_response([simplify_repository(r) for r in page], params.limit, params.offset)


@mcp.tool(
    name="search_repositories",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Search GitHub Repositories"},
)
def search_repositories(params: SearchRepositoriesInput) -> dict:
    """Search for repositories on GitHub using GitHub's search syntax
    (e.g. 'org:anthropics language:python', 'topic:mcp stars:>50').

    Args:
        params (SearchRepositoriesInput): query, limit.

    Returns:
        dict: paginated envelope with 'items' (list of simplified repositories) and 'total'.
    """
    try:
        result = github.search_repositories(params.query, params.limit)
    except Exception as e:
        return {"error": handle_api_error(e, "search_repositories")}

    items = [simplify_repository(r) for r in result["items"]]
    return paginated_response(items, params.limit, 0, total=result.get("total_count"))


@mcp.tool(
    name="get_repository",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Repository Details"},
)
def get_repository(params: RepoRef) -> dict:
    """Get detailed information about a single GitHub repository.

    Args:
        params (RepoRef): owner, repo.

    Returns:
        dict: simplified repository details.
    """
    try:
        repository = github.get_repository(params.owner, params.repo)
    except Exception as e:
        return {"error": handle_api_error(e, f"get_repository {params.owner}/{params.repo}")}

    return simplify_repository(repository)


@mcp.tool(
    name="list_branches",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "List Repository Branches"},
)
def list_branches(params: ListBranchesInput) -> dict:
    """List branches in a repository.

    Args:
        params (ListBranchesInput): owner, repo, limit.

    Returns:
        dict: paginated envelope with 'items' (list of {name, commit_sha, protected}).
    """
    try:
        branches = github.list_branches(params.owner, params.repo, params.limit)
    except Exception as e:
        return {"error": handle_api_error(e, "list_branches")}

    items = [
        {
            "name": b["name"],
            "commit_sha": b["commit"]["sha"],
            "protected": b.get("protected", False),
        }
        for b in branches
    ]
    return paginated_response(items, params.limit, 0)


@mcp.tool(
    name="get_branch_protection",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Branch Protection Rules"},
)
def get_branch_protection(params: GetBranchProtectionInput) -> dict:
    """Check whether a branch is protected, and if so, under what rules
    (required reviews, required status checks, admin enforcement, etc).
    Call this before attempting any write/merge operation against the branch —
    it explains in advance why GitHub might reject a push or merge.

    Args:
        params (GetBranchProtectionInput): owner, repo, branch.

    Returns:
        dict: protected (bool), and if true: required_approving_review_count,
              required_status_checks (list of check names), enforce_admins,
              allow_force_pushes, allow_deletions.
    """
    try:
        data = github.get_branch_protection(params.owner, params.repo, params.branch)
    except Exception as e:
        return {"error": handle_api_error(e, "get_branch_protection")}

    if not data.get("protected"):
        return {"protected": False}

    reviews = data.get("required_pull_request_reviews", {}) or {}
    status_checks = data.get("required_status_checks", {}) or {}

    return {
        "protected": True,
        "required_approving_review_count": reviews.get("required_approving_review_count"),
        "required_status_checks": status_checks.get("contexts", []),
        "enforce_admins": (data.get("enforce_admins") or {}).get("enabled", False),
        "allow_force_pushes": (data.get("allow_force_pushes") or {}).get("enabled", False),
        "allow_deletions": (data.get("allow_deletions") or {}).get("enabled", False),
    }


@mcp.tool(
    name="get_repository_tree",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Full Repository File Tree"},
)
def get_repository_tree(params: GetRepositoryTreeInput) -> dict:
    """List every file and directory in a repository, recursively, at a given
    ref. Use this FIRST when you need to understand or reorganize a repo's
    code — it shows the whole structure so you know which files exist before
    reading any of them individually with get_file_content.

    Args:
        params (GetRepositoryTreeInput): owner, repo, ref, path_prefix, limit, offset.

    Returns:
        dict: paginated envelope with 'items' (path, type: 'file'|'directory', size),
              plus 'github_truncated' (true if GitHub itself capped an extremely
              large tree — in that case, narrow with path_prefix and call again).
    """
    try:
        result = github.get_repository_tree(params.owner, params.repo, ref=params.ref)
    except Exception as e:
        return {"error": handle_api_error(e, "get_repository_tree")}

    entries = [
        {
            "path": e["path"],
            "type": "directory" if e["type"] == "tree" else "file",
            "size": e.get("size"),
        }
        for e in result.get("tree", [])
        if not params.path_prefix or e["path"].startswith(params.path_prefix)
    ]

    page = entries[params.offset : params.offset + params.limit]
    response = paginated_response(page, params.limit, params.offset, total=len(entries))
    response["github_truncated"] = result.get("truncated", False)
    return response


@mcp.tool(
    name="get_file_content",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get File Content From Repository"},
)
def get_file_content(params: GetFileContentInput) -> dict:
    """Read a file's content from a repository at a given ref (branch/tag/SHA).
    Only text files under ~1MB are returned in full; larger or binary files
    return metadata only.

    Args:
        params (GetFileContentInput): owner, repo, path, ref.

    Returns:
        dict: path, sha, size, encoding, content (decoded text if available), url.
    """
    try:
        file_data = github.get_file_content(params.owner, params.repo, params.path, params.ref)
    except Exception as e:
        return {"error": handle_api_error(e, f"get_file_content {params.path}")}

    return {
        "path": file_data["path"],
        "sha": file_data["sha"],
        "size": file_data["size"],
        "content": file_data.get("decoded_content"),
        "truncated": file_data.get("size", 0) > 1_000_000,
        "url": file_data["html_url"],
    }


# ============================================================
# COMMITS
# ============================================================

@mcp.tool(
    name="get_commits",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Recent Commits"},
)
def get_commits(params: GetCommitsInput) -> dict:
    """Get recent commits from a repository, optionally filtered by branch.

    Args:
        params (GetCommitsInput): owner, repo, limit, branch.

    Returns:
        dict: paginated envelope with 'items' (list of simplified commits).
    """
    try:
        commits = github.get_commits(params.owner, params.repo, params.limit, branch=params.branch)
    except Exception as e:
        return {"error": handle_api_error(e, "get_commits")}

    return paginated_response([simplify_commit(c) for c in commits], params.limit, 0)


@mcp.tool(
    name="compare_commits",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Compare Two Commits or Branches"},
)
def compare_commits(params: CompareCommitsInput) -> dict:
    """Compare two commits, branches, or tags — useful for previewing what a
    merge or release would include.

    Args:
        params (CompareCommitsInput): owner, repo, base, head.

    Returns:
        dict: status (ahead/behind/identical/diverged), ahead_by, behind_by,
              total_commits, files_changed, url.
    """
    try:
        comparison = github.compare_commits(params.owner, params.repo, params.base, params.head)
    except Exception as e:
        return {"error": handle_api_error(e, "compare_commits")}

    return {
        "status": comparison["status"],
        "ahead_by": comparison["ahead_by"],
        "behind_by": comparison["behind_by"],
        "total_commits": comparison["total_commits"],
        "files_changed": len(comparison.get("files", [])),
        "url": comparison["html_url"],
    }


# ============================================================
# ISSUES
# ============================================================

@mcp.tool(
    name="get_open_issues",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Repository Issues"},
)
def get_open_issues(params: GetIssuesInput) -> dict:
    """Get issues from a repository, filtered by state and optionally by labels.
    Pull requests are excluded (use get_open_pull_requests for those).

    Args:
        params (GetIssuesInput): owner, repo, limit, state, labels.

    Returns:
        dict: paginated envelope with 'items' (list of simplified issues).
    """
    try:
        issues = github.get_issues(
            params.owner, params.repo, params.limit, state=params.state.value, labels=params.labels
        )
    except Exception as e:
        return {"error": handle_api_error(e, "get_open_issues")}

    filtered = [i for i in issues if "pull_request" not in i]
    return paginated_response([simplify_issue(i) for i in filtered], params.limit, 0)


# ============================================================
# PULL REQUESTS
# ============================================================

@mcp.tool(
    name="get_open_pull_requests",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Pull Requests"},
)
def get_open_pull_requests(params: GetPullRequestsInput) -> dict:
    """Get pull requests from a repository, filtered by state.

    Args:
        params (GetPullRequestsInput): owner, repo, limit, state.

    Returns:
        dict: paginated envelope with 'items' (list of simplified pull requests).
    """
    try:
        pull_requests = github.get_pull_requests(
            params.owner, params.repo, params.limit, state=params.state.value
        )
    except Exception as e:
        return {"error": handle_api_error(e, "get_open_pull_requests")}

    return paginated_response([simplify_pull_request(pr) for pr in pull_requests], params.limit, 0)


@mcp.tool(
    name="get_pull_request_files",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Files Changed in a Pull Request"},
)
def get_pull_request_files(params: GetPullRequestFilesInput) -> dict:
    """Get the list of files changed in a pull request, with add/delete line counts.
    Useful for scoping a code review without pulling the full diff text.

    Args:
        params (GetPullRequestFilesInput): owner, repo, pr_number, limit.

    Returns:
        dict: paginated envelope with 'items' (filename, status, additions, deletions, changes).
    """
    try:
        files = github.get_pull_request_files(params.owner, params.repo, params.pr_number, params.limit)
    except Exception as e:
        return {"error": handle_api_error(e, "get_pull_request_files")}

    items = [
        {
            "filename": f["filename"],
            "status": f["status"],
            "additions": f["additions"],
            "deletions": f["deletions"],
            "changes": f["changes"],
        }
        for f in files
    ]
    return paginated_response(items, params.limit, 0)


@mcp.tool(
    name="get_pull_request_diff",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Raw Pull Request Diff"},
)
def get_pull_request_diff(params: GetPullRequestDiffInput) -> dict:
    """Get the raw unified diff for a pull request — the actual line-by-line
    code changes, not just a file list. Use get_pull_request_files first if you
    only need to know which files changed; use this when you need to read the
    actual code changes for a review.

    Args:
        params (GetPullRequestDiffInput): owner, repo, pr_number, max_chars.

    Returns:
        dict: diff (str, possibly truncated), truncated (bool).
    """
    try:
        diff_text = github.get_pull_request_diff(params.owner, params.repo, params.pr_number)
    except Exception as e:
        return {"error": handle_api_error(e, "get_pull_request_diff")}

    truncated = len(diff_text) > params.max_chars
    return {
        "diff": diff_text[: params.max_chars],
        "truncated": truncated,
    }


# ============================================================
# GITHUB ACTIONS
# ============================================================

@mcp.tool(
    name="get_github_workflows",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "List GitHub Actions Workflows"},
)
def get_github_workflows(params: RepoRef) -> dict:
    """List GitHub Actions workflows defined in a repository.

    Args:
        params (RepoRef): owner, repo.

    Returns:
        dict: paginated envelope with 'items' (id, name, state, path, url).
    """
    try:
        result = github.get_workflows(params.owner, params.repo)
    except Exception as e:
        return {"error": handle_api_error(e, "get_github_workflows")}

    items = [
        {
            "id": w["id"],
            "name": w["name"],
            "state": w["state"],
            "path": w["path"],
            "url": w["html_url"],
        }
        for w in result["workflows"]
    ]
    return paginated_response(items, len(items), 0, total=result.get("total_count"))


@mcp.tool(
    name="get_workflow_runs",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get GitHub Actions Workflow Runs"},
)
def get_workflow_runs(params: GetWorkflowRunsInput) -> dict:
    """Get recent GitHub Actions workflow runs, optionally filtered by branch or status.
    Use this to check CI health before merging, or to find a run_id for
    get_workflow_run_summary / get_workflow_run_logs.

    Args:
        params (GetWorkflowRunsInput): owner, repo, limit, branch, status.

    Returns:
        dict: paginated envelope with 'items' (id, name, status, conclusion, branch, commit, timestamps, url).
    """
    try:
        result = github.get_workflow_runs(
            params.owner, params.repo, params.limit, branch=params.branch, status=params.status
        )
    except Exception as e:
        return {"error": handle_api_error(e, "get_workflow_runs")}

    items = [
        {
            "id": run["id"],
            "name": run["name"],
            "status": run["status"],
            "conclusion": run["conclusion"],
            "branch": run["head_branch"],
            "commit": run["head_sha"],
            "created_at": run["created_at"],
            "updated_at": run["updated_at"],
            "url": run["html_url"],
        }
        for run in result["workflow_runs"]
    ]
    return paginated_response(items, params.limit, 0, total=result.get("total_count"))


@mcp.tool(
    name="get_workflow_run_summary",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Workflow Run Job Summary"},
)
def get_workflow_run_summary(params: GetWorkflowRunLogsSummaryInput) -> dict:
    """Get a per-job status summary for a specific workflow run — which jobs
    passed/failed and how long each took, without downloading full raw logs.

    Args:
        params (GetWorkflowRunLogsSummaryInput): owner, repo, run_id.

    Returns:
        dict: run_id, jobs (name, status, conclusion, started_at, completed_at, url).
    """
    try:
        result = github.get_workflow_run_jobs(params.owner, params.repo, params.run_id)
    except Exception as e:
        return {"error": handle_api_error(e, "get_workflow_run_summary")}

    jobs = [
        {
            "name": job["name"],
            "status": job["status"],
            "conclusion": job["conclusion"],
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "url": job["html_url"],
        }
        for job in result.get("jobs", [])
    ]
    return {"run_id": params.run_id, "jobs": jobs}


@mcp.tool(
    name="get_workflow_run_logs",
    annotations={**_READ_ONLY_ANNOTATIONS, "title": "Get Raw Workflow Run Logs"},
)
def get_workflow_run_logs(params: GetWorkflowRunLogsInput) -> dict:
    """Get the raw log text for a workflow run — use this when
    get_workflow_run_summary shows a failed job and you need the actual error
    output to debug it. Logs are truncated to keep responses manageable.

    Args:
        params (GetWorkflowRunLogsInput): owner, repo, run_id.

    Returns:
        dict: text (combined log text, most recent job's logs included), truncated (bool).
    """
    try:
        result = github.get_workflow_run_logs(params.owner, params.repo, params.run_id)
    except Exception as e:
        return {"error": handle_api_error(e, "get_workflow_run_logs")}

    return result