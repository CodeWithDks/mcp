"""
Tools that create brand-new GitHub resources.

ROADMAP (not yet implemented — next up per our discussion):
  - create_repository        (name, description, private/public, auto-init, gitignore template)
  - create_pull_request       (head -> base, title, body, draft flag)
  - create_branch              (from a given ref)
"""

import base64

from helpers import handle_api_error, simplify_issue, simplify_pull_request
from mcp_instance import github, mcp
from schemas import (
    CreateBranchInput,
    CreateCommitCommentInput,
    CreateFileInput,
    CreateIssueInput,
    CreatePullRequestInput,
    CreateReviewCommentInput,
    PushFilesInput,
)

_WRITE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}


# ============================================================
# ISSUES
# ============================================================

@mcp.tool(
    name="create_issue",
    annotations={**_WRITE_ANNOTATIONS, "title": "Create GitHub Issue"},
)
def create_issue(params: CreateIssueInput) -> dict:
    """Create a new issue in a repository.

    Args:
        params (CreateIssueInput): owner, repo, title, body, labels, assignees.

    Returns:
        dict: the created issue (number, title, state, url).
    """
    try:
        issue = github.create_issue(
            params.owner,
            params.repo,
            title=params.title,
            body=params.body,
            labels=params.labels,
            assignees=params.assignees,
        )
    except Exception as e:
        return {"error": handle_api_error(e, "create_issue")}
    # pyrefly: ignore [bad-argument-type]
    return simplify_issue(issue)


# ============================================================
# BRANCHES & PULL REQUESTS
# ============================================================

@mcp.tool(
    name="create_branch",
    annotations={**_WRITE_ANNOTATIONS, "title": "Create a New Branch"},
)
def create_branch(params: CreateBranchInput) -> dict:
    """Create a new branch from an existing base branch (defaults to the
    repo's default branch). Use this before create_file/update_file/push_files
    whenever changes shouldn't land directly on the base branch — e.g. before
    a reorganization, refactor, or any multi-file change that should go
    through a pull request for review.

    Args:
        params (CreateBranchInput): owner, repo, new_branch, base_branch.

    Returns:
        dict: ref, sha (the commit the new branch points at), url.
    """
    try:
        result = github.create_branch(params.owner, params.repo, params.new_branch, base_branch=params.base_branch)
    except Exception as e:
        return {"error": handle_api_error(e, "create_branch")}

    return {
        "ref": result["ref"],
        # pyrefly: ignore [bad-string-format]
        "sha": result["object"]["sha"],
        "url": result["url"],
    }


@mcp.tool(
    name="create_pull_request",
    annotations={**_WRITE_ANNOTATIONS, "title": "Open a Pull Request"},
)
def create_pull_request(params: CreatePullRequestInput) -> dict:
    """Open a pull request from a head branch into a base branch. Use this to
    turn changes made on a branch (via create_branch + push_files) into a
    reviewable PR, rather than committing straight to the base branch.

    Args:
        params (CreatePullRequestInput): owner, repo, title, head, base, body, draft.

    Returns:
        dict: simplified pull request (number, title, state, base, head, url).
    """
    try:
        pr = github.create_pull_request(
            params.owner,
            params.repo,
            params.title,
            params.head,
            params.base,
            body=params.body,
            draft=params.draft,
        )
    except Exception as e:
        return {"error": handle_api_error(e, "create_pull_request")}

    return simplify_pull_request(pr)


# ============================================================
# FILES & CODE — "write files" / "push code"
# ============================================================

