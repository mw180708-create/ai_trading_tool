"""Ingelogd blijven: een ondertekende sessiecookie (30 dagen).

Inhoud: gebruikersnaam + vervaldatum, ondertekend met HMAC-SHA256. De sleutel komt uit de Secrets
(SESSION_SECRET) of wordt afgeleid van het GitHub-token, zodat sessies een herstart overleven. In de
handtekening zit ook een vingerafdruk van het wachtwoord: na een wachtwoordwijziging zijn oude sessies ongeldig.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

import streamlit as st
import streamlit.components.v1 as components

from . import state as S

COOKIE = "wng_session"
MAX_AGE = 30 * 24 * 3600


def _key() -> bytes:
    sec = S.secret("SESSION_SECRET")
    if sec:
        return hashlib.sha256(sec.encode()).digest()
    tok = S._cfg()[0]
    if tok:
        return hmac.new(b"wng-session-v1", tok.encode(), hashlib.sha256).digest()
    p = S.LOCAL_ROOT / "_session.key"            # zonder blijvende opslag: geldig tot een herstart
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(os.urandom(32))
    return p.read_bytes()


def _sign(payload: str, fingerprint: str) -> str:
    return hmac.new(_key(), f"{payload}|{fingerprint}".encode(), hashlib.sha256).hexdigest()


def issue(username: str) -> str | None:
    fp = S.accounts().fingerprint(username)
    if fp is None:
        return None
    payload = json.dumps({"u": username, "e": int(time.time()) + MAX_AGE}, separators=(",", ":"))
    body = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{body}.{_sign(payload, fp)}"


def verify(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
        data = json.loads(payload)
        user, exp = str(data["u"]), int(data["e"])
    except (ValueError, KeyError, TypeError):
        return None
    if exp < time.time():
        return None
    fp = S.accounts().fingerprint(user)
    if fp is None or not hmac.compare_digest(sig, _sign(payload, fp)):
        return None
    return user


def remember(username: str) -> None:
    tok = issue(username)
    if tok:
        st.session_state["_cookie_op"] = ("set", tok)


def forget() -> None:
    st.session_state["_cookie_op"] = ("clear", "")
    st.session_state["_no_autologin"] = True


def auto_login() -> None:
    """Log automatisch in met een geldige cookie (niet direct na uitloggen)."""
    if S.logged_in() or st.session_state.get("_no_autologin"):
        return
    try:
        tok = st.context.cookies.get(COOKIE)
    except Exception:  # noqa: BLE001
        tok = None
    user = verify(tok)
    if user:
        S.login_as(user)


def flush() -> None:
    """Voer een openstaande cookie-actie uit in de browser (onzichtbaar onderdeel)."""
    op = st.session_state.pop("_cookie_op", None)
    if not op:
        return
    action, tok = op
    age = MAX_AGE if action == "set" else 0
    value = tok if action == "set" else ""
    js = (f"var c='{COOKIE}={value}; path=/; max-age={age}; SameSite=Lax'"
          "+(location.protocol==='https:'?'; Secure':'');"
          "try{document.cookie=c}catch(e){};try{window.parent.document.cookie=c}catch(e){}")
    with st.container(key="cookie_sink"):
        components.html(f"<script>{js}</script>", height=0)
