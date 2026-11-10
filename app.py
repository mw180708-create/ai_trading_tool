"""wng - backtest-platform (Streamlit).

Lokaal starten:   streamlit run app.py     (of dubbelklik START_WEBSITE.bat)
Online:           share.streamlit.io -> repo mw180708-create/ai_trading_tool -> streamlit_app.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import streamlit as st

_ICON = Path(__file__).resolve().parent / "assets" / "wng-icon.png"
st.set_page_config(page_title="wng", page_icon=str(_ICON), layout="wide", initial_sidebar_state="collapsed")

_ROOT = Path(__file__).resolve().parent
_PACKAGES = ("trading_tool", "webapp")


def _ensure_fresh_code() -> None:
    """Na een update (git pull op Streamlit Cloud) kan Python nog oude onderdelen in het geheugen hebben,
    terwijl nieuwe onderdelen al nieuwe code verwachten (bv. KeyError). Is er iets veranderd, dan worden alle
    eigen onderdelen en caches opnieuw geladen."""
    files = sorted(p for pkg in _PACKAGES for p in (_ROOT / pkg).rglob("*.py"))
    version = hash(tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files))
    if getattr(sys, "_ai_trading_code_version", None) == version:
        return
    for name in [n for n in sys.modules if n.split(".")[0] in _PACKAGES]:
        del sys.modules[name]
    st.cache_data.clear()
    st.cache_resource.clear()
    sys._ai_trading_code_version = version


_ensure_fresh_code()

from webapp import nav, session_cookie as cookie, state as S, theme  # noqa: E402
from webapp.pages import (admin, backtest, dashboard, data, help as help_page, login, results,  # noqa: E402
                          strategies, trades)


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
    with st.container(key="acct"):
        with st.popover(name, width="content"):
            if S.is_guest():
                st.caption("Je bekijkt wng als gast. Er wordt niets bewaard.")
                if st.button("Inloggen of account maken", width="stretch", type="primary"):
                    S.logout()
                    st.rerun()
                return
            st.caption(f"Ingelogd als {name}" + (" (beheerder)" if S.is_admin() else ""))
            with st.expander("Wachtwoord wijzigen"):
                with st.form("pw_form", border=False):
                    old = st.text_input("Huidig wachtwoord", type="password")
                    new = st.text_input("Nieuw wachtwoord", type="password")
                    if st.form_submit_button("Wijzigen", width="stretch"):
                        ok, msg = S.accounts().change_password(name, old, new)
                        if ok:
                            cookie.remember(name)          # oude sessies zijn nu ongeldig
                        (st.success if ok else st.error)(msg)
            if st.button("Uitloggen", width="stretch"):
                S.logout()
                st.rerun()


def storage_notice(current: str) -> None:
    """Beheerders zien een duidelijke melding zolang de opslag niet blijvend is."""
    if current == "beheer" or S.is_guest() or not S.can_manage() or S.persistent():
        return
    c1, c2 = st.columns([6, 1])
    c1.markdown('<div class="notice">Opslag is nog tijdelijk: accounts en data verdwijnen bij een herstart van de '
                'website.</div>', unsafe_allow_html=True)
    if c2.button("Instellen", key="notice_setup", width="stretch"):
        nav.go("admin")


theme.inject()
st.logo(str(theme.LOGO), size="large", icon_image=str(theme.LOGO))
cookie.auto_login()
nav.PAGES.clear()
if S.logged_in():
    nav.PAGES.update({
        "dashboard": st.Page(safe(dashboard.render), title="Dashboard", url_path="dashboard", default=True),
        "strategies": st.Page(safe(strategies.render), title="Strategieën", url_path="strategieen"),
        "data": st.Page(safe(data.render), title="Data", url_path="data"),
        "backtest": st.Page(safe(backtest.render), title="Backtest", url_path="backtest"),
        "results": st.Page(safe(results.render), title="Resultaten", url_path="resultaten"),
        "trades": st.Page(safe(trades.render), title="Trades", url_path="trades"),
        "help": st.Page(safe(help_page.render), title="Uitleg", url_path="uitleg"),
    })
    if S.can_manage():
        nav.PAGES["admin"] = st.Page(safe(admin.render), title="Beheer", url_path="beheer")
else:
    nav.PAGES.update({
        "login": st.Page(safe(login.render), title="Inloggen", url_path="inloggen", default=True),
        "help": st.Page(safe(help_page.render), title="Uitleg", url_path="uitleg"),
    })
page = st.navigation(list(nav.PAGES.values()), position="top")
if S.logged_in():
    head = st.columns([6, 1], vertical_alignment="center")
    with head[0]:
        theme.page_header(page.title)
    with head[1]:
        account_menu()
    storage_notice(page.url_path)
page.run()
theme.footer()
cookie.flush()
