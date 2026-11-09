"""Bestanden bewaren in je GitHub-repository via de GitHub API (één commit per opslag).

Nodig: een fine-grained Personal Access Token met "Contents: Read and write" op de repository.
"""
from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass

import requests

API = os.environ.get("AI_TRADING_GITHUB_API", "https://api.github.com")


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
        """Controleer token, toegang tot de repository én schrijfrechten (met duidelijke Nederlandse uitleg)."""
        try:
            r = self.session.request("GET", f"{API}/repos/{self.repo}", timeout=self.timeout)
        except requests.RequestException as e:
            return False, f"GitHub is niet bereikbaar ({e})."
        if r.status_code == 401:
            return False, ("GitHub accepteert het token niet: het is ongeldig, verlopen of niet volledig gekopieerd. "
                           "Een token begint met 'github_pat_' of 'ghp_'. Maak eventueel een nieuw token.")
        if r.status_code in (403, 404):
            return False, (f"Het token heeft geen toegang tot de repository '{self.repo}'. Controleer de naam van de "
                           "repository en kies bij het token 'Repository access' → ai_trading_tool "
                           "(of gebruik een classic token met vinkje 'repo').")
        if r.status_code >= 400:
            return False, f"GitHub gaf een fout ({r.status_code}): {r.text[:200]}"
        info = r.json() if r.content else {}
        # schrijfrecht echt testen: een los (ongebruikt) blob-object aanmaken verandert niets aan de repo
        try:
            w = self.session.request("POST", f"{API}/repos/{self.repo}/git/blobs", timeout=self.timeout,
                                     json={"content": "dGVzdA==", "encoding": "base64"})
        except requests.RequestException as e:
            return False, f"GitHub is niet bereikbaar ({e})."
        if w.status_code in (403, 404):
            return False, ("Het token mag lezen maar niet schrijven. Zet bij het token 'Repository permissions' → "
                           "'Contents' op 'Read and write' (classic token: vinkje 'repo').")
        if w.status_code == 409:
            return False, "De repository is leeg; zet er eerst minstens één bestand in."
        if w.status_code >= 400:
            return False, f"Schrijftest mislukt ({w.status_code}): {w.text[:200]}"
        return True, f"Verbonden met {info.get('full_name', self.repo)} - lezen en schrijven werkt."

    def commit_files(self, files: dict[str, bytes | None], message: str, attempts: int = 4) -> str:
        """Schrijf (bytes) of verwijder (None) meerdere bestanden in één commit. Retourneert commit-sha.

        Slaan meerdere gebruikers tegelijk iets op, dan kan GitHub de commit weigeren omdat de branch net is
        veranderd; dan wordt het automatisch opnieuw geprobeerd op de nieuwste versie."""
        if not files:
            return ""
        blobs: dict[str, str | None] = {}
        for path, content in files.items():
            blobs[path] = None if content is None else self._req("POST", "/git/blobs", json={
                "content": base64.b64encode(content).decode(), "encoding": "base64"})["sha"]
        last_err = None
        for i in range(attempts):
            try:
                return self._commit_tree(blobs, message)
            except GitHubError as e:
                last_err = e
                if " 422 " not in str(e) and " 409 " not in str(e):
                    raise
                time.sleep(0.5 * (i + 1))
        raise last_err  # type: ignore[misc]

    def _commit_tree(self, blobs: dict[str, str | None], message: str) -> str:
        ref = self._req("GET", f"/git/ref/heads/{self.branch}")
        head_sha = ref["object"]["sha"]
        base_tree = self._req("GET", f"/git/commits/{head_sha}")["tree"]["sha"]
        tree = [{"path": p, "mode": "100644", "type": "blob", "sha": sha} for p, sha in blobs.items()]
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
