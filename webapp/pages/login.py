"""Welkom: inloggen, account maken of als gast proberen."""
from __future__ import annotations

import streamlit as st

from .. import state as S
from ..theme import html_block


def render() -> None:
    S.show_flash()
    st.write("")
    left, _, right = st.columns([1.2, 0.15, 1], gap="large")
    with left:
        html_block("""
<div style="padding-top:28px">
  <div class="hero">Backtest je strategie<br>op je eigen data.</div>
  <div class="hero-sub">Stel een strategie samen zonder te programmeren, upload koersdata uit MetaTrader of
  TradingView en bekijk precies hoe hij in het verleden had gepresteerd.</div>
  <div style="margin-top:34px;max-width:520px">
    <div class="feature"><b>Strategiebouwer</b><br><span>Indicatoren, multi-timeframe voorwaarden, stop loss, take profit en trailing stops.</span></div>
    <div class="feature"><b>Elke markt, elke timeframe</b><br><span>Forex, indices, aandelen en crypto, van 1 minuut tot 1 maand.</span></div>
    <div class="feature"><b>Eerlijke resultaten</b><br><span>Geen vooruitkijken, spread en commissie per markt, elke trade terug te zien.</span></div>
  </div>
</div>""")
    with right, st.container(key="panel_login"):
        modes = ["Inloggen", "Account maken"] if S.signup_open() else ["Inloggen"]
        mode = st.segmented_control("Modus", modes, default=modes[0], key="login_mode",
                                    label_visibility="collapsed") or modes[0]
        if mode == "Inloggen":
            with st.form("login_form", border=False):
                u = st.text_input("Gebruikersnaam", autocomplete="username")
                p = st.text_input("Wachtwoord", type="password", autocomplete="current-password")
                go = st.form_submit_button("Inloggen", type="primary", width="stretch")
            if go:
                ok, msg = S.accounts().login(u, p)
                if ok:
                    S.login_as(u.strip().lower())
                    S.flash(f"Welkom terug, {u.strip().lower()}.")
                    st.rerun()
                st.error(msg)
        else:
            with st.form("signup_form", border=False):
                u = st.text_input("Gebruikersnaam", help="3-24 tekens: kleine letters, cijfers, - en _",
                                  autocomplete="username")
                p1 = st.text_input("Wachtwoord (min. 8 tekens)", type="password", autocomplete="new-password")
                p2 = st.text_input("Herhaal wachtwoord", type="password", autocomplete="new-password")
                agree = st.checkbox("Ik begrijp dat een backtest geen garantie is voor de toekomst en geen financieel advies.")
                go = st.form_submit_button("Account maken", type="primary", width="stretch")
            if go:
                if not agree:
                    st.error("Vink het vakje aan om verder te gaan.")
                else:
                    ok, msg = S.accounts().register(u, p1, p2)
                    if ok:
                        S.login_as(u.strip().lower())
                        S.flash(f"{msg} Welkom, {u.strip().lower()}. Begin bij Strategieën of Data.")
                        st.rerun()
                    st.error(msg)
            st.caption("Bewaar je wachtwoord goed: er is (nog) geen 'wachtwoord vergeten'-functie.")
        st.divider()
        if st.button("Doorgaan als gast", width="stretch"):
            S.login_guest()
            S.flash("Je bent ingelogd als gast met demo-data. Niets wordt blijvend bewaard.", "info")
            st.rerun()
        if not S.github_status().get("ok"):
            st.caption("Let op: accounts worden op deze installatie nog niet blijvend bewaard.")
