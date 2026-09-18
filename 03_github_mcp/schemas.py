"""
Pydantic input models and enums shared across read_tools.py, update_tools.py,
and create_tools.py. Kept in one place so RepoRef etc. isn't redefined per file.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from helpers import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT


class IssueOrPRState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    ALL = "all"


# ============================================================
# COMMON
# ============================================================

class RepoRef(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    owner: str = Field(..., description="GitHub username or organization, e.g. 'octocat'.", min_length=1)
    repo: str = Field(..., description="Repository name, e.g. 'hello-world'.", min_length=1)


# ============================================================
# READ — repositories / branches / files
# ============================================================

class ListRepositoriesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(DEFAULT_LIST_LIMIT, description="Max repositories to return.", ge=1, le=MAX_LIST_LIMIT)
    offset: int = Field(0, description="Number of repositories to skip (for pagination).", ge=0)


class SearchRepositoriesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., description="GitHub search query, e.g. 'topic:mcp language:python'.", min_length=1)
    limit: int = Field(10, description="Max results to return.", ge=1, le=MAX_LIST_LIMIT)


class ListBranchesInput(RepoRef):
    limit: int = Field(30, description="Max branches to return.", ge=1, le=MAX_LIST_LIMIT)


class GetBranchProtectionInput(RepoRef):
    branch: str = Field(..., description="Branch name, e.g. 'main'.", min_length=1)


class GetFileContentInput(RepoRef):
    path: str = Field(..., description="File path within the repo, e.g. 'src/main.py'.", min_length=1)
    ref: Optional[str] = Field(None, description="Branch, tag, or commit SHA. Defaults to the default branch.")


# ============================================================
# READ — commits
# ============================================================

class GetCommitsInput(RepoRef):
    limit: int = Field(10, description="Max commits to return.", ge=1, le=MAX_LIST_LIMIT)
    branch: Optional[str] = Field(None, description="Branch, tag, or SHA to list commits from. Defaults to the repo's default branch.")


class CompareCommitsInput(RepoRef):
    base: str = Field(..., description="Base branch, tag, or commit SHA.", min_length=1)
    head: str = Field(..., description="Head branch, tag, or commit SHA to compare against base.", min_length=1)


# ============================================================
# READ — issues
# ============================================================

class GetIssuesInput(RepoRef):
    limit: int = Field(10, description="Max issues to return.", ge=1, le=MAX_LIST_LIMIT)
    state: IssueOrPRState = Field(IssueOrPRState.OPEN, description="Filter by issue state.")
    labels: Optional[List[str]] = Field(None, description="Only return issues with all of these labels.")


# ============================================================
# READ — pull requests
# ============================================================

class GetPullRequestsInput(RepoRef):
    limit: int = Field(10, description="Max pull requests to return.", ge=1, le=MAX_LIST_LIMIT)
    state: IssueOrPRState = Field(IssueOrPRState.OPEN, description="Filter by pull request state.")


class GetPullRequestFilesInput(RepoRef):
    pr_number: int = Field(..., description="Pull request number.", ge=1)
    limit: int = Field(30, description="Max changed files to return.", ge=1, le=MAX_LIST_LIMIT)


class GetPullRequestDiffInput(RepoRef):
    pr_number: int = Field(..., description="Pull request number.", ge=1)
    max_chars: int = Field(
        15_000,
        description="Truncate the diff to this many characters if longer (keeps responses context-friendly).",
        ge=500,
        le=100_000,
    )


# ============================================================
# READ — GitHub Actions
# ============================================================

class GetWorkflowRunsInput(RepoRef):
    limit: int = Field(10, description="Max workflow runs to return.", ge=1, le=MAX_LIST_LIMIT)
    branch: Optional[str] = Field(None, description="Only return runs for this branch.")
    status: Optional[str] = Field(
        None,
        description="Filter by status/conclusion, e.g. 'success', 'failure', 'in_progress', 'queued'.",
    )


class GetWorkflowRunLogsSummaryInput(RepoRef):
    run_id: int = Field(..., description="Workflow run ID (from get_workflow_runs).", ge=1)


class GetWorkflowRunLogsInput(RepoRef):
    run_id: int = Field(..., description="Workflow run ID (from get_workflow_runs).", ge=1)


class TriggerWorkflowInput(RepoRef):
    workflow_id: str = Field(..., description="Workflow file name (e.g. 'ci.yml') or numeric workflow ID.", min_length=1)
    ref: str = Field(..., description="Branch or tag to run the workflow on, e.g. 'main'.", min_length=1)
    inputs: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Workflow input parameters as key-value pairs.")


# ============================================================
# WRITE — issues (used by update_tools.py)
# ============================================================

class CreateIssueInput(RepoRef):
    title: str = Field(..., description="Issue title.", min_length=1, max_length=256)
    body: Optional[str] = Field(None, description="Issue description in Markdown.")
    labels: Optional[List[str]] = Field(default_factory=list, description="Labels to apply, e.g. ['bug', 'urgent'].", max_length=20)
    assignees: Optional[List[str]] = Field(default_factory=list, description="GitHub usernames to assign.", max_length=10)


class UpdateIssueStateInput(RepoRef):
    issue_number: int = Field(..., description="Issue number to update.", ge=1)
    state: IssueOrPRState = Field(..., description="New state: 'open' or 'closed'.")

    def validated_state(self) -> str:
        if self.state == IssueOrPRState.ALL:
            raise ValueError("state must be 'open' or 'closed' when updating an issue, not 'all'.")
        return self.state.value


class AddIssueCommentInput(RepoRef):
    issue_number: int = Field(..., description="Issue (or PR) number to comment on.", ge=1)
    body: str = Field(..., description="Comment text in Markdown.", min_length=1)


class RequestReviewersInput(RepoRef):
    pr_number: int = Field(..., description="Pull request number.", ge=1)
    reviewers: List[str] = Field(..., description="GitHub usernames to request review from.", min_length=1, max_length=15)


# ============================================================
# WRITE — files & commits (used by create_tools.py / update_tools.py)
# ============================================================

class CreateFileInput(RepoRef):
    path: str = Field(..., description="File path to create, e.g. 'src/new_module.py'.", min_length=1)
    content: str = Field(..., description="Full text content of the new file.")
    message: str = Field(..., description="Commit message for this change.", min_length=1)
    branch: Optional[str] = Field(None, description="Branch to commit to. Defaults to the repo's default branch.")


class UpdateFileInput(RepoRef):
    path: str = Field(..., description="Path of the existing file to update.", min_length=1)
    content: str = Field(..., description="New full text content to replace the file with.")
    message: str = Field(..., description="Commit message for this change.", min_length=1)
    branch: Optional[str] = Field(None, description="Branch to commit to. Defaults to the repo's default branch.")
    sha: Optional[str] = Field(
        None,
        description="Current blob sha of the file being replaced. If omitted, it will be looked up "
        "automatically via get_file_content — but supplying it avoids a race if the file "
        "may have changed since you last read it.",
    )


class DeleteFileInput(RepoRef):
    path: str = Field(..., description="Path of the file to delete.", min_length=1)
    message: str = Field(..., description="Commit message for this deletion.", min_length=1)
    sha: str = Field(..., description="Current blob sha of the file being deleted (from get_file_content).", min_length=1)
    branch: Optional[str] = Field(None, description="Branch to commit to. Defaults to the repo's default branch.")


class FileChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., description="File path, e.g. 'src/app.py'.", min_length=1)
    content: str = Field(..., description="Full text content for this file.")


class PushFilesInput(RepoRef):
    branch: str = Field(..., description="Branch to push the commit to, e.g. 'main' or a feature branch.", min_length=1)
    message: str = Field(..., description="Commit message for the push.", min_length=1)
    files: List[FileChange] = Field(
        ...,
        description="One or more files to include in this single commit. Each is created or "
        "overwritten at the given path.",
        min_length=1,
        max_length=50,
    )


# ============================================================
# WRITE — comments (used by create_tools.py / update_tools.py)
# ============================================================

class CreateReviewCommentInput(RepoRef):
    pr_number: int = Field(..., description="Pull request number.", ge=1)
    body: str = Field(..., description="Comment text in Markdown.", min_length=1)
    commit_sha: str = Field(..., description="SHA of the commit being commented on — typically the PR's current head sha.", min_length=1)
    path: str = Field(..., description="File path within the diff being commented on.", min_length=1)
    line: int = Field(..., description="Line number in the file (in the new version) to attach the comment to.", ge=1)
    side: str = Field("RIGHT", description="Which side of the diff: 'RIGHT' (new/added lines) or 'LEFT' (old/removed lines).")


class CreateCommitCommentInput(RepoRef):
    commit_sha: str = Field(..., description="SHA of the commit to comment on.", min_length=1)
    body: str = Field(..., description="Comment text in Markdown.", min_length=1)
    path: Optional[str] = Field(None, description="Optional file path to attach the comment to a specific file in the commit.")
    line: Optional[int] = Field(None, description="Optional line number within that file.", ge=1)


class UpdateIssueCommentInput(RepoRef):
    comment_id: int = Field(..., description="ID of the existing comment (returned by add_issue_comment).", ge=1)
    body: str = Field(..., description="New comment text in Markdown, replacing the old text.", min_length=1)


# ============================================================
# READ — repository structure (used by read_tools.py)
# ============================================================

class GetRepositoryTreeInput(RepoRef):
    ref: Optional[str] = Field(None, description="Branch, tag, or commit SHA. Defaults to the repo's default branch.")
    path_prefix: Optional[str] = Field(None, description="Only return entries whose path starts with this prefix, e.g. 'src/'.")
    limit: int = Field(100, description="Max entries to return.", ge=1, le=500)
    offset: int = Field(0, description="Entries to skip (for pagination).", ge=0)


# ============================================================
# WRITE — branches & pull requests (used by create_tools.py)
# ============================================================

class CreateBranchInput(RepoRef):
    new_branch: str = Field(..., description="Name for the new branch, e.g. 'refactor/organize-src'.", min_length=1)
    base_branch: Optional[str] = Field(None, description="Branch to branch from. Defaults to the repo's default branch.")


class CreatePullRequestInput(RepoRef):
    title: str = Field(..., description="Pull request title.", min_length=1, max_length=256)
    head: str = Field(..., description="Branch containing your changes, e.g. 'refactor/organize-src'.", min_length=1)
    base: str = Field(..., description="Branch you want to merge into, e.g. 'main'.", min_length=1)
    body: Optional[str] = Field(None, description="Pull request description in Markdown.")
    draft: bool = Field(False, description="Open as a draft pull request.")