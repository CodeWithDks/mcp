"""
Tools that update existing GitHub resources (issues, pull requests, workflow
runs). Nothing here creates a brand-new top-level resource like a repo or
issue — see create_tools.py for that.

ROADMAP (not yet implemented):
  - update_repository        (rename, change description/topics/visibility)
  - merge_pull_request        (merge/squash/rebase, with confirmation gate)
  - cancel_workflow_run
  - rerun_workflow_run
  - update_branch_protection
"""

from helpers import handle_api_error, simplify_issue
from mcp_instance import github, mcp
from schemas import AddIssueCommentInput, RequestReviewersInput, TriggerWorkflowInput, UpdateIssueStateInput

_WRITE_ANNOTATIONS = {
    "readOnlyHint": False,
    "openWorldHint": True,
}


# ============================================================
# ISSUES
# ============================================================

@mcp.tool(
    name="update_issue_state",
    annotations={**_WRITE_ANNOTATIONS, "title": "Close or Reopen an Issue", "destructiveHint": False, "idempotentHint": True},
)
def update_issue_state(params: UpdateIssueStateInput) -> dict:
    """Close or reopen an existing issue.

    Args:
        params (UpdateIssueStateInput): owner, repo, issue_number, state ('open' or 'closed').

    Returns:
        dict: the updated issue (number, title, state, url).
    """
    try:
        new_state = params.validated_state()
    except ValueError as e:
        return {"error": f"Error: {e}"}

    try:
        issue = github.update_issue(params.owner, params.repo, params.issue_number, state=new_state)
    except Exception as e:
        return {"error": handle_api_error(e, "update_issue_state")}

    return simplify_issue(issue)


@mcp.tool(
    name="add_issue_comment",
    annotations={**_WRITE_ANNOTATIONS, "title": "Comment on an Issue or Pull Request", "destructiveHint": False, "idempotentHint": False},
)
def add_issue_comment(params: AddIssueCommentInput) -> dict:
    """Add a comment to an issue or pull request (GitHub treats PR comments the
    same as issue comments).

    Args:
        params (AddIssueCommentInput): owner, repo, issue_number, body.

    Returns:
        dict: id, body, author, created_at, url of the new comment.
    """
    try:
        comment = github.create_issue_comment(params.owner, params.repo, params.issue_number, params.body)
    except Exception as e:
        return {"error": handle_api_error(e, "add_issue_comment")}

    return {
        "id": comment["id"],
        "body": comment["body"],
        "author": comment["user"]["login"],
        "created_at": comment["created_at"],
        "url": comment["html_url"],
    }


# ============================================================
# PULL REQUESTS
# ============================================================

@mcp.tool(
    name="request_pull_request_reviewers",
    annotations={**_WRITE_ANNOTATIONS, "title": "Request Reviewers on a Pull Request", "destructiveHint": False, "idempotentHint": False},
)
def request_pull_request_reviewers(params: RequestReviewersInput) -> dict:
    """Request one or more GitHub users to review a pull request.

    Args:
        params (RequestReviewersInput): owner, repo, pr_number, reviewers (usernames).

    Returns:
        dict: pr_number, requested_reviewers, url.
    """
    try:
        result = github.request_reviewers(params.owner, params.repo, params.pr_number, params.reviewers)
    except Exception as e:
        return {"error": handle_api_error(e, "request_pull_request_reviewers")}

    return {
        "pr_number": params.pr_number,
        "requested_reviewers": [r["login"] for r in result.get("requested_reviewers", [])],
        "url": result.get("html_url") or result.get("url"),
    }


# ============================================================
# GITHUB ACTIONS
# ============================================================

@mcp.tool(
    name="trigger_workflow",
    annotations={**_WRITE_ANNOTATIONS, "title": "Trigger a GitHub Actions Workflow", "destructiveHint": False, "idempotentHint": False},
)
def trigger_workflow(params: TriggerWorkflowInput) -> dict:
    """Manually trigger a GitHub Actions workflow run (workflow_dispatch event).
    The target workflow's YAML must have `on: workflow_dispatch` configured.

    Args:
        params (TriggerWorkflowInput): owner, repo, workflow_id (filename or numeric ID), ref, inputs.

    Returns:
        dict: confirmation with workflow_id, ref, and a note to check get_workflow_runs
              for the resulting run (the dispatch API does not return a run ID directly).
    """
    try:
        github.trigger_workflow_dispatch(
            params.owner, params.repo, params.workflow_id, params.ref, inputs=params.inputs
        )
    except Exception as e:
        return {"error": handle_api_error(e, "trigger_workflow")}

    return {
        "status": "dispatched",
        "workflow_id": params.workflow_id,
        "ref": params.ref,
        "note": "GitHub does not return a run ID on dispatch. Call get_workflow_runs "
        "shortly after to find the new run.",
    }