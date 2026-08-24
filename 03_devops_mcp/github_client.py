import io
import os
import zipfile
from typing import Any

import httpx
from dotenv import load_dotenv


load_dotenv()


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not GITHUB_TOKEN:
    raise RuntimeError(
        "GITHUB_TOKEN is not configured."
    )


BASE_URL = "https://api.github.com"

# Max characters of combined log text returned to the agent — full logs can be
# megabytes; this keeps responses usable in an LLM context window.
MAX_LOG_CHARS = 20_000


class GitHubClient:

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request_raw(self, method: str, endpoint: str, headers: dict | None = None, **kwargs) -> httpx.Response:
        url = f"{BASE_URL}{endpoint}"

        response = httpx.request(
            method,
            url,
            headers=headers or self.headers,
            timeout=30,
            follow_redirects=True,
            **kwargs,
        )

        # Raises httpx.HTTPStatusError (with .response.status_code intact) on 4xx/5xx,
        # so the MCP layer can branch on the specific status code instead of parsing text.
        response.raise_for_status()
        return response

    def _request(self, method: str, endpoint: str, headers: dict | None = None, **kwargs) -> Any:
        response = self._request_raw(method, endpoint, headers=headers, **kwargs)

        if response.status_code == 204 or not response.content:
            return None

        return response.json()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_authenticated_user(self):

        return self._request(
            "GET",
            "/user",
        )

    def get_rate_limit(self):

        return self._request(
            "GET",
            "/rate_limit",
        )

    # ------------------------------------------------------------------
    # Repositories
    # ------------------------------------------------------------------

    def list_repositories(self, limit: int = 20):

        repositories = self._request(
            "GET",
            "/user/repos",
            params={
                "per_page": min(limit, 100),
                "sort": "updated",
                "direction": "desc",
            },
        )

        return repositories

    def search_repositories(self, query: str, limit: int = 10):

        return self._request(
            "GET",
            "/search/repositories",
            params={
                "q": query,
                "per_page": min(limit, 100),
            },
        )

    def get_repository(
        self,
        owner: str,
        repo: str,
    ):

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}",
        )

    def list_branches(
        self,
        owner: str,
        repo: str,
        limit: int = 30,
    ):

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/branches",
            params={
                "per_page": min(limit, 100),
            },
        )

    def get_branch_protection(
        self,
        owner: str,
        repo: str,
        branch: str,
    ):
        """Returns protection settings, or {"protected": False} if the branch
        has no protection rule (GitHub returns 404 in that case, which is a
        normal, expected outcome here, not an error)."""

        try:
            data = self._request(
                "GET",
                f"/repos/{owner}/{repo}/branches/{branch}/protection",
            )
            data["protected"] = True
            return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"protected": False}
            raise

    def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str | None = None,
    ):

        import base64

        params = {"ref": ref} if ref else {}

        data = self._request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{path}",
            params=params,
        )

        if data.get("encoding") == "base64" and data.get("content"):
            try:
                data["decoded_content"] = base64.b64decode(data["content"]).decode("utf-8")
            except UnicodeDecodeError:
                data["decoded_content"] = None  # binary file, not text-decodable

        return data

    # ------------------------------------------------------------------
    # Commits
    # ------------------------------------------------------------------

    def get_commits(
        self,
        owner: str,
        repo: str,
        limit: int = 10,
        branch: str | None = None,
    ):

        params: dict[str, Any] = {
            "per_page": min(limit, 100),
        }
        if branch:
            params["sha"] = branch

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits",
            params=params,
        )

    def compare_commits(
        self,
        owner: str,
        repo: str,
        base: str,
        head: str,
    ):

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/compare/{base}...{head}",
        )

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def get_issues(
        self,
        owner: str,
        repo: str,
        limit: int = 10,
        state: str = "open",
        labels: list[str] | None = None,
    ):

        params = {
            "state": state,
            "per_page": min(limit, 100),
        }
        if labels:
            params["labels"] = ",".join(labels)

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues",
            params=params,
        )

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ):

        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues",
            json=payload,
        )

    def update_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        state: str,
    ):

        return self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            json={"state": state},
        )

    def create_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ):

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )

    # ------------------------------------------------------------------
    # Pull requests
    # ------------------------------------------------------------------

    def get_pull_requests(
        self,
        owner: str,
        repo: str,
        limit: int = 10,
        state: str = "open",
    ):

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": state,
                "per_page": min(limit, 100),
            },
        )

    def get_pull_request_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        limit: int = 30,
    ):

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
            params={
                "per_page": min(limit, 100),
            },
        )

    def get_pull_request_diff(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> str:
        """Returns the raw unified diff text for a pull request."""

        diff_headers = {
            **self.headers,
            "Accept": "application/vnd.github.v3.diff",
        }

        response = self._request_raw(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=diff_headers,
        )

        return response.text

    def request_reviewers(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        reviewers: list[str],
    ):

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers",
            json={"reviewers": reviewers},
        )

    # ------------------------------------------------------------------
    # GitHub Actions
    # ------------------------------------------------------------------

    def get_workflows(
        self,
        owner: str,
        repo: str,
    ):

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/workflows",
        )

    def get_workflow_runs(
        self,
        owner: str,
        repo: str,
        limit: int = 10,
        branch: str | None = None,
        status: str | None = None,
    ):

        params: dict[str, Any] = {
            "per_page": min(limit, 100),
        }
        if branch:
            params["branch"] = branch
        if status:
            params["status"] = status

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs",
            params=params,
        )

    def get_workflow_run_jobs(
        self,
        owner: str,
        repo: str,
        run_id: int,
    ):

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
        )

    def get_workflow_run_logs(
        self,
        owner: str,
        repo: str,
        run_id: int,
    ) -> dict[str, bool | str]:
        """Downloads the run's log archive and returns combined, truncated log
        text. GitHub serves logs as a ZIP of per-job .txt files."""

        response = self._request_raw(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
        )

        combined = []
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name in sorted(archive.namelist()):
                if not name.endswith(".txt"):
                    continue
                text = archive.read(name).decode("utf-8", errors="replace")
                combined.append(f"===== {name} =====\n{text}")

        full_text = "\n\n".join(combined)
        truncated = len(full_text) > MAX_LOG_CHARS

        return {
            "text": full_text[:MAX_LOG_CHARS],
            "truncated": truncated,
        }

    def trigger_workflow_dispatch(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
        ref: str,
        inputs: dict[str, Any] | None = None,
    ):

        payload: dict[str, Any] = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs

        # 204 No Content on success — _request returns None, which is expected here.
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches",
            json=payload,
        )