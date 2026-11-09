"""Resultaten: KPI's, equity curve, verdeling, per maand en uitsplitsingen."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from trading_tool.metrics import breakdown_by, compute_metrics, format_report

from .. import nav
from .. import state as S
from ..charts import PLOTLY_CONFIG, style
from ..theme import DOWN, NEUTRAL, SERIES, UP, html_block, kpi, money, ptitle, tone_of

PCT = st.column_config.NumberColumn(format="%.1f%%")
R2 = st.column_config.NumberColumn(format="%.2f")
USD = st.column_config.NumberColumn(format="dollar")


def run_picker(key: str) -> None:
    runs = S.list_runs()
    if not runs:
        return
    ids = [r for r, _ in runs]
    meta = dict(runs)
    cur = st.session_state.get("run_id") if st.session_state.get("run_id") in ids else ids[0]

    def label(rid: str) -> str:
        m = meta.get(rid, {})
        return (f"{str(m.get('run_at', rid))[:16]} · {m.get('strategy_name', 'Trading Plan')} · "
                f"{', '.join(m.get('symbols') or list((m.get('initial') or {}).keys()))}")
    c1, c2 = st.columns([4, 1])
    pick = c1.selectbox("Backtest", ids, index=ids.index(cur), format_func=label, key=f"{key}_run",
                        label_visibility="collapsed")
    if pick != st.session_state.get("run_id"):
        S.select_run(pick)
        st.rerun()
    if c2.button("🗑  Verwijderen", key=f"{key}_delrun", width="stretch"):
        S.delete_run(pick)
        S.flash("Backtest verwijderd.", "warning")
        st.rerun()


def no_results(key: str = "res") -> bool:
    run_picker(key)
    res = S.get_results()
    if res is None:
        st.info("Nog geen resultaten. Start eerst een backtest.")
        if st.button("▶  Naar Backtest", type="primary"):
            nav.go("backtest")
        return True
    if res.meta.get("demo"):
        st.warning("Dit zijn resultaten op **demo-data** (nep).")
    return False


def render() -> None:
    st.markdown("## 📊 Resultaten")
    S.show_flash()
    if no_results("res"):
        return
    res = S.get_results()
    views = res.views()
    top = st.columns([2, 3])
    view = top[0].segmented_control("Bekijk", views, default=views[-1], key="res_view",
                                    label_visibility="collapsed") or views[-1]
    if res.meta.get("run_at"):
        top[1].markdown(f"<div style='text-align:right' class='small-note'>Strategie <b>{res.meta.get('strategy_name', 'Trading Plan')}</b>"
                        f" · {res.meta['run_at']}</div>", unsafe_allow_html=True)
    trades, equity, initial = res.trades_for(view), res.equity_for(view), res.initial_for(view)
    m = compute_metrics(trades, equity, initial)
    if not m.get("Trades"):
        st.warning("Geen trades met deze data en instellingen. Tip: voeg meer historie toe (1D-data) of verlaag de minimale RR.")
        return

    pf = m["Profit Factor"]
    cards = [
        kpi("Net profit", money(m["Net Profit"]), f"{m['Net Profit %']:+.2f}%", tone_of(m["Net Profit"])),
        kpi("Winrate", f"{m['Winrate %']:.1f}%", f"BE-exits {m['Break-even %']:.0f}%"),
        kpi("Profit factor", "∞" if np.isinf(pf) else f"{pf:.2f}", "> 1 = winstgevend", tone_of(pf - 1)),
        kpi("Max drawdown", f"{m['Max DD %']:.1f}%", "op gesloten trades", "down"),
        kpi("Trades", f"{m['Trades']}", " · ".join(f"{n} {t.lower()}" for t, n in trades["trade_type"].value_counts().items())),
        kpi("Gem. RR", f"{m['Avg planned RR']:.2f}", f"{m['Avg R/trade']:+.2f} R per trade", tone_of(m["Avg R/trade"])),
    ]
    cols = st.columns(6)
    for i, (c, html) in enumerate(zip(cols, cards)):
        with c, st.container(key=f"panel_kpi{i}"):
            html_block(html)

    with st.container(key="panel_equity"):
        ptitle("Equity curve · rendement % na elke gesloten trade")
        fig = go.Figure()
        names = res.views() if view == "TOTAAL" else [view]
        for s in names:
            e = res.equity_for(s)
            pct = (e / res.initial_for(s) - 1) * 100
            fig.add_trace(go.Scatter(x=e.index, y=pct.values, name=s, mode="lines", customdata=e.values,
                                     line=dict(color=SERIES.get(s, "#c3c2b7"), width=2.2 if s == "TOTAAL" else 1.6,
                                               shape="hv"),
                                     hovertemplate="%{y:+.2f}% (%{customdata:$,.0f})<extra>" + s + "</extra>"))
        fig.add_hline(y=0, line=dict(color="rgba(139,149,167,.4)", width=1))
        fig.update_yaxes(ticksuffix="%")
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(style(fig, 330), width="stretch", config=PLOTLY_CONFIG)

    c1, c2, c3 = st.columns([1.4, 1.1, 1])
    with c1, st.container(key="panel_rbars"):
        ptitle("Resultaat per trade (R)")
        r = trades["r_multiple"].to_numpy()
        colors = np.where(r > 0.05, UP, np.where(r < -0.05, DOWN, NEUTRAL))
        fig = go.Figure(go.Bar(x=np.arange(1, len(r) + 1), y=r, marker=dict(color=colors, cornerradius=3),
                               customdata=np.stack([trades["symbol"], trades["trade_type"], trades["exit_reason"]], 1),
                               hovertemplate="Trade %{x}: %{y:+.2f} R<br>%{customdata[0]} · %{customdata[1]} · "
                                             "%{customdata[2]}<extra></extra>"))
        fig.update_layout(bargap=0.6 if len(r) < 15 else 0.2)
        fig.update_xaxes(title="Trade #")
        st.plotly_chart(style(fig, 260, legend=False), width="stretch", config=PLOTLY_CONFIG)
    with c2, st.container(key="panel_month"):
        ptitle("Resultaat per maand (R)")
        mon = trades.set_index(pd.DatetimeIndex(trades["exit_time"]))["r_multiple"].resample("MS").sum()
        fig = go.Figure(go.Bar(x=mon.index, y=mon.values, marker=dict(
            color=np.where(mon.values >= 0, UP, DOWN), cornerradius=3),
            hovertemplate="%{x|%b %Y}: %{y:+.2f} R<extra></extra>"))
        fig.update_layout(bargap=0.3)
        st.plotly_chart(style(fig, 260, legend=False), width="stretch", config=PLOTLY_CONFIG)
    with c3, st.container(key="panel_exits"):
        ptitle("Exits")
        ex = trades["exit_reason"].value_counts().reindex(["TP", "BE", "SL", "EOD"]).dropna()
        names = {"TP": "Take Profit", "BE": "Break-even", "SL": "Stop Loss", "EOD": "Einde data"}
        fig = go.Figure(go.Bar(y=[names[k] for k in ex.index], x=ex.values, orientation="h", text=ex.values.astype(int),
                               textposition="outside",
                               marker=dict(color=[{"TP": UP, "SL": DOWN}.get(k, NEUTRAL) for k in ex.index],
                                           cornerradius=3),
                               hovertemplate="%{y}: %{x} trades<extra></extra>"))
        fig.update_yaxes(autorange="reversed", showgrid=False)
        fig.update_xaxes(range=[0, float(ex.max()) * 1.18 if len(ex) else 1])
        fig.update_layout(bargap=0.45)
        st.plotly_chart(style(fig, 260, legend=False), width="stretch", config=PLOTLY_CONFIG)

    t1, t2 = st.columns(2)
    second = ("poi_tf", "Per POI-timeframe", "POI") if res.is_smc else ("exit_reason", "Per exit-reden", "Exit")
    for col, key, title, label in [(t1, "trade_type", "Per trade type", "Type"), (t2, *second)]:
        with col, st.container(key=f"panel_{key}"):
            ptitle(title)
            b = breakdown_by(trades, key).reset_index().rename(columns={"symbol": "Asset", key: label})
            st.dataframe(b, hide_index=True, width="stretch", column_config={
                "Winrate %": PCT, "Avg R": st.column_config.NumberColumn("Gem. R", format="%.2f"),
                "Total R": st.column_config.NumberColumn("Totaal R", format="%.2f"), "Net Profit": USD})
    if res.is_smc:
        st.caption("Swing = Monthly/Weekly POI · Intraday = Daily/4H/1H POI · Scalp = alleen via een scalp-combinatie")

    with st.container(key="panel_compare"):
        ptitle("Per markt")
        rows = {s: compute_metrics(res.trades_for(s), res.equity_for(s), res.initial_for(s)) for s in res.views()}
        comp = pd.DataFrame(rows)
        if not res.is_smc:
            comp = comp.drop(index=[i for i in ("Swing", "Intraday", "Scalp") if i in comp.index])
        comp = format_report(comp, money_rows=("Net Profit",))
        comp.index = [{"Avg planned RR": "Gem. geplande RR", "Avg win R": "Gem. winst (R)", "Avg R/trade": "Gem. R per trade",
                       "Total R": "Totaal R", "Max DD %": "Max drawdown %", "Net Profit %": "Net profit %"}.get(i, i)
                      for i in comp.index]
        st.dataframe(comp, width="stretch")
        with st.expander("Waarom zijn signalen overgeslagen?"):
            st.dataframe(pd.DataFrame({s: {"Confirmaties gevonden": v.get("signals", 0),
                                           "Overgeslagen: RR te laag": v.get("skip_rr", 0),
                                           "Overgeslagen: geen TP-liquiditeit": v.get("skip_no_tp", 0),
                                           "Overgeslagen: ongeldige SL": v.get("skip_sl", 0)}
                                       for s, v in res.stats.items()}), width="stretch")
