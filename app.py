"""AI Trading Tool - website (Streamlit).

Lokaal starten:   streamlit run app.py
Online zetten:    share.streamlit.io -> koppel GitHub-repo -> main file: app.py
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from trading_tool.backtester import Backtester
from trading_tool.config import (CONFIRMATION_TF, DEFAULT_COSTS, TF_MINUTES, TIMEFRAMES, CostConfig,
                                 RiskConfig, StrategyConfig, normalize_tf)
from trading_tool.data_loader import (build_multi_timeframe, detect_tf, discover_files,
                                      read_ohlc_csv, resample_ohlc)
from trading_tool.metrics import breakdown_by, combined_equity, compute_metrics, format_report
from trading_tool.synthetic import demo_dataset

# --------------------------------------------------------------------------- #
# Opmaak
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="AI Trading Tool", page_icon="📈", layout="wide",
                   initial_sidebar_state="expanded")

SYMBOLS = ["BTCUSD", "XAUUSD"]
COLORS = {"BTCUSD": "#2a78d6", "XAUUSD": "#eb6834", "TOTAAL": "#52514e"}
GOOD, BAD, NEUTRAL = "#0ca30c", "#d03b3b", "#8a8984"
DATA_DIR = Path(__file__).parent / "data"
GITHUB_URL = "https://github.com/mw180708-create/ai_trading_tool"

st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1400px;}
  div[data-testid="stMetric"] {
      background: var(--secondary-background-color);
      border-radius: 12px; padding: 14px 18px;
      border: 1px solid rgba(128,128,128,0.15);
  }
  div[data-testid="stMetricLabel"] p {font-size: 0.85rem; opacity: 0.8;}
  .step {font-size: 0.8rem; font-weight: 600; letter-spacing: .06em; opacity: .6; text-transform: uppercase;}
  .hint {opacity: .75; font-size: .92rem;}
</style>
""", unsafe_allow_html=True)


def base_layout(fig: go.Figure, height: int = 380, title: str | None = None) -> go.Figure:
    fig.update_layout(
        template="plotly_white", height=height, margin=dict(l=10, r=10, t=50 if title else 20, b=10),
        title=dict(text=title, x=0, font=dict(size=15)) if title else None,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
    )
    fig.update_xaxes(showgrid=False, linecolor="rgba(128,128,128,.3)")
    fig.update_yaxes(gridcolor="rgba(128,128,128,.15)", zeroline=False)
    return fig


def money(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}" if abs(v) >= 100 else f"{sign}${abs(v):,.2f}"


# --------------------------------------------------------------------------- #
# Data helpers
# --------------------------------------------------------------------------- #
_TF_IN_NAME = re.compile(r"[_\-\s,]([A-Za-z0-9]+)(?:\.csv)?$", re.I)


def tf_from_filename(name: str) -> str | None:
    stem = Path(name).stem
    for part in reversed(re.split(r"[_\-\s,]+", stem)):
        try:
            return normalize_tf(part)
        except ValueError:
            continue
    return None


def symbol_from_filename(name: str) -> str | None:
    up = Path(name).stem.upper()
    if "XAU" in up or "GOLD" in up:
        return "XAUUSD"
    if "BTC" in up or "XBT" in up:
        return "BTCUSD"
    return None


@st.cache_data(show_spinner=False, max_entries=20)
def parse_upload(data: bytes, name: str) -> pd.DataFrame:
    buf = io.BytesIO(data)
    buf.name = name
    return read_ohlc_csv(buf)


@st.cache_data(show_spinner=False)
def load_repo_file(path: str, mtime: float) -> pd.DataFrame:
    return read_ohlc_csv(path)


@st.cache_resource(show_spinner=False)
def cached_demo(symbol: str, seed: int):
    return demo_dataset(symbol, seed)


def run_backtests(datasets, strategy, risk, use_costs, start):
    results = []
    progress = st.progress(0.0, text="Backtest starten...")
    for n, mtf in enumerate(datasets):
        progress.progress(n / len(datasets), text=f"Backtest {mtf.symbol} draait...")
        costs = DEFAULT_COSTS.get(mtf.symbol, CostConfig()) if use_costs else CostConfig()
        st_start = pd.Timestamp(start, tz="UTC") if start else getattr(mtf, "backtest_start", None)
        results.append(Backtester(mtf, strategy, RiskConfig(**vars(risk)), costs, start=st_start,
                                  verbose=False).run())
    progress.progress(1.0, text="Klaar!")
    return results


