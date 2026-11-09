"""AI Trading Tool - backtest-platform voor iedereen (Streamlit).

Lokaal starten:   streamlit run app.py     (of dubbelklik START_WEBSITE.bat)
Online:           share.streamlit.io -> repo mw180708-create/ai_trading_tool -> streamlit_app.py
"""
from __future__ import annotations

import traceback

import streamlit as st

st.set_page_config(page_title="AI Trading Tool", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")

from webapp import nav, state as S, theme  # noqa: E402
from webapp.pages import (backtest, dashboard, data, help as help_page, login, results, strategies,  # noqa: E402
                          trades)


def safe(fn):
    """Toon een nette foutmelding in plaats van een crash van de hele pagina."""
    def run():
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            st.error(f"Er ging iets mis: {e}")
            with st.expander("Technische details (stuur dit door als het probleem blijft)"):
                st.code(traceback.format_exc())
    run.__name__ = fn.__module__.rsplit(".", 1)[-1]
    return run


def account_menu() -> None:
    name = S.display_name()
    with st.popover(f"👤 {name}", width="stretch"):
        if S.is_guest():
            st.caption("Je bent ingelogd als gast. Niets wordt blijvend bewaard.")
            if st.button("Account maken / inloggen", width="stretch", type="primary"):
                S.logout()
                st.rerun()
            return
        st.caption(f"Ingelogd als **{name}**" + (" · beheerder" if S.is_admin() else ""))
        with st.expander("Wachtwoord wijzigen"):
            with st.form("pw_form", border=False):
                old = st.text_input("Huidig wachtwoord", type="password")
                new = st.text_input("Nieuw wachtwoord", type="password")
                if st.form_submit_button("Wijzigen", width="stretch"):
                    ok, msg = S.accounts().change_password(name, old, new)
                    (st.success if ok else st.error)(msg)
        if st.button("Uitloggen", width="stretch"):
            S.logout()
            S.flash("Je bent uitgelogd.", "info")
            st.rerun()


theme.inject()
nav.PAGES.clear()
if S.logged_in():
    nav.PAGES.update({
        "dashboard": st.Page(safe(dashboard.render), title="Dashboard", icon="🏠", url_path="dashboard", default=True),
        "strategies": st.Page(safe(strategies.render), title="Strategieën", icon="🧠", url_path="strategieen"),
        "data": st.Page(safe(data.render), title="Data", icon="📁", url_path="data"),
        "backtest": st.Page(safe(backtest.render), title="Backtest", icon="▶️", url_path="backtest"),
        "results": st.Page(safe(results.render), title="Resultaten", icon="📊", url_path="resultaten"),
        "trades": st.Page(safe(trades.render), title="Trades", icon="📋", url_path="trades"),
        "help": st.Page(safe(help_page.render), title="Uitleg", icon="ℹ️", url_path="uitleg"),
    })
else:
    nav.PAGES.update({
        "login": st.Page(safe(login.render), title="Welkom", icon="👋", url_path="welkom", default=True),
        "help": st.Page(safe(help_page.render), title="Uitleg", icon="ℹ️", url_path="uitleg"),
    })
page = st.navigation(list(nav.PAGES.values()), position="top")
head = st.columns([4, 1])
with head[0]:
    theme.brand()
if S.logged_in():
    with head[1]:
        account_menu()
page.run()
