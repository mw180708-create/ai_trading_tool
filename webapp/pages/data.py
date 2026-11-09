"""Data: bibliotheek (blijvend bewaard), uploaden, downloaden en GitHub-koppeling."""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from trading_tool.config import TIMEFRAMES, normalize_tf
from trading_tool.data_loader import detect_tf, read_ohlc_csv
from trading_tool.downloaders import download_btc

from .. import state as S
from ..charts import candles_payload, tv_chart
from ..theme import badge, html_block, ptitle

SYMBOLS = S.SYMBOLS


def tf_from_name(name: str) -> str | None:
    for part in reversed(re.split(r"[_\-\s,.]+", Path(name).stem)):
        try:
            return normalize_tf(part)
        except ValueError:
            continue
    return None


def symbol_from_name(name: str) -> str | None:
    up = Path(name).stem.upper()
    if "XAU" in up or "GOLD" in up:
        return "XAUUSD"
    if "BTC" in up or "XBT" in up:
        return "BTCUSD"
    return None


@st.cache_data(show_spinner=False, max_entries=16)
def parse_upload(data: bytes, name: str) -> pd.DataFrame:
    buf = io.BytesIO(data)
    buf.name = name
    return read_ohlc_csv(buf)


SECRETS_TEMPLATE = 'GITHUB_TOKEN = "{token}"\nGITHUB_REPO = "{repo}"'


def _save_step(status: dict) -> None:
    tok = st.session_state.get("gh_ok_token")
    st.markdown("##### Stap 3 · Vast opslaan (zodat je het niet opnieuw hoeft te plakken)")
    st.markdown("Het token werkt nu **tot de website herstart**. Zet het in de *Secrets* van Streamlit om het "
                "blijvend te bewaren:")
    st.markdown("""
1. Ga naar **https://share.streamlit.io** en log in.
2. Klik bij je app rechts op de **drie puntjes ⋮** → **Settings**.
3. Kies links **Secrets**.
4. Klik in het grote tekstvak, **wis wat erin staat** en plak precies onderstaande tekst (kopieer-knop rechtsboven):
""")
    st.code(SECRETS_TEMPLATE.format(token=tok or "PLAK-HIER-JE-TOKEN", repo=status.get("repo")), language="toml")
    st.markdown("5. Klik **Save changes**. Na ±1 minuut staat hier *Token uit: Secrets (blijvend)*.")
    st.caption('Let op: de aanhalingstekens " " zijn nodig. Plak dus niet alleen de code zelf.')


def _connect_wizard(status: dict) -> None:
    """Stap-voor-stap: token maken → testen op de website → (optioneel) vast opslaan in Secrets."""
    st.markdown("##### Stap 1 · Maak een token op GitHub")
    t_easy, t_fine = st.tabs(["Makkelijkste manier (classic token)", "Veiligere manier (fine-grained token)"])
    with t_easy:
        st.markdown("""
1. Open **https://github.com/settings/tokens/new** (log in als *mw180708-create*).
2. **Note**: typ `ai-trading-tool` · **Expiration**: kies *No expiration* of *1 year*.
3. Zet een vinkje bij **repo** (het bovenste vakje, de rest gaat vanzelf mee).
4. Scroll naar beneden → **Generate token** → klik op het kopieer-icoontje naast de code (begint met `ghp_`).

⚠️ GitHub laat de code maar één keer zien. Kwijt? Maak gewoon een nieuwe.
""")
    with t_fine:
        st.markdown("""
1. Open **https://github.com/settings/personal-access-tokens/new**.
2. **Token name** `ai-trading-tool` · **Expiration** naar keuze.
3. **Repository access** → *Only select repositories* → kies **ai_trading_tool**.
4. **Permissions** → klik **Add permissions** (of *Repository permissions*) → **Contents** → zet op **Read and write**.
5. **Generate token** → kopieer de code (begint met `github_pat_`).
""")

    st.markdown("##### Stap 2 · Plak het token hier en test het")
    c1, c2 = st.columns([3, 1])
    tok = c1.text_input("Token", type="password", placeholder="ghp_... of github_pat_...",
                        label_visibility="collapsed", key="gh_token_input")
    test = c2.button("Testen & koppelen", type="primary", width="stretch", disabled=not tok)
    if test and tok:
        with st.spinner("Token controleren bij GitHub..."):
            ok, msg = S.test_token(tok, status.get("repo"))
        if ok:
            S.use_token_now(tok, status.get("repo"))
            st.session_state["gh_ok_token"] = S.clean_token(tok)
            S.flash("✅ Gelukt! " + msg + " Opslaan op GitHub staat nu aan.", "success")
            st.rerun()
        else:
            st.error("❌ " + msg)

    if st.session_state.get("gh_ok_token"):
        _save_step(status)


