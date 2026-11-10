"""Beheer: blijvende opslag koppelen en gebruikersoverzicht (alleen voor beheerders)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import state as S
from ..theme import badge, html_block, ptitle

TOKEN_URL = "https://github.com/settings/tokens/new?scopes=repo&description=wng-opslag"


def _secrets_text(token: str) -> str:
    lines = [f'GITHUB_TOKEN = "{token}"']
    if S.user():
        lines.append(f'ADMIN_USERS = "{S.user()}"')
    return "\n".join(lines)


def _storage() -> None:
    status = S.github_status()
    gh = S.github()
    with st.container(key="panel_storage"):
        ptitle("Opslag")
        if gh is not None:
            src = {"secrets": "uit de Secrets", "website": "tijdelijk op de website geplakt",
                   "omgeving": "uit een omgevingsvariabele"}.get(status.get("source"), "")
            html_block(f"{badge('Blijvend', 'ok')}&nbsp; Accounts, data, strategieën en resultaten worden bewaard in de "
                       f"privé repository <b>{status['repo']}</b> (token {src}).")
            c1, c2, _ = st.columns([1, 1, 3])
            if c1.button("Verbinding testen", width="stretch"):
                ok, msg = gh.check()
                (st.success if ok else st.error)(msg)
            pending = S.unsynced_count()
            if pending and c2.button(f"{pending} bestand(en) opslaan", width="stretch", type="primary"):
                with st.spinner("Opslaan…"):
                    n, err = S.push_all_unsynced()
                S.flash(f"{n} bestand(en) opgeslagen." if not err else f"Opslaan mislukt: {err}",
                        "success" if not err else "error")
                st.rerun()
            if status.get("source") == "website":
                st.warning("Het token staat nog niet in de Secrets. Na een herstart blijven alle gegevens bewaard, maar "
                           "nieuwe gegevens pas weer zodra het token in de Secrets staat.")
                _step_secrets()
            return

        html_block(f"{badge('Tijdelijk', 'warn')}&nbsp; Zonder koppeling verdwijnen accounts en data bij elke herstart "
                   "of update van de website.")
        if status.get("secrets_error"):
            st.error(f"De Secrets bevatten een schrijffout: {status['secrets_error'][:200]}. Wis het tekstvak in de "
                     "Secrets en plak de tekst uit stap 3 opnieuw.")
        elif status.get("configured") and status.get("msg"):
            st.error(status["msg"])
            if st.button("Opnieuw proberen"):
                S.reset_github()
                st.rerun()

        st.markdown("**1. Maak een toegangscode (token) op GitHub**")
        st.markdown("Het vinkje *repo* staat al aan. Kies een vervaldatum, klik onderaan op **Generate token** en "
                    "kopieer de code die begint met `ghp_`.")
        st.link_button("Token aanmaken op GitHub", TOKEN_URL)
        st.markdown("**2. Plak de code hier**")
        c1, c2 = st.columns([3, 1])
        tok = c1.text_input("Token", type="password", placeholder="ghp_…", label_visibility="collapsed", key="gh_token")
        if c2.button("Koppelen", type="primary", width="stretch", disabled=not tok):
            with st.spinner("Koppelen… (wng maakt zo nodig een privé repository aan)"):
                ok, msg, repo = S.test_token(tok, status.get("repo"))
                if ok:
                    S.use_token_now(tok, repo)
                    st.session_state["gh_ok_token"] = S.clean_token(tok)
                    n, err = S.push_all_unsynced()
            if ok:
                S.flash(f"Gekoppeld aan {repo}. {n} bestaand(e) bestand(en) opgeslagen." +
                        (f" Let op: {err}" if err else ""), "success")
                st.rerun()
            st.error(msg)
        st.caption("wng maakt een privé repository 'wng-data' aan in je GitHub-account. Alleen jij hebt daar toegang toe.")


def _step_secrets() -> None:
    tok = st.session_state.get("gh_ok_token")
    st.markdown("**3. Zet de code in de Secrets van Streamlit**")
    st.markdown("Open je app op share.streamlit.io → **⋮** → **Settings** → **Secrets**, wis wat er staat en plak:")
    st.code(_secrets_text(tok or "plak-hier-je-token"), language="toml")
    st.link_button("Naar share.streamlit.io", "https://share.streamlit.io")
    st.caption("Klik daarna op Save changes. De website herstart en alles blijft voortaan bewaard.")


def _users() -> None:
    acc = S.accounts()
    users = acc.list_users()
    with st.container(key="panel_users"):
        ptitle(f"Gebruikers ({len(users)})")
        if not users:
            st.caption("Nog geen accounts.")
            return
        rows = []
        for u in users:
            p = acc.profile(u) or {}
            rows.append({"Gebruiker": u, "Aangemaakt": p.get("created", "-"), "Beheerder": "ja" if u in S.admins() else ""})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render() -> None:
    S.show_flash()
    if not S.can_manage():
        st.info("Deze pagina is alleen voor beheerders.")
        return
    _storage()
    st.write("")
    _users()
    if not S.admins():
        st.caption("Tip: zet jezelf als beheerder in de Secrets (ADMIN_USERS), dan zien andere gebruikers deze pagina niet.")
