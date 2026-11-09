"""Register van pagina's (gevuld in app.py) zodat pagina's naar elkaar kunnen linken."""
PAGES: dict = {}


def go(name: str) -> None:
    import streamlit as st

    st.switch_page(PAGES[name])


def link(name: str, label: str, icon: str | None = None) -> None:
    import streamlit as st

    st.page_link(PAGES[name], label=label, icon=icon)