def _storage_panel() -> None:
    store = S.store()
    status = S.github_status()
    with st.container(key="panel_storage"):
        if store.synced:
            src = {"secrets": "Secrets (blijvend)", "website": "op de website geplakt (tot herstart)",
                   "omgeving": "omgevingsvariabele"}.get(status.get("source"), "")
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"{badge('Opslag gekoppeld aan GitHub ✓', 'ok')} &nbsp; Alles wat je opslaat komt in "
                        f"**{status['repo']}** (map `data/store/`) en blijft bewaard.  \n"
                        f"<span class='small-note'>Token uit: {src}</span>", unsafe_allow_html=True)
            if c2.button("Verbinding testen", width="stretch"):
                ok, msg = store.github.check()
                (st.success if ok else st.error)(msg)
            pending = store.unsynced_files()
            if pending:
                w1, w2 = st.columns([3, 1])
                w1.warning(f"{len(pending)} bestand(en) staan alleen nog op de server (opgeslagen vóór de koppeling). "
                           "Stuur ze naar GitHub zodat ze bewaard blijven.")
                if w2.button("⬆️  Nu naar GitHub sturen", type="primary", width="stretch"):
                    with st.spinner("Bezig met uploaden naar GitHub..."):
                        rep = store.push_unsynced()
                    S.flash(f"{rep.total} bestand(en) op GitHub gezet ✓" if not rep.error
                            else f"Uploaden naar GitHub mislukt: {rep.error}", "success" if not rep.error else "error")
                    st.rerun()
            if status.get("source") == "website":
                with st.expander("📌  Token blijvend opslaan in Streamlit Secrets", expanded=True):
                    _save_step(status)
            return

        st.markdown(f"{badge('Opslag: alleen tijdelijk', 'warn')} &nbsp; Je data staat nu op de server, maar "
                    "verdwijnt als de online website herstart. Koppel GitHub om alles blijvend te bewaren.",
                    unsafe_allow_html=True)
        if status.get("secrets_error"):
            st.error("De **Secrets** in Streamlit bevatten een schrijffout, daardoor wordt het token niet gelezen. "
                     "Wis het tekstvak in Settings → Secrets en plak de tekst uit stap 3 opnieuw.  \n"
                     f"Technische melding: `{status['secrets_error'][:300]}`")
        elif status.get("configured") and not status.get("ok"):
            st.error(f"Er is een token gevonden in de Secrets, maar het werkt niet: {status['msg']}")
            if st.button("Opnieuw controleren"):
                S.reset_github()
                st.rerun()
        with st.expander("🔗  GitHub koppelen (±3 minuten)", expanded=bool(status.get("configured")
                                                                            or status.get("secrets_error"))):
            _connect_wizard(status)


