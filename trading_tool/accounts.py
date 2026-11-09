"""Gebruikersaccounts: registreren, inloggen en wachtwoord wijzigen.

* Wachtwoorden worden nooit zelf opgeslagen: alleen een scrypt-hash met een eigen salt per gebruiker.
* Na 5 mislukte pogingen wordt een gebruikersnaam 5 minuten geblokkeerd.
* Elk account krijgt een eigen afgeschermde map: data/store/users/<gebruikersnaam>/
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from pathlib import Path

from .github_sync import GitHubSync
from .storage import DataStore

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,23}$")
RESERVED = {"admin", "root", "guest", "guests", "users", "shared", "system", "gedeeld", "demo", "_results"}
PROFILE = "account/profile.json"
MAX_FAILS, LOCK_SECONDS = 5, 300
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


def normalize_username(name: str) -> str:
    return (name or "").strip().lower()


def hash_password(password: str, salt: bytes | None = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, maxmem=64 * 1024 * 1024, **_SCRYPT)
    return {"algo": "scrypt", **{k: v for k, v in _SCRYPT.items() if k != "dklen"}, "salt": salt.hex(), "hash": h.hex()}


def verify_password(password: str, rec: dict) -> bool:
    try:
        salt = bytes.fromhex(rec["salt"])
        h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(rec["n"]), r=int(rec["r"]), p=int(rec["p"]),
                           dklen=len(bytes.fromhex(rec["hash"])), maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(h.hex(), rec["hash"])
    except (KeyError, ValueError, TypeError):
        return False


def check_new_password(pw: str) -> str | None:
    if len(pw) < 8:
        return "Kies een wachtwoord van minstens 8 tekens."
    if pw.isdigit() or pw.lower() in {"wachtwoord", "password", "12345678", "qwertyui"}:
        return "Dit wachtwoord is te makkelijk te raden."
    return None


class Accounts:
    def __init__(self, repo_root: str | Path, github: GitHubSync | None = None, local_root: str | Path | None = None):
        self.repo_root = Path(repo_root)
        self.github = github
        self.local_root = local_root
        self._fails: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def store_for(self, username: str) -> DataStore:
        return DataStore(self.repo_root, local_root=self.local_root, github=self.github,
                         namespace=f"users/{normalize_username(username)}")

    def exists(self, username: str) -> bool:
        return self.store_for(username).get_json(PROFILE) is not None

    def profile(self, username: str) -> dict | None:
        p = self.store_for(username).get_json(PROFILE)
        if p:
            p = {k: v for k, v in p.items() if k != "password"}
        return p

    def list_users(self) -> list[str]:
        local = Path(self.local_root) if self.local_root else self.repo_root / ".datastore"
        names: set[str] = set()
        for base in (self.repo_root / "data" / "store" / "users", local / "users"):
            if base.is_dir():
                names |= {p.name for p in base.iterdir() if p.is_dir()}
        return sorted(u for u in names if self.exists(u))

    # ------------------------------------------------------------------ #
    def register(self, username: str, password: str, password2: str | None = None) -> tuple[bool, str]:
        u = normalize_username(username)
        if not USERNAME_RE.match(u):
            return False, "Gebruikersnaam: 3-24 tekens, alleen kleine letters, cijfers, - en _ (begin met letter/cijfer)."
        if u in RESERVED:
            return False, "Deze gebruikersnaam is niet beschikbaar."
        if password2 is not None and password != password2:
            return False, "De wachtwoorden zijn niet hetzelfde."
        problem = check_new_password(password)
        if problem:
            return False, problem
        with self._lock:
            if self.exists(u):
                return False, "Deze gebruikersnaam is al in gebruik."
            rep = self.store_for(u).put_json(PROFILE, {"username": u, "created": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
                                                       "password": hash_password(password)}, f"Nieuw account: {u}")
        if rep.error:
            return True, f"Account aangemaakt (let op: opslaan op GitHub mislukte: {rep.error})."
        return True, "Account aangemaakt."

    def login(self, username: str, password: str) -> tuple[bool, str]:
        u = normalize_username(username)
        now = time.time()
        fails, until = self._fails.get(u, (0, 0.0))
        if until > now:
            return False, f"Te veel mislukte pogingen. Probeer het over {int((until - now) // 60) + 1} minuten opnieuw."
        rec = self.store_for(u).get_json(PROFILE) if USERNAME_RE.match(u) else None
        if rec and verify_password(password, rec.get("password", {})):
            self._fails.pop(u, None)
            return True, "Ingelogd."
        if not rec:   # zelfde rekentijd als bij een echt account (geen info over bestaan)
            verify_password(password, hash_password("x" * 12))
        fails += 1
        self._fails[u] = (fails, now + LOCK_SECONDS if fails >= MAX_FAILS else 0.0)
        return False, "Gebruikersnaam of wachtwoord klopt niet."

    def change_password(self, username: str, old: str, new: str) -> tuple[bool, str]:
        u = normalize_username(username)
        store = self.store_for(u)
        rec = store.get_json(PROFILE)
        if not rec or not verify_password(old, rec.get("password", {})):
            return False, "Je huidige wachtwoord klopt niet."
        problem = check_new_password(new)
        if problem:
            return False, problem
        rec["password"] = hash_password(new)
        store.put_json(PROFILE, rec, f"Wachtwoord gewijzigd: {u}")
        return True, "Wachtwoord gewijzigd."
