"""AI Trading Tool - website (Streamlit).

Lokaal starten:   streamlit run app.py     (of dubbelklik START_WEBSITE.bat)
Online:           share.streamlit.io -> repo mw180708-create/ai_trading_tool -> streamlit_app.py
"""
from __future__ import annotations

import traceback

import streamlit as st

st.set_page_config(page_title="AI Trading Tool", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")

from webapp import nav, theme  # noqa: E402
from webapp.pages import backtest, dashboard, data, help as help_page, results, trades  # noqa: E402


def safe(fn):
    """Toon een nette foutmelding in plaats van een crash van de hele pagina."""
    def run():
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            if type(e).__name__ in ("RerunException", "StopException", "RerunData", "SwitchPageException"):
                raise
            st.error(f"Er ging iets mis: {e}")
            with st.expander("Technische details (stuur dit door als het probleem blijft)"):
                st.code(traceback.format_exc())
    run.__name__ = fn.__module__.rsplit(".", 1)[-1]
    return run


theme.inject()
nav.PAGES.update({
    "dashboard": st.Page(safe(dashboard.render), title="Dashboard", icon="🏠", url_path="dashboard", default=True),
    "data": st.Page(safe(data.render), title="Data", icon="📁", url_path="data"),
    "backtest": st.Page(safe(backtest.render), title="Backtest", icon="▶️", url_path="backtest"),
    "results": st.Page(safe(results.render), title="Resultaten", icon="📊", url_path="resultaten"),
    "trades": st.Page(safe(trades.render), title="Trades", icon="📋", url_path="trades"),
    "help": st.Page(safe(help_page.render), title="Uitleg", icon="ℹ️", url_path="uitleg"),
})
page = st.navigation(list(nav.PAGES.values()), position="top")
theme.brand()
page.run()