def _library() -> None:
    store = S.store()
    df = store.datasets()
    if df.empty:
        st.info("De bibliotheek is nog leeg. Kies hierboven **Uploaden** of **Downloaden** om data toe te voegen.")
        return
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "Bars": st.column_config.NumberColumn(format="%d"),
        "Grootte (MB)": st.column_config.NumberColumn(format="%.2f")})
    labels = [f"{r.Asset} · {r.Timeframe}" for r in df.itertuples()]
    c1, c2 = st.columns([2, 1])
    pick = c1.selectbox("Dataset bekijken of verwijderen", range(len(labels)), format_func=lambda i: labels[i])
    row = df.iloc[pick]
    with c2:
        st.write("")
        confirm = st.checkbox("Ja, verwijderen", key="del_confirm")
        if st.button("🗑️  Verwijderen", disabled=not confirm, width="stretch"):
            rep = store.delete(row["Asset"], row["Timeframe"])
            msg = f"{row['Asset']} {row['Timeframe']} verwijderd."
            if rep.error:
                msg += f" (GitHub: {rep.error})"
            S.flash(msg, "warning" if rep.error else "success")
            st.session_state.pop("del_confirm", None)
            st.rerun()
    data = store.load(row["Asset"], row["Timeframe"])
    if data is not None and len(data):
        tv_chart(candles_payload(data, max_bars=2500), height=360, show_bars=300, key=f"lib_{pick}")


def _upload() -> None:
    st.markdown("Sleep je CSV-bestanden hierheen: **TradingView** (*Export chart data*), **MetaTrader 4/5** of "
                "crypto-exports. Asset en timeframe worden herkend uit de bestandsnaam (bv. `XAUUSD_M1.csv`, "
                "`BTCUSD_1D.csv`) of de data. Nieuwe data wordt **samengevoegd** met wat er al in de bibliotheek staat.")
    key = st.session_state.get("upload_key", 0)
    files = st.file_uploader("CSV-bestanden", type=["csv", "txt"], accept_multiple_files=True, key=f"up_{key}",
                             label_visibility="collapsed")
    if not files:
        return
    plan = []
    for f in files:
        try:
            df = parse_upload(f.getvalue(), f.name)
        except Exception as e:  # noqa: BLE001
            st.error(f"**{f.name}** kon niet gelezen worden: {e}")
            continue
        if df.empty:
            st.error(f"**{f.name}** bevat geen koersdata.")
            continue
        c1, c2, c3 = st.columns([2.2, 1, 1])
        c1.markdown(f"**{f.name}**  \n<span class='small-note'>{len(df):,} bars · {df.index[0]:%Y-%m-%d} → "
                    f"{df.index[-1]:%Y-%m-%d}</span>", unsafe_allow_html=True)
        sym_guess = symbol_from_name(f.name) or "XAUUSD"
        sym = c2.selectbox("Asset", SYMBOLS, index=SYMBOLS.index(sym_guess), key=f"sym_{key}_{f.name}")
        tf_guess = tf_from_name(f.name) or detect_tf(df)
        tf = c3.selectbox("Timeframe", TIMEFRAMES, index=TIMEFRAMES.index(tf_guess), key=f"tf_{key}_{f.name}")
        plan.append((f.name, sym, tf, df))
    if plan and st.button(f"💾  {len(plan)} bestand(en) opslaan in de bibliotheek", type="primary", width="stretch"):
        store = S.store()
        prog = st.progress(0.0)
        for i, (name, sym, tf, df) in enumerate(plan):
            prog.progress(i / len(plan), text=f"Opslaan: {name}")
            rep = store.save(sym, tf, df, message=f"Data: {sym} {tf} geüpload ({name})")
            msg = f"{sym} {tf}: {rep.added:,} nieuwe candles toegevoegd (totaal {rep.total:,})."
            if store.synced:
                msg += " Bewaard op GitHub ✓" if rep.synced else f" ⚠️ GitHub-sync mislukt: {rep.error}"
            S.flash(msg, "success" if not rep.error else "warning")
        prog.progress(1.0)
        st.session_state["upload_key"] = key + 1
        st.rerun()


PRESETS = {
    "Aanbevolen (1D sinds 2017 + 1H 2 jaar + 1m 6 maanden)": [("1D", 365 * 9), ("1H", 730), ("1m", 182)],
    "Snel (1D sinds 2017 + 1H 1 jaar)": [("1D", 365 * 9), ("1H", 365)],
}