# --------------------------------------------------------------------------- #
# Sidebar: instellingen
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("## ⚙️ Instellingen")
    st.caption("Standaard staan alle regels van het Trading Plan 2026-2028 goed. "
               "Je hoeft hier niets te veranderen.")

    st.markdown("**Account & risico**")
    balance = st.number_input("Startbalans per account ($)", 1_000, 10_000_000, 100_000, step=5_000)
    risk_pct = st.number_input("Risico per trade (%)", 0.1, 5.0, 1.0, step=0.1)

    st.markdown("**Entry-filter**")
    min_rr = st.slider("Minimale Risk-to-Reward", 1.0, 10.0, 2.0, 0.5)
    adaptive = st.toggle("Dynamische RR-eis (op basis van winrate)", value=True,
                         help="Na 20 trades verhoogt de tool de minimale RR als de winrate dat vereist.")

    with st.expander("Geavanceerd"):
        confirmation = st.radio("Confirmation op lagere timeframe",
                                ["bos", "first_candle"],
                                format_func=lambda x: {"bos": "Balance shift / BOS",
                                                       "first_candle": "Eerste candle in bias-richting"}[x])
        tp_source = st.radio("Take Profit", ["poi_tf", "poi_tf_and_higher"],
                             format_func=lambda x: {"poi_tf": "Eerstvolgende liquiditeit op POI-timeframe",
                                                    "poi_tf_and_higher": "Dichtstbijzijnde liquiditeit (POI-TF of hoger)"}[x])
        liq_mode = st.radio("Liquiditeit-definitie", ["draw", "sweep"],
                            format_func=lambda x: {"draw": "Sweeps + BOS (draw on liquidity)",
                                                   "sweep": "Alleen sweeps (strenger)"}[x])
        be_swing = st.number_input("Break-even Swing (R)", 0.5, 20.0, 2.0, 0.5)
        be_intra = st.number_input("Break-even Intraday/Scalp (R)", 0.5, 20.0, 4.0, 0.5)
        use_costs = st.toggle("Spread & commissie meenemen", value=True)
        start_date = st.date_input("Start backtest (optioneel)", value=None,
                                   help="Data vóór deze datum wordt alleen als warm-up gebruikt.")

    st.divider()
    st.markdown(f"[📂 Code op GitHub]({GITHUB_URL})")

strategy = StrategyConfig(min_rr=min_rr, adaptive_rr=adaptive, confirmation_mode=confirmation,
                          tp_source=tp_source, liquidity_mode=liq_mode,
                          be_trigger_rr_swing=be_swing, be_trigger_rr_intraday=be_intra)
risk = RiskConfig(initial_balance=float(balance), risk_per_trade=risk_pct / 100)

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.markdown("# 📈 AI Trading Tool")
st.markdown('<p class="hint">Backtest van het Trading Plan 2026-2028 op <b>BTCUSD</b> en <b>XAUUSD</b> — '
            "Bias → POI → Confirmation → Entry → Break-even / TP / SL.</p>", unsafe_allow_html=True)

tab_data, tab_res, tab_chart, tab_trades, tab_info = st.tabs(
    ["① Data & start", "② Resultaten", "③ Grafiek", "④ Alle trades", "ℹ️ Uitleg"])

