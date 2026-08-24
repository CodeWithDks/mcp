"""
Tools that create brand-new GitHub resources.

ROADMAP (not yet implemented — next up per our discussion):
  - create_repository        (name, description, private/public, auto-init, gitignore template)
  - create_pull_request       (head -> base, title, body, draft flag)
  - create_branch              (from a given ref)
"""

from helpers import handle_api_error, simplify_issue
from mcp_instance import github, mcp
from schemas import CreateIssueInput

_WRITE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}


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

    return simplify_issue(issue)