@mcp.tool(
    name="create_file",
    annotations={**_WRITE_ANNOTATIONS, "title": "Create a New File in a Repository"},
)
def create_file(params: CreateFileInput) -> dict:
    """Create a new file in a repository as a single commit. Fails with a 422
    if a file already exists at that path on the target branch — use
    update_file instead for existing files.

    Args:
        params (CreateFileInput): owner, repo, path, content, message, branch.

    Returns:
        dict: path, sha (new file blob sha), commit_sha, url.
    """
    content_b64 = base64.b64encode(params.content.encode("utf-8")).decode("ascii")

    try:
        result = github.put_file_content(
            params.owner,
            params.repo,
            params.path,
            content_b64,
            params.message,
            branch=params.branch,
        )
    except Exception as e:
        return {"error": handle_api_error(e, "create_file")}

    return {
        "path": result["content"]["path"],
        "sha": result["content"]["sha"],
        "commit_sha": result["commit"]["sha"],
        "url": result["content"]["html_url"],
    }


@mcp.tool(
    name="push_files",
    annotations={**_WRITE_ANNOTATIONS, "title": "Push Multiple Files as One Commit"},
)
def push_files(params: PushFilesInput) -> dict:
    """Push one or more files to a branch in a single commit — this is the
    'real git push' tool: it creates one atomic commit covering every file
    you pass, rather than one commit per file (which create_file/update_file
    would produce if called repeatedly). Use this whenever you're changing
    more than one file together, e.g. a feature that touches source + tests.

    Existing files at a given path are overwritten; new paths are created.

    Args:
        params (PushFilesInput): owner, repo, branch, message, files (list of {path, content}).

    Returns:
        dict: commit_sha, files_changed (count), branch, url.
    """
    try:
        commit = github.push_files(
            params.owner,
            params.repo,
            params.branch,
            params.message,
            files=[{"path": f.path, "content": f.content} for f in params.files],
        )
    except Exception as e:
        return {"error": handle_api_error(e, "push_files")}

    return {
        "commit_sha": commit["sha"],
        "files_changed": len(params.files),
        "branch": params.branch,
        "url": commit["html_url"],
    }


# ============================================================
# COMMENTS — code review & commit comments
# ============================================================

@mcp.tool(
    name="create_review_comment",
    annotations={**_WRITE_ANNOTATIONS, "title": "Comment on a Specific Line in a Pull Request Diff"},
)
def create_review_comment(params: CreateReviewCommentInput) -> dict:
    """Add a comment anchored to a specific line of a specific file within a
    pull request's diff — a code review comment, distinct from a general PR
    comment (use add_issue_comment for those). Get commit_sha from the PR's
    head sha (get_open_pull_requests) and path/line from get_pull_request_diff.

    Args:
        params (CreateReviewCommentInput): owner, repo, pr_number, body, commit_sha, path, line, side.

    Returns:
        dict: id, path, line, body, author, url.
    """
    try:
        comment = github.create_review_comment(
            params.owner,
            params.repo,
            params.pr_number,
            params.body,
            params.commit_sha,
            params.path,
            params.line,
            side=params.side,
        )
    except Exception as e:
        return {"error": handle_api_error(e, "create_review_comment")}

    return {
        "id": comment["id"],
        "path": comment["path"],
        "line": comment.get("line"),
        "body": comment["body"],
        "author": comment["user"]["login"],
        "url": comment["html_url"],
    }


@mcp.tool(
    name="create_commit_comment",
    annotations={**_WRITE_ANNOTATIONS, "title": "Comment on a Commit"},
)
def create_commit_comment(params: CreateCommitCommentInput) -> dict:
    """Add a comment to a specific commit, optionally anchored to a file and
    line within that commit (rather than to an issue or PR).

    Args:
        params (CreateCommitCommentInput): owner, repo, commit_sha, body, path, line.

    Returns:
        dict: id, body, author, url.
    """
    try:
        comment = github.create_commit_comment(
            params.owner,
            params.repo,
            params.commit_sha,
            params.body,
            path=params.path,
            line=params.line,
        )
    except Exception as e:
        return {"error": handle_api_error(e, "create_commit_comment")}

    return {
        "id": comment["id"],
        "body": comment["body"],
        "author": comment["user"]["login"],
        "url": comment["html_url"],
    }