# --------------------------------------------------------------------------- #
# Tab 1: Data
# --------------------------------------------------------------------------- #
with tab_data:
    st.markdown('<div class="step">Stap 1 — Kies je data</div>', unsafe_allow_html=True)
    source = st.radio("Waar komt de data vandaan?",
                      ["📤 Zelf uploaden", "📂 Uit GitHub (map data/)", "🧪 Demo-data (om te testen)"],
                      horizontal=True, label_visibility="collapsed")

    sources: dict[str, dict[str, pd.DataFrame]] = {}
    demo_mode = source.startswith("🧪")

    if source.startswith("📤"):
        st.markdown('<p class="hint">Sleep je CSV-bestanden hierheen (TradingView, MetaTrader 4/5 of crypto-export). '
                    "Gebruik bij voorkeur 1-minuut data voor de backtest én een 1D-bestand met jaren historie "
                    "voor de Monthly/Weekly analyse. De timeframe wordt automatisch herkend.</p>",
                    unsafe_allow_html=True)
        cols = st.columns(2)
        for col, sym in zip(cols, SYMBOLS):
            with col:
                files = st.file_uploader(f"**{sym}** bestanden", type=["csv", "txt"],
                                         accept_multiple_files=True, key=f"up_{sym}")
                rows = []
                for f in files or []:
                    try:
                        df = parse_upload(f.getvalue(), f.name)
                    except Exception as e:  # noqa: BLE001
                        st.error(f"{f.name}: kon niet gelezen worden ({e})")
                        continue
                    tf_guess = tf_from_filename(f.name) or detect_tf(df)
                    tf = st.selectbox(f"Timeframe van {f.name}", TIMEFRAMES,
                                      index=TIMEFRAMES.index(tf_guess), key=f"tf_{sym}_{f.name}")
                    sources.setdefault(sym, {})[tf] = df
                    rows.append({"Bestand": f.name, "TF": tf, "Bars": len(df),
                                 "Van": df.index[0].date(), "Tot": df.index[-1].date()})
                if rows:
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    elif source.startswith("📂"):
        found = discover_files(DATA_DIR) if DATA_DIR.exists() else {}
        if not found:
            st.info(f"Er staan nog geen CSV-bestanden in de map **data/** van je GitHub-repository.\n\n"
                    f"Zo voeg je ze toe: open [je repository]({GITHUB_URL}/tree/main/data) → **Add file** → "
                    f"**Upload files** → sleep je CSV's erin (naam bv. `XAUUSD_1D.csv`, `BTCUSD_1m.csv`) → "
                    f"**Commit changes**. De website ververst daarna automatisch.")
        rows = []
        for sym, files in found.items():
            if sym not in SYMBOLS:
                continue
            for tf, path in files.items():
                df = load_repo_file(str(path), path.stat().st_mtime)
                sources.setdefault(sym, {})[tf] = df
                rows.append({"Asset": sym, "Bestand": path.name, "TF": tf, "Bars": len(df),
                             "Van": df.index[0].date(), "Tot": df.index[-1].date()})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("🧪 Demo-data is **nep** (gesimuleerde koersen). Handig om te zien hoe de website werkt, "
                "maar de resultaten zeggen niets over de echte markt.")

    # ---------- overzicht + start ----------
    st.divider()
    st.markdown('<div class="step">Stap 2 — Start de backtest</div>', unsafe_allow_html=True)

    datasets = []
    try:
        if demo_mode:
            datasets = [cached_demo(s, i) for i, s in enumerate(SYMBOLS)]
        else:
            datasets = [build_multi_timeframe(s, src) for s, src in sources.items() if src]
    except Exception as e:  # noqa: BLE001
        st.error(f"Data kon niet worden voorbereid: {e}")

    if datasets:
        cols = st.columns(len(datasets))
        for col, mtf in zip(cols, datasets):
            with col:
                st.markdown(f"**{mtf.symbol}** · executie op **{mtf.base_tf}**")
                cover = pd.DataFrame([{"Timeframe": tf, "Bars": len(mtf[tf]),
                                       "Van": mtf[tf].index[0].date(), "Tot": mtf[tf].index[-1].date()}
                                      for tf in TIMEFRAMES if tf in mtf])
                st.dataframe(cover, hide_index=True, width="stretch", height=180)
                missing = [c for p, c in CONFIRMATION_TF.items() if c not in mtf and p in mtf]
                if missing:
                    st.caption(f"⚠️ Geen {', '.join(sorted(set(missing), key=lambda t: -TF_MINUTES[t]))} data: "
                               f"confirmatie gebeurt dan op {mtf.base_tf}.")
                if len(mtf["1M"]) < 12 if "1M" in mtf else True:
                    st.caption("⚠️ Minder dan 12 maanden historie: Monthly-analyse is beperkt. "
                               "Voeg een 1D-bestand met meer historie toe.")

        if st.button("▶️  Start backtest", type="primary", width="stretch"):
            try:
                st.session_state["results"] = run_backtests(datasets, strategy, risk, use_costs, start_date)
                st.session_state["datasets"] = {m.symbol: m for m in datasets}
                st.session_state["demo"] = demo_mode
                st.success("✅ Backtest klaar! Open het tabblad **② Resultaten** hierboven.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Er ging iets mis tijdens de backtest: {e}")
    else:
        st.caption("Voeg eerst data toe (of kies demo-data) om de backtest te kunnen starten.")

