"""Inloggen, account maken of als gast verder."""
from __future__ import annotations

import streamlit as st

from .. import state as S
from ..session_cookie import remember
from ..theme import html_block


def _switch(mode: str) -> None:
    st.session_state["login_mode"] = mode


def render() -> None:
    mode = st.session_state.get("login_mode", "login")
    if mode == "signup" and not S.signup_open():
        mode = "login"
    _, mid, _ = st.columns([1, 1.05, 1])
    with mid:
        st.write("")
        html_block(f'<div class="auth-title">{"Inloggen" if mode == "login" else "Account maken"}</div>'
                   '<div class="auth-sub">Backtest je strategieën op je eigen koersdata.</div>')
        S.show_flash()
        if mode == "login":
            with st.form("login_form", border=False):
                u = st.text_input("Gebruikersnaam", autocomplete="username")
                p = st.text_input("Wachtwoord", type="password", autocomplete="current-password")
                go = st.form_submit_button("Inloggen", type="primary", width="stretch")
            if go:
                ok, msg = S.accounts().login(u, p)
                if ok:
                    name = u.strip().lower()
                    S.login_as(name)
                    remember(name)
                    st.rerun()
                st.error(msg)
            if S.signup_open():
                st.button("Nog geen account? Maak er een aan", on_click=_switch, args=("signup",), type="tertiary",
                          width="stretch")
        else:
            with st.form("signup_form", border=False):
                u = st.text_input("Gebruikersnaam", help="3–24 tekens: kleine letters, cijfers, - en _",
                                  autocomplete="username")
                p1 = st.text_input("Wachtwoord", type="password", autocomplete="new-password",
                                   help="Minimaal 8 tekens")
                p2 = st.text_input("Herhaal wachtwoord", type="password", autocomplete="new-password")
                agree = st.checkbox("Ik begrijp dat een backtest geen garantie is voor de toekomst en geen financieel advies.")
                go = st.form_submit_button("Account maken", type="primary", width="stretch")
            if go:
                if not agree:
                    st.error("Bevestig eerst dat je dit begrijpt.")
                else:
                    ok, msg = S.accounts().register(u, p1, p2)
                    if ok:
                        name = u.strip().lower()
                        S.login_as(name)
                        remember(name)
                        S.flash(f"Welkom bij wng, {name}.")
                        st.rerun()
                    st.error(msg)
            st.button("Heb je al een account? Inloggen", on_click=_switch, args=("login",), type="tertiary",
                      width="stretch")
        html_block('<div class="auth-divider"><span>of</span></div>')
        if st.button("Verder als gast", width="stretch"):
            S.login_guest()
            S.flash("Je bekijkt wng als gast met voorbeelddata. Er wordt niets bewaard.", "info")
            st.rerun()
        if not S.persistent():
            st.caption("Let op: deze installatie bewaart accounts nog niet blijvend.")
