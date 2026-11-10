"""Data: bibliotheek (blijvend bewaard), uploaden, downloaden en GitHub-koppeling."""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from trading_tool.config import TIMEFRAMES, normalize_tf
from trading_tool.data_loader import detect_tf, read_ohlc_csv
from trading_tool.downloaders import CRYPTO, download_crypto

from .. import state as S
from ..charts import candles_payload, tv_chart

SYMBOLS = S.SYMBOLS


def tf_from_name(name: str) -> str | None:
    for part in reversed(re.split(r"[_\-\s,.]+", Path(name).stem)):
        try:
            return normalize_tf(part)
        except ValueError:
            continue
    return None


def clean_symbol(sym: str) -> str:
    s = re.sub(r"[^A-Z0-9]", "", str(sym or "").upper())
    return s[:20]


def symbol_from_name(name: str) -> str | None:
    up = Path(name).stem.upper()
    if "XAU" in up or "GOLD" in up:
        return "XAUUSD"
    if "BTC" in up or "XBT" in up:
        return "BTCUSD"
    first = re.split(r"[_\-\s,.]+", up)[0]
    first = re.sub(r"^(OANDA|FX|BINANCE|CAPITALCOM|PEPPERSTONE|ICMARKETS|FOREXCOM)[:_]?", "", first)
    cleaned = clean_symbol(first)
    return cleaned if len(cleaned) >= 3 and not cleaned.isdigit() else None


@st.cache_data(show_spinner=False, max_entries=16)
def parse_upload(data: bytes, name: str) -> pd.DataFrame:
    buf = io.BytesIO(data)
    buf.name = name
    return read_ohlc_csv(buf)


def _storage_note() -> None:
    if S.is_guest():
        st.info("Je bekijkt wng als gast. Wat je hier toevoegt, wordt niet bewaard.")
    elif not S.persistent() and not S.can_manage():
        st.warning("Deze installatie bewaart data nog niet blijvend. Neem contact op met de beheerder.")


def _library(store, editable: bool, key: str) -> None:
    df = store.datasets()
    if df.empty:
        st.info("Nog geen data. Kies hierboven **Uploaden** of **Downloaden**." if editable else
                "Er staat nog geen gedeelde data klaar.")
        return
    df = df.rename(columns={"Asset": "Markt"})
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "Bars": st.column_config.NumberColumn(format="%d"),
        "Grootte (MB)": st.column_config.NumberColumn(format="%.2f")})
    labels = [f"{r.Markt} · {r.Timeframe}" for r in df.itertuples()]
    c1, c2 = st.columns([2, 1])
    pick = c1.selectbox("Dataset bekijken" + (" of verwijderen" if editable else ""), range(len(labels)),
                        format_func=lambda i: labels[i], key=f"{key}_pick")
    row = df.iloc[pick]
    if editable:
        with c2:
            st.write("")
            confirm = st.checkbox("Ja, verwijderen", key=f"{key}_del_confirm")
            if st.button("Verwijderen", disabled=not confirm, width="stretch", key=f"{key}_del"):
                rep = store.delete(row["Markt"], row["Timeframe"])
                msg = f"{row['Markt']} {row['Timeframe']} verwijderd."
                if rep.error:
                    msg += f" (GitHub: {rep.error})"
                S.flash(msg, "warning" if rep.error else "success")
                st.session_state.pop(f"{key}_del_confirm", None)
                st.rerun()
    data = store.load(row["Markt"], row["Timeframe"])
    if data is not None and len(data):
        tv_chart(candles_payload(data, max_bars=2500), height=360, show_bars=300, key=f"{key}_{pick}")


def _target_store():
    """Eigen bibliotheek, of (alleen voor beheerders) de gedeelde bibliotheek."""
    if S.is_admin():
        where = st.radio("Opslaan in", ["Mijn data", "Gedeelde data (voor iedereen)"], horizontal=True, key="target_lib")
        if where.startswith("Gedeelde"):
            return S.shared_store(), "gedeelde bibliotheek"
    return S.store(), "jouw bibliotheek"


def _report(store, sym, tf, rep, where: str) -> None:
    msg = f"{sym} {tf}: {rep.added:,} nieuwe candles toegevoegd aan {where} (totaal {rep.total:,})."
    if store.synced:
        msg += " Blijvend bewaard." if rep.synced else f" Let op: blijvend opslaan mislukt ({rep.error})."
    S.flash(msg, "success" if not rep.error else "warning")