results = st.session_state.get("results")
mtfs = st.session_state.get("datasets", {})


def need_results() -> bool:
    if not results:
        st.info("👈 Nog geen resultaten. Ga naar **① Data & start** en klik op **Start backtest**.")
        return False
    if st.session_state.get("demo"):
        st.warning("Dit zijn resultaten op **demo-data** (nep). Upload echte data voor echte resultaten.")
    return True


# --------------------------------------------------------------------------- #
# Tab 2: Resultaten
# --------------------------------------------------------------------------- #
with tab_res:
    if need_results():
        names = [r.symbol for r in results] + (["TOTAAL"] if len(results) > 1 else [])
        pick = st.segmented_control("Bekijk", names, default=names[-1], key="res_pick") or names[-1]
        if pick == "TOTAAL":
            trades = pd.concat([r.trades for r in results if not r.trades.empty], ignore_index=True) \
                if any(not r.trades.empty for r in results) else pd.DataFrame()
            equity = combined_equity(results)
            initial = sum(r.initial_balance for r in results)
        else:
            r = next(r for r in results if r.symbol == pick)
            trades, equity, initial = r.trades, r.equity, r.initial_balance
        m = compute_metrics(trades, equity, initial)

        if m["Trades"] == 0:
            st.warning("Geen trades gevonden met deze data en instellingen. Tip: voeg meer historie toe "
                       "(1D-bestand met meerdere jaren) of verlaag de minimale RR.")
        else:
            c = st.columns(3)
            c[0].metric("Net Profit", money(m["Net Profit"]), f"{m['Net Profit %']:+.1f}%")
            c[1].metric("Winrate", f"{m['Winrate %']:.1f}%")
            pf = m["Profit Factor"]
            c[2].metric("Profit Factor", "∞" if np.isinf(pf) else f"{pf:.2f}")
            c = st.columns(3)
            c[0].metric("Max Drawdown", f"{m['Max DD %']:.1f}%")
            c[1].metric("Aantal trades", f"{m['Trades']}")
            c[2].metric("Gem. Risk-to-Reward", f"{m['Avg planned RR']:.2f}",
                        f"{m['Avg R/trade']:+.2f} R gemiddeld per trade")
            st.caption(f"Trades: **{m['Swing']}** Swing · **{m['Intraday']}** Intraday · **{m['Scalp']}** Scalp "
                       f"— Break-even exits: {m['Break-even %']:.0f}% · Totaal {m['Total R']:+.1f} R")

            # Equity curve
            fig = go.Figure()
            curves = [(r.symbol, r.equity) for r in results] if pick == "TOTAAL" else [(pick, equity)]
            if pick == "TOTAAL" and len(results) > 1:
                curves.append(("TOTAAL", equity))
            for name, eq in curves:
                base_val = eq.iloc[0] if len(eq) else 1.0
                pct = (eq / base_val - 1) * 100
                fig.add_trace(go.Scatter(x=eq.index, y=pct.values, name=name, mode="lines",
                                         customdata=eq.values,
                                         line=dict(color=COLORS.get(name, COLORS["TOTAAL"]), width=2, shape="hv"),
                                         hovertemplate="%{y:+.1f}% (%{customdata:$,.0f})<extra>" + name + "</extra>"))
            fig.add_hline(y=0, line=dict(color="rgba(128,128,128,.5)", width=1))
            fig.update_yaxes(ticksuffix="%")
            st.plotly_chart(base_layout(fig, 360, "Equity curve — rendement % (na elke gesloten trade)"),
                            width="stretch")

            left, right = st.columns(2)
            with left:
                rr = trades.sort_values("exit_time").reset_index(drop=True)
                colors = np.where(rr["r_multiple"] > 0.05, GOOD, np.where(rr["r_multiple"] < -0.05, BAD, NEUTRAL))
                fig = go.Figure(go.Bar(
                    x=rr.index + 1, y=rr["r_multiple"], marker=dict(color=colors, cornerradius=3),
                    customdata=np.stack([rr["symbol"], rr["trade_type"], rr["exit_reason"]], axis=1),
                    hovertemplate="Trade %{x}<br>%{y:+.2f} R<br>%{customdata[0]} · %{customdata[1]} · "
                                  "%{customdata[2]}<extra></extra>"))
                fig.update_layout(hovermode="closest", bargap=0.6 if len(rr) < 15 else 0.25)
                fig.update_xaxes(title="Trade #")
                fig.update_yaxes(title="Resultaat (R)")
                st.plotly_chart(base_layout(fig, 320, "Resultaat per trade (R)"), width="stretch")
            with right:
                ex = trades["exit_reason"].value_counts().reindex(["TP", "BE", "SL", "EOD"]).dropna()
                labels = {"TP": "Take Profit", "BE": "Break-even", "SL": "Stop Loss", "EOD": "Einde data"}
                fig = go.Figure(go.Bar(
                    y=[labels[k] for k in ex.index], x=ex.values, orientation="h",
                    marker=dict(color=[{"TP": GOOD, "BE": NEUTRAL, "SL": BAD, "EOD": NEUTRAL}[k] for k in ex.index],
                                cornerradius=3),
                    text=ex.values, textposition="outside",
                    hovertemplate="%{y}: %{x} trades<extra></extra>"))
                fig.update_layout(hovermode="closest", bargap=0.45)
                fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
                st.plotly_chart(base_layout(fig, 320, "Hoe zijn trades gesloten?"), width="stretch")

            st.markdown("#### Per trade type")
            st.caption("Swing = Monthly/Weekly POI · Intraday = Daily/4H/1H POI · Scalp = alleen 1D+4H+1H match")
            bt = breakdown_by(trades, "trade_type").reset_index().rename(
                columns={"symbol": "Asset", "trade_type": "Type"})
            st.dataframe(bt, hide_index=True, width="stretch", column_config={
                "Winrate %": st.column_config.NumberColumn(format="%.1f%%"),
                "Avg R": st.column_config.NumberColumn("Gem. R", format="%.2f"),
                "Total R": st.column_config.NumberColumn("Totaal R", format="%.2f"),
                "Net Profit": st.column_config.NumberColumn(format="dollar")})

            st.markdown("#### Per POI timeframe")
            bp = breakdown_by(trades, "poi_tf").reset_index().rename(columns={"symbol": "Asset", "poi_tf": "POI"})
            st.dataframe(bp, hide_index=True, width="stretch", column_config={
                "Winrate %": st.column_config.NumberColumn(format="%.1f%%"),
                "Avg R": st.column_config.NumberColumn("Gem. R", format="%.2f"),
                "Total R": st.column_config.NumberColumn("Totaal R", format="%.2f"),
                "Net Profit": st.column_config.NumberColumn(format="dollar")})

        # vergelijkingstabel
        st.markdown("#### BTCUSD vs XAUUSD")
        rows = {r.symbol: compute_metrics(r.trades, r.equity, r.initial_balance) for r in results}
        if len(results) > 1:
            all_t = pd.concat([r.trades for r in results if not r.trades.empty], ignore_index=True) \
                if any(not r.trades.empty for r in results) else pd.DataFrame()
            rows["TOTAAL"] = compute_metrics(all_t, combined_equity(results),
                                             sum(r.initial_balance for r in results))
        comp = pd.DataFrame(rows)
        comp_fmt = format_report(comp, money_rows=("Net Profit",))
        comp_fmt.index = [{"Avg planned RR": "Gem. geplande RR", "Avg win R": "Gem. winst (R)",
                           "Avg R/trade": "Gem. R per trade", "Total R": "Totaal R",
                           "Max DD %": "Max Drawdown %"}.get(i, i) for i in comp_fmt.index]
        st.dataframe(comp_fmt, width="stretch")

        with st.expander("Filter-statistieken (waarom signalen zijn overgeslagen)"):
            st.dataframe(pd.DataFrame({r.symbol: {
                "Confirmaties gevonden": r.stats.get("signals", 0),
                "Overgeslagen: RR te laag": r.stats.get("skip_rr", 0),
                "Overgeslagen: geen TP-liquiditeit": r.stats.get("skip_no_tp", 0),
                "Overgeslagen: ongeldige SL": r.stats.get("skip_sl", 0)} for r in results}), width="stretch")

