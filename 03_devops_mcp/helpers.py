"""
Shared utilities used across read_tools.py, update_tools.py, and
create_tools.py: error formatting, pagination envelopes, and response
simplification. Centralized here so no tool module duplicates this logic.
"""

import logging
from typing import List, Optional

import httpx

logger = logging.getLogger("github_mcp")

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100


# ============================================================
# ERROR HANDLING
# ============================================================

def handle_api_error(e: Exception, context: str = "") -> str:
    """Turn a raw exception into an actionable, agent-readable error string."""
    prefix = f"Error{f' ({context})' if context else ''}: "

    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 404:
            return (
                prefix
                + "Resource not found. Double-check the owner/repo name, "
                "issue/PR number, branch, or file path."
            )
        if status == 403:
            return (
                prefix
                + "Permission denied or rate-limited. Check that your GitHub "
                "token has the required scopes (e.g. 'repo', 'workflow'), "
                "or call get_rate_limit to check quota."
            )
        if status == 401:
            return prefix + "Authentication failed. The GitHub token is missing or invalid."
        if status == 409:
            return prefix + "Conflict — the resource may have changed since you last read it."
        if status == 422:
            return prefix + f"Validation failed: {e.response.text[:300]}"
        if status == 429:
            return prefix + "Rate limit exceeded. Wait before retrying, or check get_rate_limit."
        return prefix + f"GitHub API returned status {status}: {e.response.text[:300]}"

    if isinstance(e, httpx.TimeoutException):
        return prefix + "Request timed out. Please retry."

    if isinstance(e, httpx.RequestError):
        return prefix + f"Network error contacting GitHub: {e}"

    logger.exception("Unexpected error in github_mcp")
    return prefix + f"Unexpected error ({type(e).__name__}): {e}"


# ============================================================
# PAGINATION
# ============================================================

def paginated_response(items: List[dict], limit: int, offset: int, total: Optional[int] = None) -> dict:
    """Build a consistent pagination envelope for list-returning tools."""
    return {
        "count": len(items),
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": (total is not None and offset + len(items) < total),
        "items": items,
    }


# ============================================================
# RESPONSE SIMPLIFICATION
# ============================================================

def simplify_repository(repo: dict) -> dict:
    return {
        "name": repo["name"],
        "full_name": repo["full_name"],
        "description": repo["description"],
        "private": repo["private"],
        "default_branch": repo["default_branch"],
        "language": repo["language"],
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "open_issues": repo["open_issues_count"],
        "url": repo["html_url"],
    }


def simplify_commit(commit: dict) -> dict:
    return {
        "sha": commit["sha"],
        "message": commit["commit"]["message"],
        "author": commit["commit"]["author"]["name"],
        "date": commit["commit"]["author"]["date"],
        "url": commit["html_url"],
    }


def simplify_issue(issue: dict) -> dict:
    return {
        "number": issue["number"],
        "title": issue["title"],
        "state": issue["state"],
        "author": issue["user"]["login"],
        "labels": [label["name"] for label in issue.get("labels", [])],
        "created_at": issue["created_at"],
        "updated_at": issue["updated_at"],
        "url": issue["html_url"],
    }


def simplify_pull_request(pr: dict) -> dict:
    return {
        "number": pr["number"],
        "title": pr["title"],
        "state": pr.get("state"),
        "author": pr["user"]["login"],
        "base": pr.get("base", {}).get("ref"),
        "head": pr.get("head", {}).get("ref"),
        "mergeable": pr.get("mergeable"),
        "draft": pr.get("draft"),
        "created_at": pr["created_at"],
        "updated_at": pr["updated_at"],
        "url": pr["html_url"],
    }