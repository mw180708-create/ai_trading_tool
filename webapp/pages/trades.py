"""Alle trades: filteren, downloaden en elke trade in detail op de grafiek."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from trading_tool.config import TF_MINUTES
from trading_tool.metrics import compute_metrics

from .. import state as S
from ..charts import candles_payload, trade_markers, tv_chart
from ..theme import DOWN, UP, html_block, kpi, money, ptitle, tone_of
from .results import no_results

ZOOM_TFS = ["1m", "5m", "15m", "1H", "4H", "1D"]


@st.cache_data(show_spinner=False, max_entries=12)
def _zoom_payload(ns: str, symbol: str, tf: str, fp: str, t0: str, t1: str) -> dict:
    m = S._mtf(ns, symbol, fp)
    df = m[tf]
    return candles_payload(df[(df.index >= pd.Timestamp(t0)) & (df.index <= pd.Timestamp(t1))], max_bars=4000)


def _detail(row: pd.Series, n: int) -> None:
    m = S.mtf(row["symbol"])
    if m is None:
        st.caption("De data van deze trade staat niet (meer) in de bibliotheek.")
        return
    dur = row["exit_time"] - row["entry_time"]
    tf = next((z for z in ZOOM_TFS if z in m and dur / pd.Timedelta(minutes=TF_MINUTES[z]) <= 250),
              "1D" if "1D" in m else m.base_tf)
    pad = pd.Timedelta(minutes=TF_MINUTES[tf] * 120)
    t0, t1 = row["entry_time"] - pad, row["exit_time"] + pad / 2
    payload = _zoom_payload(S.namespace(), row["symbol"], tf, S.fingerprint(), str(t0), str(t1))
    if not payload["candles"]:
        st.caption("Geen candles gevonden rond deze trade.")
        return
    idx = pd.DatetimeIndex([pd.Timestamp(c["time"], unit="s", tz="UTC") for c in payload["candles"]])
    markers = trade_markers(row.to_frame().T, idx)
    lines = [
        {"price": float(row["entry"]), "color": "#e6e9ef", "title": "Entry", "style": 0, "width": 2},
        {"price": float(row["stop_loss"]), "color": DOWN, "title": "SL", "style": 0, "width": 2},
    ]
    if pd.notna(row.get("take_profit")):
        lines.append({"price": float(row["take_profit"]), "color": UP, "title": "TP", "style": 0, "width": 2})
    if "poi_top" in row and pd.notna(row.get("poi_top")):
        lines += [{"price": float(row["poi_top"]), "color": "#3b9eff", "title": f"{row['poi_tf']} POI", "style": 2},
                  {"price": float(row["poi_bottom"]), "color": "#3b9eff", "title": "", "style": 2}]
    vis = (int((row["entry_time"] - pad / 2).timestamp()), int((row["exit_time"] + pad / 4).timestamp()))
    tv_chart(payload, height=430, markers=markers, lines=lines, visible=vis, key=f"trade_{n}")
    cols = st.columns(4)
    rr = float(row["r_multiple"])
    prr = row.get("planned_rr")
    rqr = row.get("required_rr")
    smc = row.get("confirmation_tf", "-") not in ("-", None) and pd.notna(row.get("poi_top"))
    cards = [kpi("Resultaat", f"{rr:+.2f} R", money(float(row["pnl"])), tone_of(rr), small=True),
             kpi("Geplande RR", f"{prr:.2f}" if pd.notna(prr) else "–",
                 f"Eis was {rqr:.2f}" if pd.notna(rqr) else "geen vaste TP" if pd.isna(prr) else "", small=True),
             kpi("POI → confirmatie" if smc else "Signaal-timeframe",
                 f"{row['poi_tf']} → {row['confirmation_tf']}" if smc else str(row["poi_tf"]), row["trade_type"], small=True),
             kpi("Bias-match" if smc else "Strategie", str(row["bias_combo"]),
                 "BE geraakt" if row["be_moved"] else "BE niet geraakt", small=True)]
    for c, h in zip(cols, cards):
        with c:
            html_block(h)
    st.caption(f"Grafiek op {tf} · entry {row['entry_time']:%d-%m-%Y %H:%M} · exit {row['exit_time']:%d-%m-%Y %H:%M} "
               f"({row['exit_reason']}) · tijden in UTC")


def render() -> None:
    if no_results("trd"):
        return
    res = S.get_results()
    t = res.trades
    if t.empty:
        st.info("De laatste backtest had geen trades.")
        return
    t = t.sort_values("entry_time").reset_index(drop=True)
    t.insert(0, "#", range(1, len(t) + 1))

    with st.container(key="panel_filters"):
        f1, f2, f3, f4 = st.columns(4)
        opts = lambda c: sorted(t[c].unique())  # noqa: E731
        fs = f1.multiselect("Asset", opts("symbol"), default=opts("symbol"))
        ft = f2.multiselect("Type", opts("trade_type"), default=opts("trade_type"))
        fd = f3.multiselect("Richting", opts("direction"), default=opts("direction"))
        fe = f4.multiselect("Exit", opts("exit_reason"), default=opts("exit_reason"))
    view = t[t.symbol.isin(fs) & t.trade_type.isin(ft) & t.direction.isin(fd) & t.exit_reason.isin(fe)]

    mm = compute_metrics(view, pd.Series(dtype=float), 1)
    if mm.get("Trades"):
        html_block(f"<div class='small-note'>{len(view)} trades · winrate {mm['Winrate %']:.1f}% · "
                   f"totaal {mm['Total R']:+.2f} R · netto {money(mm['Net Profit'])}</div>")

    with st.container(key="panel_table"):
        cols = ["#", "symbol", "direction", "trade_type", "poi_tf", "confirmation_tf", "entry_time", "entry",
                "stop_loss", "take_profit", "planned_rr", "exit_time", "exit", "exit_reason", "r_multiple", "pnl", "equity"]
        event = st.dataframe(
            view[cols], hide_index=True, width="stretch", height=420, on_select="rerun", selection_mode="single-row",
            key="trade_table", column_config={
                "symbol": "Markt", "direction": "Richting", "trade_type": "Type",
                "poi_tf": "POI" if res.is_smc else "Signaal-TF",
                "confirmation_tf": "Confirm.",
                "entry_time": st.column_config.DatetimeColumn("Entry", format="DD-MM-YY HH:mm"),
                "exit_time": st.column_config.DatetimeColumn("Exit", format="DD-MM-YY HH:mm"),
                "entry": st.column_config.NumberColumn("Entry prijs", format="%.2f"),
                "stop_loss": st.column_config.NumberColumn("SL", format="%.2f"),
                "take_profit": st.column_config.NumberColumn("TP", format="%.2f"),
                "exit": st.column_config.NumberColumn("Exit prijs", format="%.2f"),
                "planned_rr": st.column_config.NumberColumn("RR", format="%.2f"),
                "exit_reason": "Reden", "r_multiple": st.column_config.NumberColumn("R", format="%+.2f"),
                "pnl": st.column_config.NumberColumn("P&L", format="dollar"),
                "equity": st.column_config.NumberColumn("Balans", format="dollar")})
        st.caption("Klik op een rij om de trade hieronder op de grafiek te zien.")
        d1, d2 = st.columns(2)
        d1.download_button("Download selectie (CSV)", view.to_csv(index=False).encode(),
                           "trades.csv", "text/csv", width="stretch")
        d2.download_button("Download alle trades (CSV)", t.to_csv(index=False).encode(), "trades_alles.csv",
                           "text/csv", width="stretch")

    if view.empty:
        return
    sel = event.selection.rows if event and hasattr(event, "selection") else []
    with st.container(key="panelglow_detail"):
        ptitle("Trade in detail")
        labels = [f"#{r['#']} · {r['symbol']} · {r['entry_time']:%d-%m-%Y %H:%M} · {r['direction']} · "
                  f"{r['trade_type']} · {r['r_multiple']:+.2f} R ({r['exit_reason']})" for _, r in view.iterrows()]
        default = sel[0] if sel else 0
        pick = st.selectbox("Trade", range(len(view)), index=min(default, len(view) - 1),
                            format_func=lambda i: labels[i], label_visibility="collapsed",
                            key=f"trade_pick_{default}")
        _detail(view.iloc[pick], int(view.iloc[pick]["#"]))