# --------------------------------------------------------------------------- #
# Tab 3: Grafiek
# --------------------------------------------------------------------------- #
CANDLE_UP, CANDLE_DOWN = "#1baf7a", "#e34948"


def candle_fig(df: pd.DataFrame, title: str, height: int = 520) -> go.Figure:
    fig = go.Figure(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="Koers",
        increasing=dict(line=dict(color=CANDLE_UP, width=1), fillcolor=CANDLE_UP),
        decreasing=dict(line=dict(color=CANDLE_DOWN, width=1), fillcolor=CANDLE_DOWN)))
    fig = base_layout(fig, height, title)
    fig.update_layout(xaxis_rangeslider_visible=False, hovermode="x")
    return fig


with tab_chart:
    if need_results():
        c1, c2 = st.columns([1, 1])
        sym = c1.segmented_control("Asset", list(mtfs), default=list(mtfs)[0], key="ch_sym") or list(mtfs)[0]
        mtf = mtfs[sym]
        tfs = [t for t in ["1W", "1D", "4H", "1H", "15m"] if t in mtf]
        tf = c2.segmented_control("Timeframe", tfs, default="1D" if "1D" in tfs else tfs[0], key="ch_tf") or tfs[0]
        res = next(r for r in results if r.symbol == sym)
        df = mtf[tf]
        if not res.trades.empty:
            t0 = res.trades["entry_time"].min() - pd.Timedelta(minutes=TF_MINUTES[tf] * 100)
            df = df[df.index >= t0]
        df = df.iloc[-4000:]
        fig = candle_fig(df, f"{sym} · {tf} met alle trades")
        t = res.trades
        if not t.empty:
            for d, sym_marker, color, name in [("LONG", "triangle-up", GOOD, "Long entry"),
                                               ("SHORT", "triangle-down", BAD, "Short entry")]:
                s = t[t.direction == d]
                if len(s):
                    fig.add_trace(go.Scatter(
                        x=s.entry_time, y=s.entry, mode="markers", name=name,
                        marker=dict(symbol=sym_marker, size=12, color=color, line=dict(color="white", width=2)),
                        customdata=np.stack([s.trade_type, s.poi_tf, s.r_multiple], axis=1),
                        hovertemplate="%{customdata[0]} (%{customdata[1]} POI)<br>Entry %{y:,.2f}<br>"
                                      "Resultaat %{customdata[2]:+.2f} R<extra>" + name + "</extra>"))
            fig.add_trace(go.Scatter(
                x=t.exit_time, y=t.exit, mode="markers", name="Exit",
                marker=dict(symbol="x", size=9, color="#52514e", line=dict(width=1)),
                customdata=t.exit_reason, hovertemplate="Exit (%{customdata}) %{y:,.2f}<extra></extra>"))
        st.plotly_chart(fig, width="stretch")
        st.caption("▲ long entry · ▼ short entry · ✕ exit. Zoom in door een gebied te selecteren, dubbelklik om terug te gaan.")

        if not t.empty:
            st.markdown("#### 🔍 Trade in detail")
            labels = [f"#{i + 1} · {row.entry_time:%d-%m-%Y %H:%M} · {row.direction} · {row.trade_type} · "
                      f"{row.r_multiple:+.2f} R ({row.exit_reason})" for i, row in t.iterrows()]
            choice = st.selectbox("Kies een trade", range(len(t)), format_func=lambda i: labels[i])
            row = t.iloc[choice]
            dur = row.exit_time - row.entry_time
            ztf = next((z for z in ["1m", "5m", "15m", "1H", "4H", "1D"]
                        if z in mtf and (dur + pd.Timedelta(minutes=TF_MINUTES[z] * 60)) / pd.Timedelta(minutes=TF_MINUTES[z]) <= 400),
                       "1D" if "1D" in mtf else mtf.base_tf)
            pad = pd.Timedelta(minutes=TF_MINUTES[ztf] * 60)
            zdf = mtf[ztf]
            zdf = zdf[(zdf.index >= row.entry_time - pad) & (zdf.index <= row.exit_time + pad / 2)]
            zfig = candle_fig(zdf, f"Trade #{choice + 1} op {ztf}", 480)
            x0, x1 = zdf.index[0], zdf.index[-1]
            zfig.add_shape(type="rect", x0=x0, x1=row.entry_time, y0=row.poi_bottom, y1=row.poi_top,
                           fillcolor="rgba(42,120,214,.12)", line=dict(width=0), layer="below")
            zfig.add_annotation(x=x0, y=row.poi_top, text=f"{row.poi_tf} POI", showarrow=False,
                                xanchor="left", yanchor="bottom", font=dict(size=11, color="#2a78d6"))
            for y, label, color, dash in [(row.entry, "Entry", "#52514e", "solid"),
                                          (row.stop_loss, "Stop Loss", BAD, "dash"),
                                          (row.take_profit, "Take Profit", GOOD, "dash")]:
                zfig.add_shape(type="line", x0=row.entry_time, x1=row.exit_time, y0=y, y1=y,
                               line=dict(color=color, width=2, dash=dash))
                zfig.add_annotation(x=row.exit_time, y=y, text=f"{label} {y:,.2f}", showarrow=False,
                                    xanchor="left", font=dict(size=11, color=color))
            zfig.add_trace(go.Scatter(x=[row.entry_time, row.exit_time], y=[row.entry, row.exit],
                                      mode="markers", name="Entry / Exit",
                                      marker=dict(size=11, color=["#52514e", GOOD if row.r_multiple > 0 else BAD],
                                                  symbol=["circle", "x"], line=dict(color="white", width=2)),
                                      hovertemplate="%{y:,.2f}<extra></extra>"))
            zfig.update_yaxes(range=[min(zdf.low.min(), row.stop_loss, row.poi_bottom) * 0.999,
                                     max(zdf.high.max(), row.take_profit) * 1.001])
            st.plotly_chart(zfig, width="stretch")
            k = st.columns(3)
            k[0].metric("Resultaat", f"{row.r_multiple:+.2f} R", money(row.pnl))
            k[1].metric("Geplande RR", f"{row.planned_rr:.2f}")
            k[2].metric("Break-even geraakt", "Ja" if row.be_moved else "Nee")
            st.markdown(f"**Bias-match:** {row.bias_combo} &nbsp;·&nbsp; **POI → confirmatie:** "
                        f"{row.poi_tf} → {row.confirmation_tf} &nbsp;·&nbsp; **Type:** {row.trade_type} "
                        f"&nbsp;·&nbsp; **Exit:** {row.exit_reason} op {row.exit:,.2f}")