def _download() -> None:
    st.markdown("**Bitcoin (BTCUSD)** kan direct gedownload worden van Binance (BTC/USDT), met Bitstamp (BTC/USD) "
                "als reserve. Geen account of API-key nodig.")
    mode = st.radio("Wat wil je downloaden?", ["Kant-en-klare set", "Zelf kiezen"], horizontal=True)
    jobs: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []
    now = pd.Timestamp.now(tz="UTC").floor("min")
    if mode == "Kant-en-klare set":
        preset = st.selectbox("Set", list(PRESETS))
        jobs = [(tf, now - pd.Timedelta(days=d), now) for tf, d in PRESETS[preset]]
        st.caption("1m-data voor 6 maanden is ±260.000 candles en duurt 1-3 minuten.")
    else:
        c1, c2, c3 = st.columns(3)
        tfs = c1.multiselect("Timeframes", ["1m", "5m", "15m", "1H", "4H", "1D"], default=["1D"])
        start = c2.date_input("Vanaf", value=(now - pd.Timedelta(days=365)).date())
        end = c3.date_input("Tot en met", value=now.date())
        jobs = [(tf, pd.Timestamp(start, tz="UTC"), min(now, pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)))
                for tf in tfs]
    if st.button("⬇️  Downloaden & opslaan", type="primary", width="stretch", disabled=not jobs):
        store = S.store()
        for tf, t0, t1 in jobs:
            bar = st.progress(0.0, text=f"BTCUSD {tf} downloaden...")
            try:
                df, src = download_btc(tf, t0, t1, progress=lambda p, m, b=bar, t=tf: b.progress(p, text=f"{t}: {m}"))
            except Exception as e:  # noqa: BLE001
                bar.empty()
                st.error(f"BTCUSD {tf}: {e}")
                continue
            bar.progress(1.0, text=f"{tf}: opslaan...")
            rep = store.save("BTCUSD", tf, df, message=f"Data: BTCUSD {tf} gedownload ({src})")
            msg = f"BTCUSD {tf} ({src}): {rep.added:,} nieuwe candles (totaal {rep.total:,})."
            if store.synced:
                msg += " Bewaard op GitHub ✓" if rep.synced else f" ⚠️ GitHub-sync mislukt: {rep.error}"
            S.flash(msg, "success" if not rep.error else "warning")
        st.rerun()
    st.divider()
    st.markdown("**Goud (XAUUSD)** – er is geen gratis bron die automatisch downloaden toestaat. Exporteer daarom uit:")
    st.markdown("- **MetaTrader 5**: *Beeld → Symbolen* (Ctrl+U) → *XAUUSD* → tab *Bars* → kies timeframe (M1 en D1) "
                "en periode → **Opvragen** → **Exporteren**.\n"
                "- **TradingView**: open XAUUSD → menu naast de chartnaam → **Export chart data…**\n\n"
                "Upload de bestanden daarna bij het tabblad **Uploaden**.")


def _demo() -> None:
    on = st.toggle("Demo-data gebruiken (nep, om de website te proberen)", value=S.demo_on())
    if on != S.demo_on():
        st.session_state["demo"] = on
        S.set_results(None) if on else st.session_state.pop("results", None)
        st.rerun()
    st.caption("Met demo-data aan gebruikt de hele website gesimuleerde koersen in plaats van je bibliotheek. "
               "Demo-resultaten worden niet opgeslagen.")


def render() -> None:
    st.markdown("## 📁 Data")
    S.show_flash()
    _storage_panel()
    sections = ["📚  Bibliotheek", "📤  Uploaden", "🌐  Downloaden", "🧪  Demo"]
    section = st.segmented_control("Onderdeel", sections, default=sections[0], key="data_section",
                                   label_visibility="collapsed") or sections[0]
    with st.container(key="panel_section"):
        if section == sections[0]:
            ptitle("Opgeslagen datasets")
            _library()
        elif section == sections[1]:
            ptitle("Bestanden uploaden")
            _upload()
        elif section == sections[2]:
            ptitle("Data downloaden")
            _download()
        else:
            ptitle("Demo-modus")
            _demo()
    html_block('<p class="small-note">Tip: voor de beste backtest heb je per asset <b>1-minuut data</b> (backtest-periode) '
               'én <b>1D-data met jaren historie</b> nodig (voor de Monthly/Weekly analyse).</p>')