def _upload() -> None:
    st.markdown("Sleep je CSV-bestanden hierheen: **TradingView** (*Export chart data*), **MetaTrader 4/5** of "
                "crypto-exports – elke markt mag (forex, indices, aandelen, crypto, grondstoffen). Markt en timeframe "
                "worden herkend uit de bestandsnaam (bv. `EURUSD_M1.csv`, `XAUUSD_D1.csv`). Nieuwe data wordt "
                "**samengevoegd** met wat er al staat.")
    target, where = _target_store()
    key = st.session_state.get("upload_key", 0)
    files = st.file_uploader("CSV-bestanden", type=["csv", "txt"], accept_multiple_files=True, key=f"up_{key}",
                             label_visibility="collapsed")
    if not files:
        return
    known = sorted(set(SYMBOLS) | set(S.symbols()) | {"EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30", "SPX500",
                                                    "GER40", "ETHUSD", "XAGUSD", "USOIL"})
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
        guess = symbol_from_name(f.name) or "EURUSD"
        opts = known if guess in known else [guess, *known]
        sym = c2.selectbox("Markt", opts, index=opts.index(guess), key=f"sym_{key}_{f.name}", accept_new_options=True,
                           help="Kies of typ een eigen naam (bv. NAS100)")
        tf_guess = tf_from_name(f.name) or detect_tf(df)
        tf = c3.selectbox("Timeframe", TIMEFRAMES, index=TIMEFRAMES.index(tf_guess), key=f"tf_{key}_{f.name}")
        plan.append((f.name, clean_symbol(sym), tf, df))
    bad = [p for p in plan if len(p[1]) < 2]
    if bad:
        st.warning("Geef elke markt een naam van minstens 2 tekens.")
    if plan and not bad and st.button(f"{len(plan)} bestand(en) opslaan in {where}", type="primary", width="stretch"):
        prog = st.progress(0.0)
        for i, (name, sym, tf, df) in enumerate(plan):
            prog.progress(i / len(plan), text=f"Opslaan: {name}")
            rep = target.save(sym, tf, df, message=f"Data: {sym} {tf} geüpload ({name})")
            _report(target, sym, tf, rep, where)
        prog.progress(1.0)
        st.session_state["upload_key"] = key + 1
        st.rerun()


PRESETS = {
    "Aanbevolen (1D sinds 2017 + 1H 2 jaar + 1m 6 maanden)": [("1D", 365 * 9), ("1H", 730), ("1m", 182)],
    "Snel (1D sinds 2017 + 1H 1 jaar)": [("1D", 365 * 9), ("1H", 365)],
}


def _download() -> None:
    st.markdown("**Crypto** kan direct gedownload worden van Binance (…/USDT), met Bitstamp (…/USD) als reserve. "
                "Geen account of API-key nodig.")
    target, where = _target_store()
    base = st.selectbox("Munt", CRYPTO, format_func=lambda b: f"{b}USD", key="dl_base")
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
    if st.button("Downloaden en opslaan", type="primary", width="stretch", disabled=not jobs):
        sym = f"{base}USD"
        for tf, t0, t1 in jobs:
            bar = st.progress(0.0, text=f"{sym} {tf} downloaden...")
            try:
                df, src = download_crypto(base, tf, t0, t1,
                                          progress=lambda p, m, b=bar, t=tf: b.progress(p, text=f"{t}: {m}"))
            except Exception as e:  # noqa: BLE001
                bar.empty()
                st.error(f"{sym} {tf}: {e}")
                continue
            bar.progress(1.0, text=f"{tf}: opslaan...")
            rep = target.save(sym, tf, df, message=f"Data: {sym} {tf} gedownload ({src})")
            _report(target, sym, tf, rep, where)
        st.rerun()
    st.divider()
    st.markdown("**Forex, goud, indices en aandelen** – daarvoor is geen gratis bron die automatisch downloaden toestaat. "
                "Exporteer uit je eigen platform:")
    st.markdown("- **MetaTrader 5**: *Beeld → Symbolen* (Ctrl+U) → kies je markt → tab *Bars* → kies timeframe (M1 en D1) "
                "en periode → **Opvragen** → **Exporteren**.\n"
                "- **TradingView**: open je markt → menu naast de chartnaam → **Export chart data…**\n\n"
                "Upload de bestanden daarna bij het tabblad **Uploaden**.")


def _demo() -> None:
    on = st.toggle("Demo-data gebruiken (nep, om de website te proberen)", value=S.demo_on())
    if on != S.demo_on():
        st.session_state["demo"] = on
        st.session_state.pop("results", None)
        st.rerun()
    st.caption("Met demo-data aan gebruikt de hele website gesimuleerde koersen in plaats van je bibliotheek. "
               "Demo-resultaten worden niet opgeslagen.")


def render() -> None:
    S.show_flash()
    _storage_note()
    tabs = st.tabs(["Mijn data", "Gedeelde data", "Uploaden", "Downloaden", "Demo"], key="data_tabs",
                   on_change="rerun")
    if tabs[0].open:
        with tabs[0]:
            _library(S.store(), editable=True, key="own")
    if tabs[1].open:
        with tabs[1]:
            st.caption("Koersdata die de beheerder voor iedereen klaarzet. Heb je zelf dezelfde markt en timeframe, "
                       "dan gaat jouw eigen data voor.")
            _library(S.shared_store(), editable=S.is_admin(), key="shared")
    if tabs[2].open:
        with tabs[2]:
            _upload()
    if tabs[3].open:
        with tabs[3]:
            _download()
    if tabs[4].open:
        with tabs[4]:
            _demo()