# --------------------------------------------------------------------------- #
# Tab 4: Alle trades
# --------------------------------------------------------------------------- #
with tab_trades:
    if need_results():
        all_t = pd.concat([r.trades for r in results if not r.trades.empty], ignore_index=True) \
            if any(not r.trades.empty for r in results) else pd.DataFrame()
        if all_t.empty:
            st.info("Geen trades.")
        else:
            f1, f2, f3 = st.columns(3)
            fs = f1.multiselect("Asset", sorted(all_t.symbol.unique()), default=sorted(all_t.symbol.unique()))
            ft = f2.multiselect("Type", sorted(all_t.trade_type.unique()), default=sorted(all_t.trade_type.unique()))
            fe = f3.multiselect("Exit", sorted(all_t.exit_reason.unique()), default=sorted(all_t.exit_reason.unique()))
            view = all_t[all_t.symbol.isin(fs) & all_t.trade_type.isin(ft) & all_t.exit_reason.isin(fe)]
            view = view.sort_values("entry_time").reset_index(drop=True)
            view.insert(0, "#", range(1, len(view) + 1))
            show = view[["#", "symbol", "direction", "trade_type", "poi_tf", "confirmation_tf", "entry_time", "entry",
                         "stop_loss", "take_profit", "planned_rr", "exit_time", "exit", "exit_reason",
                         "r_multiple", "pnl", "equity"]]
            st.dataframe(show, width="stretch", height=520, hide_index=True, column_config={
                "symbol": "Asset", "direction": "Richting", "trade_type": "Type", "poi_tf": "POI",
                "confirmation_tf": "Confirm.",
                "entry_time": st.column_config.DatetimeColumn("Entry tijd", format="DD-MM-YYYY HH:mm"),
                "exit_time": st.column_config.DatetimeColumn("Exit tijd", format="DD-MM-YYYY HH:mm"),
                "entry": st.column_config.NumberColumn("Entry", format="%.2f"),
                "stop_loss": st.column_config.NumberColumn("SL", format="%.2f"),
                "take_profit": st.column_config.NumberColumn("TP", format="%.2f"),
                "exit": st.column_config.NumberColumn("Exit", format="%.2f"),
                "planned_rr": st.column_config.NumberColumn("RR", format="%.2f"),
                "exit_reason": "Reden",
                "r_multiple": st.column_config.NumberColumn("R", format="%+.2f"),
                "pnl": st.column_config.NumberColumn("P&L", format="dollar"),
                "equity": st.column_config.NumberColumn("Balans", format="dollar"),
            })
            st.caption(f"{len(view)} trades getoond.")
            d1, d2 = st.columns(2)
            d1.download_button("⬇️ Download trades (CSV, voor Excel)", view.to_csv(index=False).encode(),
                               "trades.csv", "text/csv", width="stretch")
            summ = pd.DataFrame({r.symbol: compute_metrics(r.trades, r.equity, r.initial_balance) for r in results})
            d2.download_button("⬇️ Download samenvatting (CSV)", summ.to_csv().encode(), "samenvatting.csv",
                               "text/csv", width="stretch")

