"""Gegevens blijvend bewaren in een (privé) GitHub-repository via de GitHub API.

* Schrijven: één commit per opslag (meerdere bestanden tegelijk), met automatische herhaling als meerdere
  gebruikers tegelijk opslaan.
* Lezen na een herstart: `restore()` haalt alle bestanden terug naar een lokale cache.
* `ensure_repo()` maakt de privé opslag-repository aan als die nog niet bestaat (classic token met 'repo').
"""
from __future__ import annotations

import base64
import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path

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

    def _get(self, url_path: str, **kw) -> requests.Response:
        return self.session.request("GET", f"{API}{url_path}", timeout=self.timeout, **kw)

    def user_login(self) -> str | None:
        r = self._get("/user")
        return r.json().get("login") if r.status_code == 200 else None

    def repo_exists(self) -> bool:
        return self._get(f"/repos/{self.repo}").status_code == 200

    def ensure_repo(self) -> tuple[bool, str]:
        """Maak de opslag-repository (privé, met README) aan als hij nog niet bestaat."""
        if self.repo_exists():
            return True, "bestaat al"
        owner, _, name = self.repo.partition("/")
        login = self.user_login()
        if login is None:
            return False, "GitHub accepteert het token niet (ongeldig of verlopen)."
        url = "/user/repos" if owner.lower() == login.lower() else f"/orgs/{owner}/repos"
        r = self.session.request("POST", f"{API}{url}", timeout=self.timeout, json={
            "name": name, "private": True, "auto_init": True,
            "description": "Opslag voor wng: accounts, koersdata, strategieën en resultaten (privé)."})
        if r.status_code not in (200, 201):
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            return False, (f"Kon de privé repository '{self.repo}' niet aanmaken ({r.status_code}: {msg}). Maak hem "
                           "zelf aan op github.com/new (privé, met README) of gebruik een classic token met vinkje 'repo'.")
        for _ in range(10):                      # GitHub heeft soms even nodig
            if self.repo_exists():
                break
            time.sleep(1)
        return True, "aangemaakt"

    def _sync_branch(self) -> None:
        """Gebruik de standaard-branch van de repository als de ingestelde branch niet bestaat."""
        if self._get(f"/repos/{self.repo}/git/ref/heads/{self.branch}").status_code == 200:
            return
        r = self._get(f"/repos/{self.repo}")
        if r.status_code == 200 and r.json().get("default_branch"):
            self.branch = r.json()["default_branch"]

    def _bootstrap_empty(self) -> None:
        """Een lege repository (zonder commits) krijgt eerst een README, anders kan er niet gecommit worden."""
        self.session.request("PUT", f"{API}/repos/{self.repo}/contents/README.md", timeout=self.timeout, json={
            "message": "Opslag voor wng", "content": base64.b64encode(b"# Opslag voor wng\n").decode()})

    @staticmethod
    def git_blob_sha(data: bytes) -> str:
        return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()

    def tree(self) -> list[dict]:
        ref = self._req("GET", f"/git/ref/heads/{self.branch}")
        tree_sha = self._req("GET", f"/git/commits/{ref['object']['sha']}")["tree"]["sha"]
        return [t for t in self._req("GET", f"/git/trees/{tree_sha}", params={"recursive": "1"}).get("tree", [])
                if t.get("type") == "blob"]

    def restore(self, prefix: str, dest_root: Path, progress=None) -> int:
        """Zet alle bestanden onder `prefix` uit de repository in `dest_root` (alleen gewijzigde worden gedownload).
        Bestanden die in de repository niet meer bestaan, worden ook lokaal verwijderd."""
        dest_root = Path(dest_root)
        try:
            items = [t for t in self.tree() if t["path"].startswith(prefix.rstrip("/") + "/")]
        except GitHubError as e:
            if " 409 " in str(e) or " 404 " in str(e):   # lege repository / nog geen branch
                return 0
            raise
        wanted = set()
        n = 0
        for i, t in enumerate(items):
            p = dest_root / t["path"]
            wanted.add(p)
            if p.exists() and self.git_blob_sha(p.read_bytes()) == t["sha"]:
                continue
            blob = self._req("GET", f"/git/blobs/{t['sha']}")
            data = base64.b64decode(blob["content"]) if blob.get("encoding") == "base64" else blob["content"].encode()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
            n += 1
            if progress:
                progress(i + 1, len(items))
        base = dest_root / prefix
        if base.is_dir():
            for f in base.rglob("*"):
                if f.is_file() and f not in wanted:
                    f.unlink()
        return n

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
            return False, (f"De repository '{self.repo}' bestaat niet of het token heeft er geen toegang toe. "
                           "Gebruik een classic token met vinkje 'repo', dan maakt wng de privé repository zelf aan.")
        if r.status_code >= 400:
            return False, f"GitHub gaf een fout ({r.status_code}): {r.text[:200]}"
        info = r.json() if r.content else {}
        self._sync_branch()
        # schrijfrecht echt testen: een los (ongebruikt) blob-object aanmaken verandert niets aan de repo
        try:
            w = self.session.request("POST", f"{API}/repos/{self.repo}/git/blobs", timeout=self.timeout,
                                     json={"content": "dGVzdA==", "encoding": "base64"})
        except requests.RequestException as e:
            return False, f"GitHub is niet bereikbaar ({e})."
        if w.status_code in (403, 404):
            return False, ("Het token mag lezen maar niet schrijven. Zet bij het token 'Repository permissions' → "
                           "'Contents' op 'Read and write' (classic token: vinkje 'repo').")
        if w.status_code == 409:                 # lege repository: eerst een README zetten
            self._bootstrap_empty()
            self._sync_branch()
        if w.status_code >= 400:
            return False, f"Schrijftest mislukt ({w.status_code}): {w.text[:200]}"
        private = "privé" if info.get("private") else "OPENBAAR - zet hem op privé!"
        return True, f"Verbonden met {info.get('full_name', self.repo)} ({private})."

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
        try:
            ref = self._req("GET", f"/git/ref/heads/{self.branch}")
        except GitHubError as e:
            if " 409 " not in str(e) and " 404 " not in str(e):
                raise
            self._bootstrap_empty()
            self._sync_branch()
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
