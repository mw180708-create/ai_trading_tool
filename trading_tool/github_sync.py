"""Bestanden bewaren in je GitHub-repository via de GitHub API (één commit per opslag).

Nodig: een fine-grained Personal Access Token met "Contents: Read and write" op de repository.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

import requests

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


@dataclass
class GitHubSync:
    token: str
    repo: str                 # "owner/naam"
    branch: str = "main"
    timeout: int = 60
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        self.session = self.session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    # ------------------------------------------------------------------ #
    def _req(self, method: str, path: str, **kw):
        r = self.session.request(method, f"{API}/repos/{self.repo}{path}", timeout=self.timeout, **kw)
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            raise GitHubError(f"GitHub {method} {path}: {r.status_code} {msg}")
        return r.json() if r.content else {}

    def check(self) -> tuple[bool, str]:
        """Controleer token + schrijfrechten."""
        try:
            info = self._req("GET", "")
        except (GitHubError, requests.RequestException) as e:
            return False, str(e)
        perms = info.get("permissions", {})
        if perms and not (perms.get("push") or perms.get("admin")):
            return False, "Token heeft geen schrijfrechten (Contents: Read and write) op deze repository."
        return True, f"Verbonden met {info.get('full_name', self.repo)}"

    def commit_files(self, files: dict[str, bytes | None], message: str) -> str:
        """Schrijf (bytes) of verwijder (None) meerdere bestanden in één commit. Retourneert commit-sha."""
        if not files:
            return ""
        ref = self._req("GET", f"/git/ref/heads/{self.branch}")
        head_sha = ref["object"]["sha"]
        base_tree = self._req("GET", f"/git/commits/{head_sha}")["tree"]["sha"]
        tree = []
        for path, content in files.items():
            if content is None:
                tree.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                continue
            blob = self._req("POST", "/git/blobs", json={
                "content": base64.b64encode(content).decode(), "encoding": "base64"})
            tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        new_tree = self._req("POST", "/git/trees", json={"base_tree": base_tree, "tree": tree})
        commit = self._req("POST", "/git/commits", json={
            "message": message, "tree": new_tree["sha"], "parents": [head_sha]})
        self._req("PATCH", f"/git/refs/heads/{self.branch}", json={"sha": commit["sha"]})
        return commit["sha"]

    def list_dir(self, path: str) -> list[str]:
        """Alle bestandspaden onder `path` (recursief) op de branch."""
        ref = self._req("GET", f"/git/ref/heads/{self.branch}")
        tree_sha = self._req("GET", f"/git/commits/{ref['object']['sha']}")["tree"]["sha"]
        tree = self._req("GET", f"/git/trees/{tree_sha}", params={"recursive": "1"})
        prefix = path.rstrip("/") + "/"
        return [t["path"] for t in tree.get("tree", []) if t["type"] == "blob" and t["path"].startswith(prefix)]
