"""A minimal GitHub REST API client built on urllib."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

API = "https://api.github.com"


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"GitHub API {status}: {message}")


class GitHub:
    def __init__(self, repo: str, token: str = "", api: str = API, opener=None):
        if not repo or "/" not in repo:
            raise ValueError("repository must look like owner/name")
        self.repo = repo
        self.token = token
        self.api = api.rstrip("/")
        self._open = opener or urllib.request.urlopen

    def request(self, method: str, path: str, body: dict | None = None, params: dict | None = None):
        url = f"{self.api}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"GitHup/{__version__}",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._open(req, timeout=20) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise GitHubError(exc.code, detail) from None
        except urllib.error.URLError as exc:
            raise GitHubError(0, str(exc.reason)) from None
        return json.loads(raw) if raw else None

    # -- issues ------------------------------------------------------------

    def issues(self, labels: list[str], state: str = "open", per_page: int = 30) -> list[dict]:
        items = self.request("GET", f"/repos/{self.repo}/issues",
                             params={"labels": ",".join(labels), "state": state, "per_page": per_page,
                                     "sort": "created", "direction": "desc"}) or []
        return [i for i in items if "pull_request" not in i]

    def create_issue(self, title: str, body: str, labels: list[str], assignees: list[str] | None = None) -> dict:
        payload = {"title": title, "body": body, "labels": labels}
        if assignees:
            payload["assignees"] = assignees
        return self.request("POST", f"/repos/{self.repo}/issues", payload)

    def comment(self, number: int, body: str) -> dict:
        return self.request("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": body})

    def close_issue(self, number: int) -> dict:
        return self.request("PATCH", f"/repos/{self.repo}/issues/{number}",
                            {"state": "closed", "state_reason": "completed"})

    def ensure_label(self, name: str, color: str, description: str = "") -> None:
        try:
            self.request("POST", f"/repos/{self.repo}/labels",
                         {"name": name, "color": color.lstrip("#"), "description": description})
        except GitHubError as exc:
            if exc.status != 422:  # 422 = already exists
                raise
