"""Welkom: inloggen, account maken of als gast proberen."""
from __future__ import annotations

import streamlit as st

from .. import state as S
from ..theme import html_block, ptitle


def render() -> None:
    S.show_flash()
    left, right = st.columns([1.25, 1], gap="large")
    with left:
        html_block("""
<div style="padding:18px 4px 0 4px">
  <div style="font-family:'Space Grotesk';font-size:2.35rem;font-weight:700;line-height:1.15">
    Backtest <span style="color:var(--gold)">jouw</span> strategie.<br>Op jouw data. Zonder te programmeren.
  </div>
  <p style="color:#c4cad6;font-size:1.02rem;margin-top:14px;max-width:560px">
    Stel je eigen strategie samen met indicatoren of het Smart Money / POI-model, upload je eigen koersdata
    (MetaTrader, TradingView, crypto) en zie direct winrate, drawdown, profit factor en elke trade op de grafiek.
  </p>
  <ol class="steps" style="margin-top:18px">
    <li><b>Maak een gratis account</b> – je data, strategieën en resultaten zijn alleen voor jou zichtbaar.</li>
    <li><b>Bouw een strategie</b> vanuit een sjabloon of helemaal zelf, en deel hem als je wilt met de community.</li>
    <li><b>Backtest</b> op elke markt en timeframe (1m t/m 1M) en vergelijk je runs.</li>
  </ol>
</div>""")
    with right, st.container(key="panelglow_login"):
        modes = ["Inloggen", "Account maken"] if S.signup_open() else ["Inloggen"]
        mode = st.segmented_control("Modus", modes, default=modes[0], key="login_mode",
                                    label_visibility="collapsed") or modes[0]
        if mode == "Inloggen":
            ptitle("Inloggen")
            with st.form("login_form", border=False):
                u = st.text_input("Gebruikersnaam", autocomplete="username")
                p = st.text_input("Wachtwoord", type="password", autocomplete="current-password")
                go = st.form_submit_button("Inloggen", type="primary", width="stretch")
            if go:
                ok, msg = S.accounts().login(u, p)
                if ok:
                    S.login_as(u.strip().lower())
                    S.flash(f"Welkom terug, {u.strip().lower()}! 👋")
                    st.rerun()
                st.error(msg)
        else:
            ptitle("Nieuw account")
            with st.form("signup_form", border=False):
                u = st.text_input("Gebruikersnaam", help="3-24 tekens: kleine letters, cijfers, - en _",
                                  autocomplete="username")
                p1 = st.text_input("Wachtwoord (min. 8 tekens)", type="password", autocomplete="new-password")
                p2 = st.text_input("Herhaal wachtwoord", type="password", autocomplete="new-password")
                agree = st.checkbox("Ik begrijp dat backtests geen garantie zijn voor de toekomst en geen financieel advies.")
                go = st.form_submit_button("Account maken", type="primary", width="stretch")
            if go:
                if not agree:
                    st.error("Vink het vakje aan om verder te gaan.")
                else:
                    ok, msg = S.accounts().register(u, p1, p2)
                    if ok:
                        S.login_as(u.strip().lower())
                        S.flash(f"{msg} Welkom, {u.strip().lower()}! Begin bij **Strategieën** of **Data**.")
                        st.rerun()
                    st.error(msg)
            st.caption("Bewaar je wachtwoord goed: er is (nog) geen 'wachtwoord vergeten'-functie.")
        st.divider()
        if st.button("🧪  Eerst proberen als gast (demo-data)", width="stretch"):
            S.login_guest()
            S.flash("Je bent ingelogd als gast met demo-data. Niets wordt blijvend bewaard.", "info")
            st.rerun()
        if not S.github_status().get("ok"):
            st.caption("ℹ️ Deze website bewaart accounts nu alleen tijdelijk (geen GitHub-opslag gekoppeld).")
