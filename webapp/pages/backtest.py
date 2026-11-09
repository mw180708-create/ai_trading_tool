"""Backtest: instellingen kiezen en draaien op de data uit de bibliotheek."""
from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from trading_tool.backtester import Backtester
from trading_tool.config import CONFIRMATION_TF, DEFAULT_COSTS, TF_MINUTES, TIMEFRAMES, CostConfig, RiskConfig, StrategyConfig
from trading_tool.data_loader import build_multi_timeframe

from .. import nav
from .. import state as S
from ..theme import badge, html_block, ptitle


def _coverage(symbol: str) -> pd.DataFrame | None:
    m = S.mtf(symbol)
    if m is None:
        return None
    return pd.DataFrame([{"TF": tf, "Bars": len(m[tf]), "Van": m[tf].index[0].strftime("%Y-%m-%d"),
                          "Tot": m[tf].index[-1].strftime("%Y-%m-%d")} for tf in TIMEFRAMES if tf in m])


def render() -> None:
    st.markdown("## ▶️ Backtest")
    S.show_flash()
    syms = S.symbols()
    if not syms:
        st.info("Er is nog geen data. Voeg eerst data toe.")
        if st.button("📁  Naar Data", type="primary"):
            nav.go("data")
        return

    left, right = st.columns([1.25, 1], gap="large")
    with left, st.container(key="panel_assets"):
        ptitle("1 · Welke assets?")
        chosen = []
        cols = st.columns(len(syms))
        for col, s in zip(cols, syms):
            with col:
                m = S.mtf(s)
                if st.checkbox(f"**{s}**", value=True, key=f"bt_use_{s}"):
                    chosen.append(s)
                cov = _coverage(s)
                if cov is not None:
                    st.dataframe(cov, hide_index=True, width="stretch", height=min(320, 36 + 35 * len(cov)))
                    st.caption(f"Executie op **{m.base_tf}**")
                    missing = sorted({c for p, c in CONFIRMATION_TF.items() if c not in m and p in m},
                                     key=lambda t: -TF_MINUTES[t])
                    if missing:
                        st.caption(f"⚠️ Geen {', '.join(missing)}: confirmatie gebeurt dan op {m.base_tf}.")
                    if "1M" not in m or len(m["1M"]) < 12:
                        st.caption("⚠️ < 12 maanden historie: voeg 1D-data met meer historie toe.")
        if S.demo_on():
            html_block(badge("Demo-data (nep)", "warn"))

    with right, st.container(key="panel_settings"):
        ptitle("2 · Instellingen")
        st.caption("Standaard staan alle regels van het Trading Plan goed.")
        c1, c2 = st.columns(2)
        balance = c1.number_input("Startbalans per account ($)", 1_000, 10_000_000, 100_000, step=5_000)
        risk_pct = c2.number_input("Risico per trade (%)", 0.1, 5.0, 1.0, step=0.1)
        min_rr = st.slider("Minimale Risk-to-Reward", 1.0, 10.0, 2.0, 0.5)
        adaptive = st.toggle("Dynamische RR-eis (op basis van winrate)", value=True)
        period = st.columns(2)
        start = period[0].date_input("Start (optioneel)", value=None, help="Data hiervoor = alleen warm-up.")
        end = period[1].date_input("Einde (optioneel)", value=None)
        with st.expander("Geavanceerd"):
            confirmation = st.radio("Confirmation", ["bos", "first_candle"], horizontal=True,
                                    format_func=lambda x: {"bos": "Balance shift / BOS",
                                                           "first_candle": "Eerste candle in bias-richting"}[x])
            tp_source = st.radio("Take Profit", ["poi_tf", "poi_tf_and_higher"],
                                 format_func=lambda x: {"poi_tf": "Eerstvolgende liquiditeit op POI-timeframe",
                                                        "poi_tf_and_higher": "Dichtstbijzijnde liquiditeit (POI-TF of hoger)"}[x])
            liq_mode = st.radio("Liquiditeit", ["draw", "sweep"], horizontal=True,
                                format_func=lambda x: {"draw": "Sweeps + BOS", "sweep": "Alleen sweeps"}[x])
            b1, b2 = st.columns(2)
            be_swing = b1.number_input("Break-even Swing (R)", 0.5, 20.0, 2.0, 0.5)
            be_intra = b2.number_input("Break-even Intraday/Scalp (R)", 0.5, 20.0, 4.0, 0.5)
            use_costs = st.toggle("Spread & commissie meenemen", value=True)

    run = st.button("▶  Start backtest", type="primary", width="stretch", disabled=not chosen)
    if not run:
        res = S.get_results()
        if res and res.meta.get("run_at"):
            st.caption(f"Laatste backtest: {str(res.meta['run_at'])[:16]} · {', '.join(res.symbols)}")
        return

    strategy = StrategyConfig(min_rr=min_rr, adaptive_rr=adaptive, confirmation_mode=confirmation,
                              tp_source=tp_source, liquidity_mode=liq_mode,
                              be_trigger_rr_swing=be_swing, be_trigger_rr_intraday=be_intra)
    t_start = pd.Timestamp(start, tz="UTC") if start else None
    t_end = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) if end else None
    results = []
    prog = st.progress(0.0, text="Backtest voorbereiden...")
    try:
        for i, s in enumerate(chosen):
            prog.progress(i / len(chosen), text=f"{s}: analyse en backtest draaien (kan even duren bij 1m-data)...")
            m = S.mtf(s)
            if t_end is not None:
                src = {tf: m[tf][m[tf].index < t_end].drop(columns="close_time") for tf in m.frames}
                m = build_multi_timeframe(s, {k: v for k, v in src.items() if len(v)})
            st_start = t_start if t_start is not None else getattr(m, "backtest_start", None)
            costs = DEFAULT_COSTS.get(s, CostConfig()) if use_costs else CostConfig()
            results.append(Backtester(m, strategy, RiskConfig(initial_balance=float(balance),
                                                              risk_per_trade=risk_pct / 100),
                                      costs, start=st_start, verbose=False).run())
        prog.progress(1.0, text="Klaar!")
    except Exception as e:  # noqa: BLE001
        prog.empty()
        st.error(f"De backtest is gestopt door een fout: {e}")
        return

    meta = {"run_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"), "demo": S.demo_on(),
            "settings": {**asdict(strategy), "balance": balance, "risk_pct": risk_pct, "costs": use_costs,
                         "start": str(start) if start else None, "end": str(end) if end else None}}
    r = S.results_from_backtests(results, meta)
    S.set_results(r)
    rep = S.persist_results(r)
    n = len(r.trades)
    msg = f"Backtest klaar: {n} trades."
    if rep is not None:
        msg += (" Resultaten bewaard op GitHub ✓" if rep.synced else
                (f" ⚠️ GitHub-sync mislukt: {rep.error}" if rep.error else " Resultaten bewaard."))
    S.flash(msg, "success")
    nav.go("results")
