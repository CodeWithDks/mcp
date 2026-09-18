import io
import logging
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# ----------------------------------------------------------------------
# Logging — goes to stderr, which Claude Desktop captures into its MCP
# server log files (see logs at: macOS ~/Library/Logs/Claude/,
# Windows %APPDATA%\Claude\logs\). Every request logs its timing so a
# slow/hanging call is visible there instead of just "Failed" with no
# detail in the chat UI.
# ----------------------------------------------------------------------

logger = logging.getLogger("github_mcp.client")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [github_mcp] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


class GitHubClient:

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # A persistent client reuses TLS/TCP connections across calls instead
        # of reconnecting every time — meaningfully faster for tools like
        # push_files that make several requests in a row. Split timeouts mean
        # a dead/unreachable connection fails fast (~10s) instead of sitting
        # on one generic 30s budget that can mask what's actually slow.
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=5.0),
            follow_redirects=True,
        )

    def _request(self, method: str, endpoint: str, headers: dict | None = None, raw: bool = False, **kwargs):

        start = time.monotonic()
        logger.info(f"-> {method} {endpoint}")

        try:
            response = self._client.request(
                method,
                endpoint,
                headers=headers or self.headers,
                **kwargs,
            )
        except httpx.TimeoutException as e:
            elapsed = time.monotonic() - start
            logger.error(f"x  {method} {endpoint} TIMED OUT after {elapsed:.1f}s ({type(e).__name__}): {e}")
            raise
        except httpx.RequestError as e:
            elapsed = time.monotonic() - start
            logger.error(f"x  {method} {endpoint} NETWORK ERROR after {elapsed:.1f}s ({type(e).__name__}): {e}")
            raise

        elapsed = time.monotonic() - start
        logger.info(f"<- {method} {endpoint} {response.status_code} in {elapsed:.2f}s")

        # Raises httpx.HTTPStatusError (with .response.status_code intact) on 4xx/5xx,
        # so the MCP layer can branch on the specific status code instead of parsing text.
        response.raise_for_status()

        if raw:
            return response

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

        params = {
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

        payload = {"title": title}
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

        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=diff_headers,
            raw=True,
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

        params = {
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
    ) -> str:
        """Downloads the run's log archive and returns combined, truncated log
        text. GitHub serves logs as a ZIP of per-job .txt files."""

        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
            raw=True,
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
        inputs: dict | None = None,
    ):

        payload = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs

        # 204 No Content on success — _request returns None, which is expected here.
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches",
            json=payload,
        )

    # ------------------------------------------------------------------
    # Files & commits — single-file writes via the Contents API, and
    # multi-file "push" via the lower-level Git Data API (blobs/trees/
    # commits/refs), which is what a real `git push` does under the hood.
    # ------------------------------------------------------------------

    def put_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        content_b64: str,
        message: str,
        branch: str | None = None,
        sha: str | None = None,
    ):
        """Create or update a single file. Pass `sha` (the file's current
        blob sha) to update an existing file; omit it to create a new one."""

        payload = {
            "message": message,
            "content": content_b64,
        }
        if branch:
            payload["branch"] = branch
        if sha:
            payload["sha"] = sha

        return self._request(
            "PUT",
            f"/repos/{owner}/{repo}/contents/{path}",
            json=payload,
        )

    def delete_file(
        self,
        owner: str,
        repo: str,
        path: str,
        message: str,
        sha: str,
        branch: str | None = None,
    ):

        payload = {
            "message": message,
            "sha": sha,
        }
        if branch:
            payload["branch"] = branch

        return self._request(
            "DELETE",
            f"/repos/{owner}/{repo}/contents/{path}",
            json=payload,
        )

    def get_ref(
        self,
        owner: str,
        repo: str,
        branch: str,
    ):

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/git/ref/heads/{branch}",
        )

    def get_git_commit(
        self,
        owner: str,
        repo: str,
        commit_sha: str,
    ):

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/git/commits/{commit_sha}",
        )

    def create_blob(
        self,
        owner: str,
        repo: str,
        content: str,
    ):

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/blobs",
            json={"content": content, "encoding": "utf-8"},
        )

    def create_tree(
        self,
        owner: str,
        repo: str,
        base_tree_sha: str,
        tree_entries: list[dict],
    ):

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/trees",
            json={"base_tree": base_tree_sha, "tree": tree_entries},
        )

    def create_git_commit(
        self,
        owner: str,
        repo: str,
        message: str,
        tree_sha: str,
        parent_sha: str,
    ):

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/commits",
            json={"message": message, "tree": tree_sha, "parents": [parent_sha]},
        )

    def update_ref(
        self,
        owner: str,
        repo: str,
        branch: str,
        commit_sha: str,
        force: bool = False,
    ):

        return self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
            json={"sha": commit_sha, "force": force},
        )

    def push_files(
        self,
        owner: str,
        repo: str,
        branch: str,
        message: str,
        files: list[dict],
    ):
        """Push one or more files (each {"path": ..., "content": ...}) to
        `branch` as a single new commit — equivalent to a local `git add` of
        each file, one commit, and a `git push`. Uses the Git Data API:
        read the branch tip -> create blobs (in parallel) -> create a new
        tree on top of the current tree -> create a commit -> fast-forward
        the branch ref.

        Blob creation is parallelized because each file's blob is
        independent of the others — doing them one at a time serially was
        the main source of slow/timed-out pushes for multi-file commits,
        since a client-side tool-call timeout applies to the whole call,
        not to each individual GitHub request.
        """

        push_start = time.monotonic()
        logger.info(f"push_files: starting — {owner}/{repo}@{branch}, {len(files)} file(s)")

        ref = self.get_ref(owner, repo, branch)
        parent_commit_sha = ref["object"]["sha"]

        parent_commit = self.get_git_commit(owner, repo, parent_commit_sha)
        base_tree_sha = parent_commit["tree"]["sha"]
        logger.info(f"push_files: resolved branch tip after {time.monotonic() - push_start:.2f}s")

        blobs_by_path: dict[str, dict] = {}
        errors: list[str] = []

        blob_start = time.monotonic()
        max_workers = min(8, len(files)) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_path = {
                pool.submit(self.create_blob, owner, repo, file["content"]): file["path"]
                for file in files
            }
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    blobs_by_path[path] = future.result()
                except Exception as e:
                    errors.append(f"{path}: {e}")

        logger.info(
            f"push_files: {len(blobs_by_path)}/{len(files)} blob(s) created in "
            f"{time.monotonic() - blob_start:.2f}s ({len(errors)} failed)"
        )

        if errors:
            raise RuntimeError(
                f"Failed to create blob(s) for {len(errors)} file(s): " + "; ".join(errors)
            )

        # Preserve the caller's original file order in the tree, rather than
        # the arbitrary completion order from the thread pool.
        tree_entries = [
            {
                "path": file["path"],
                "mode": "100644",
                "type": "blob",
                "sha": blobs_by_path[file["path"]]["sha"],
            }
            for file in files
        ]

        new_tree = self.create_tree(owner, repo, base_tree_sha, tree_entries)
        new_commit = self.create_git_commit(owner, repo, message, new_tree["sha"], parent_commit_sha)
        self.update_ref(owner, repo, branch, new_commit["sha"])

        logger.info(f"push_files: done in {time.monotonic() - push_start:.2f}s total")

        return new_commit

    # ------------------------------------------------------------------
    # Comments — general issue/PR comments already exist via
    # create_issue_comment(); these cover code-line review comments and
    # commit comments, plus editing an existing comment.
    # ------------------------------------------------------------------

    def create_review_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        commit_sha: str,
        path: str,
        line: int,
        side: str = "RIGHT",
    ):
        """Comment on a specific line of a specific file within a pull
        request's diff (a 'review comment', distinct from a general PR
        comment)."""

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            json={
                "body": body,
                "commit_id": commit_sha,
                "path": path,
                "line": line,
                "side": side,
            },
        )

    def create_commit_comment(
        self,
        owner: str,
        repo: str,
        commit_sha: str,
        body: str,
        path: str | None = None,
        line: int | None = None,
    ):

        payload = {"body": body}
        if path:
            payload["path"] = path
        if line is not None:
            payload["line"] = line

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/commits/{commit_sha}/comments",
            json=payload,
        )

    def update_issue_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        body: str,
    ):

        return self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
            json={"body": body},
        )

    # ------------------------------------------------------------------
    # Repository structure & branches — needed to read/organize a whole
    # repo's code (not just one file at a time) and to make the resulting
    # changes on a branch instead of directly on the default branch.
    # ------------------------------------------------------------------

    def get_repository_tree(
        self,
        owner: str,
        repo: str,
        ref: str | None = None,
        recursive: bool = True,
    ):
        """Full file/directory listing at a ref. If ref is omitted, resolves
        the repo's default branch first. `ref` also accepts a branch, tag,
        or commit sha (GitHub's trees endpoint supports all three)."""

        if not ref:
            repo_data = self.get_repository(owner, repo)
            ref = repo_data["default_branch"]

        params = {"recursive": "1"} if recursive else {}

        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/git/trees/{ref}",
            params=params,
        )

    def create_branch(
        self,
        owner: str,
        repo: str,
        new_branch: str,
        base_branch: str | None = None,
    ):
        """Create a new branch pointing at the current tip of base_branch
        (or the repo's default branch if base_branch is omitted)."""

        if not base_branch:
            repo_data = self.get_repository(owner, repo)
            base_branch = repo_data["default_branch"]

        base_ref = self.get_ref(owner, repo, base_branch)
        base_sha = base_ref["object"]["sha"]

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{new_branch}", "sha": base_sha},
        )

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str | None = None,
        draft: bool = False,
    ):

        payload = {
            "title": title,
            "head": head,
            "base": base,
            "draft": draft,
        }
        if body:
            payload["body"] = body

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json=payload,
        )