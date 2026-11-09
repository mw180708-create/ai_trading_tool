"""Backtest: kies een strategie en markten, en draai hem op je eigen (en gedeelde) data."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from trading_tool import strategies as strat
from trading_tool.config import DEFAULT_COSTS, TIMEFRAMES, CostConfig
from trading_tool.data_loader import build_multi_timeframe

from .. import nav
from .. import state as S
from ..theme import badge, esc, html_block, ptitle


def render() -> None:
    S.show_flash()
    syms = S.symbols()
    if not syms:
        st.info("Er is nog geen koersdata. Voeg eerst data toe (of probeer de demo).")
        if st.button("Naar data", type="primary"):
            nav.go("data")
        return
    choices = S.strategy_choices()
    ids = [s["id"] for s in choices]
    want = st.session_state.get("bt_strategy")

    left, right = st.columns([1.1, 1], gap="large")
    with left, st.container(key="panel_bt_strategy"):
        ptitle("Strategie")
        idx = ids.index(want) if want in ids else 0
        sid = st.selectbox("Strategie", ids, index=idx, format_func=lambda i: next(s["name"] for s in choices if s["id"] == i),
                           label_visibility="collapsed")
        st.session_state["bt_strategy"] = sid
        strategy = next(s for s in choices if s["id"] == sid)
        if sid.startswith("tpl-"):
            st.caption("Dit is een sjabloon. Pas het aan en sla het op bij **Strategieën**.")
        html_block(badge(strat.TYPES[strategy["type"]], "info") + "<ul style='margin:8px 0 0 18px;color:#b4b4bc;font-size:.88rem'>"
                   + "".join(f"<li>{esc(x)}</li>" for x in strat.describe(strategy)) + "</ul>")
        if st.button("Strategie aanpassen", key="bt_edit"):
            if not sid.startswith("tpl-"):
                import copy
                st.session_state["draft"] = copy.deepcopy(strategy)
            nav.go("strategies")

    need = strat.required_timeframes(strategy)
    with right, st.container(key="panel_bt_markets"):
        ptitle("Markten")
        chosen = []
        for s in syms:
            m = S.mtf(s)
            if m is None:
                continue
            have = [t for t in TIMEFRAMES if t in m]
            missing = [t for t in need if t not in m]
            c1, c2 = st.columns([1, 2.4])
            if c1.checkbox(f"**{s}**", value=s in st.session_state.get("bt_syms", syms[:2]), key=f"bt_use_{s}"):
                chosen.append(s)
            span = f"{m[m.base_tf].index[0]:%d-%m-%Y} → {m[m.base_tf].index[-1]:%d-%m-%Y}"
            note = f"Executie op **{m.base_tf}** · {span}"
            if missing:
                note += f"  \nOntbreekt voor deze strategie: {', '.join(missing)} – voeg die data toe of pas de strategie aan."
            c2.markdown(f"<span class='small-note'>{note.replace(chr(10), '<br>')}</span>", unsafe_allow_html=True)
            c2.caption("Timeframes: " + " · ".join(have))
        st.session_state["bt_syms"] = chosen
        if S.demo_on():
            html_block(badge("Demo-data (nep)", "warn"))

    with st.container(key="panel_bt_settings"):
        ptitle("Instellingen")
        c1, c2, c3 = st.columns(3)
        balance = c1.number_input("Startbalans per markt ($)", 100, 100_000_000, 100_000, step=5_000)
        start = c2.date_input("Start (optioneel)", value=None, help="Data hiervoor wordt alleen als opwarmperiode gebruikt.")
        end = c3.date_input("Einde (optioneel)", value=None)
        with st.expander("Kosten per markt (spread & commissie)"):
            rows = [{"Markt": s, "Spread (prijs)": DEFAULT_COSTS.get(s, CostConfig()).spread,
                     "Commissie % per kant": DEFAULT_COSTS.get(s, CostConfig()).commission_pct * 100} for s in chosen]
            costs_df = st.data_editor(pd.DataFrame(rows, columns=["Markt", "Spread (prijs)", "Commissie % per kant"]),
                                      hide_index=True, width="stretch", disabled=["Markt"], key=f"bt_costs_{'_'.join(chosen)}")
            st.caption("Spread wordt bij de entry betaald. Commissie wordt bij entry én exit berekend over de positiegrootte.")
        st.caption(f"Risico per trade komt uit de strategie: **{float(strategy['risk_pct']):g}%**.")

    errs = strat.validate(strategy)
    for e in errs:
        st.error(e)
    run = st.button("Start backtest", type="primary", width="stretch", disabled=not chosen or bool(errs))
    if not run:
        return

    t_start = pd.Timestamp(start, tz="UTC") if start else None
    t_end = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) if end else None
    costs = {r["Markt"]: CostConfig(spread=float(r["Spread (prijs)"] or 0), commission_pct=float(r["Commissie % per kant"] or 0) / 100)
             for _, r in costs_df.iterrows()}
    results = []
    prog = st.progress(0.0, text="Backtest voorbereiden...")
    try:
        for i, s in enumerate(chosen):
            prog.progress(i / len(chosen), text=f"{s}: backtest draait (kan even duren bij 1m-data)...")
            m = S.mtf(s)
            if t_end is not None:
                src = {tf: m[tf][m[tf].index < t_end].drop(columns="close_time") for tf in m.frames}
                m = build_multi_timeframe(s, {k: v for k, v in src.items() if len(v)})
            st_start = t_start if t_start is not None else getattr(m, "backtest_start", None)
            results.append(strat.run_strategy(strategy, m, balance, costs.get(s, CostConfig()), start=st_start))
        prog.progress(1.0, text="Klaar!")
    except Exception as e:  # noqa: BLE001
        prog.empty()
        st.error(f"De backtest is gestopt: {e}")
        return

    meta = {"run_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"), "demo": S.demo_on(),
            "strategy_id": strategy["id"], "strategy_name": strategy["name"], "strategy_type": strategy["type"],
            "strategy": strategy, "balance": balance, "start": str(start) if start else None,
            "end": str(end) if end else None, "symbols": chosen}
    r = S.results_from_backtests(results, meta)
    rep = S.save_run(r)
    msg = f"Backtest klaar: {len(r.trades)} trades met '{strategy['name']}'."
    if rep.error:
        msg += f" Let op: opslaan op GitHub mislukt ({rep.error})."
    S.flash(msg)
    nav.go("results")
