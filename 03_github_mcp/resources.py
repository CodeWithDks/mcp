"""
MCP resources — passive, URI-addressable read data. Separate from tools:
resources are for clients that want to browse/attach data without a full
tool call with arguments.
"""

from helpers import DEFAULT_LIST_LIMIT, simplify_commit, simplify_repository
from mcp_instance import github, mcp


@mcp.resource(
    "devops://github/repositories",
    mime_type="application/json",
)
def repositories_resource() -> list[dict]:
    """Read-only resource containing accessible GitHub repositories."""
    repositories = github.list_repositories(DEFAULT_LIST_LIMIT)
    return [simplify_repository(repo) for repo in repositories]


@mcp.resource(
    "devops://github/{owner}/{repo}/commits",
    mime_type="application/json",
)
def commits_resource(owner: str, repo: str) -> list[dict]:
    """Read-only resource containing recent repository commits."""
    commits = github.get_commits(owner, repo, DEFAULT_LIST_LIMIT)
    return [simplify_commit(commit) for commit in commits]


@mcp.resource(
    "devops://github/{owner}/{repo}/workflows",
    mime_type="application/json",
)
def workflows_resource(owner: str, repo: str) -> list[dict]:
    """Read-only resource containing GitHub Actions workflows."""
    result = github.get_workflows(owner, repo)
    return [
        {
            "id": workflow["id"],
            "name": workflow["name"],
            "state": workflow["state"],
            "path": workflow["path"],
            "url": workflow["html_url"],
        }
        for workflow in result["workflows"]
    ]