# --------------------------------------------------------------------------- #
# Tab 5: Uitleg
# --------------------------------------------------------------------------- #
with tab_info:
    st.markdown(f"""
### Hoe gebruik ik de website?
1. **① Data & start** — upload je CSV's (of kies demo-data) en klik op **Start backtest**.
2. **② Resultaten** — winst, winrate, drawdown, profit factor en de equity curve.
3. **③ Grafiek** — de koersgrafiek met alle entries/exits, en elke trade in detail (POI, entry, SL, TP).
4. **④ Alle trades** — de volledige tradelijst, te filteren en te downloaden voor Excel.

### Waar haal ik data vandaan?
- **TradingView**: open de chart → menu naast de chartnaam → *Export chart data…*
- **MetaTrader 5**: *Tools → History Center* (of rechtsklik in Market Watch) → kies symbool en timeframe → *Export*.
- Tip: gebruik **1-minuut data** voor de backtest + een **1D-bestand met jaren historie** (voor Monthly/Weekly).
- Naamgeving: `XAUUSD_1D.csv`, `BTCUSD_1m.csv` (**1M** = maand, **1m** = minuut).
- Vaste data bewaren? Zet de bestanden in de map [`data/` op GitHub]({GITHUB_URL}/tree/main/data)
  en kies bij stap 1 **Uit GitHub**.

### De regels van het Trading Plan
| Stap | Regel |
|---|---|
| **1. Bias** | Match nodig op 1M+1W+1D, 1W+1D+4H, 1M+1D+1H of 1D+4H+1H (alleen Scalp). Liquiditeit en balance level moeten dezelfde kant op wijzen, anders 50/50 → geen trade. |
| **2. POI** | Alleen POI's in de bias-richting op 1M/1W/1D/4H/1H: zone tussen de liquiditeit (wick) en de protected zone (body). |
| **3. Entry** | POI-in-POI: Monthly → 4H, Weekly → 1H, Daily → 15m, 4H → 5m, 1H → 1m balance shift. SL op het dichtstbijzijnde 1H protected level, TP op de eerstvolgende liquiditeit. Alleen als de RR hoog genoeg is. |
| **4. Management** | Swing (M/W POI): break-even bij 2R. Intraday & Scalp (D/4H/1H POI): break-even bij 4R. Geen partials. |
| **Risico** | Exact 1% per trade, max. 1 open trade per account. |

> Een backtest is geen garantie voor toekomstige resultaten.
""")
