"""Dashboard: grafiek, stand van de gekozen strategie, kerncijfers en markten."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from trading_tool.metrics import compute_metrics

from .. import nav
from .. import state as S
from ..charts import PLOTLY_CONFIG, candles_payload, sparkline, style, trade_markers, tv_chart
from ..theme import DOWN, UP, esc, html_block, kpi, kpi_strip, money, price_fmt, ptitle, series_color, tone_of

CHART_TFS = ["1m", "5m", "15m", "1H", "4H", "1D", "1W"]


def _welcome() -> None:
    with st.container(key="panel_welcome"):
        st.markdown("#### Aan de slag")
        html_block('<ol class="steps">'
                   '<li>Kies een sjabloon of bouw je eigen strategie.</li>'
                   '<li>Voeg koersdata toe: upload een export uit MetaTrader of TradingView, of download crypto.</li>'
                   '<li>Start een backtest en bekijk de resultaten en elke trade.</li></ol>')
        st.write("")
        c1, c2, c3, _ = st.columns([1, 1, 1, 2])
        if c1.button("Strategie maken", type="primary", width="stretch"):
            nav.go("strategies")
        if c2.button("Data toevoegen", width="stretch"):
            nav.go("data")
        if c3.button("Demo bekijken", width="stretch"):
            st.session_state["demo"] = True
            st.rerun()


@st.cache_data(show_spinner=False, max_entries=24)
def _payload(ns: str, symbol: str, tf: str, fp: str) -> dict:
    m = S._mtf(ns, symbol, fp)
    return candles_payload(m[tf], max_bars=3000)


@st.fragment
def chart_panel(symbol: str, strategy: dict) -> None:
    m = S.mtf(symbol)
    tfs = [t for t in CHART_TFS if t in m]
    default = "4H" if "4H" in tfs else tfs[-1]
    with st.container(key="panel_chart"):
        last, chg, _ = S.daily_change(m)
        head = st.columns([3, 2])
        head[0].markdown(f'<div style="display:flex;align-items:baseline;gap:12px;padding-top:4px">'
                         f'<span style="font-weight:600;font-size:1.05rem">{esc(symbol)}</span>'
                         f'<span style="font-weight:600;font-size:1.05rem;font-variant-numeric:tabular-nums">{price_fmt(last)}</span>'
                         f'<span class="{tone_of(chg)}" style="font-size:.85rem">{chg:+.2f}%</span></div>',
                         unsafe_allow_html=True)
        with head[1]:
            tf = st.segmented_control("Timeframe", tfs, default=default, key=f"dash_tf_{symbol}",
                                      label_visibility="collapsed") or default
        payload = _payload(S.namespace(), symbol, tf, S.fingerprint())
        res = S.get_results()
        trades = res.trades_for(symbol) if res and symbol in res.symbols else pd.DataFrame()
        markers = trade_markers(trades, m[tf].index[-3000:])
        lv = S.live(symbol, strategy) if strategy["type"] == "smc" else None
        lines = []
        if lv:
            for p in sorted(lv.pois, key=lambda p: abs(p.distance_pct))[:2]:
                col = UP if p.direction == 1 else DOWN
                lines += [{"price": p.top, "color": col, "title": f"{p.tf} POI", "style": 2},
                          {"price": p.bottom, "color": col, "title": "", "style": 2}]
        tv_chart(payload, height=460, markers=markers, lines=lines, key=f"dash_{symbol}_{tf}")


def _status(title: str, tone: str, detail: str, foot: str) -> None:
    with st.container(key="panel_status"):
        ptitle("Status")
        html_block(f'<div class="status-title"><span class="dot {tone}"></span>{esc(title)}</div>'
                   f'<div class="status-detail">{esc(detail)}</div>')
        st.caption(foot)


def _rules_side(symbol: str, strategy: dict) -> None:
    lv = S.live(symbol, strategy)
    if not lv or lv.get("error"):
        _status("Niet beschikbaar", "", f"De voorwaarden konden niet berekend worden: "
                f"{lv.get('error') if lv else 'geen data'}", "")
        return
    total_ok, total, signal_side = 0, 0, None
    blocks = []
    for side, label in (("long", "Long"), ("short", "Short")):
        info = lv["sides"].get(side, {})
        if not info.get("rows"):
            continue
        rows = []
        for r in info["rows"]:
            total += 1
            total_ok += r["ok"]
            vals = (f'<div class="small-note">{r["left"]:,.2f} vs {r["right"]:,.2f}</div>'
                    if r["left"] is not None and r["right"] is not None else "")
            rows.append(f'<div class="row two"><span class="dot {"up" if r["ok"] else ""}"></span>'
                        f'<div>{esc(r["text"])}{vals}</div></div>')
        sig_html = ' &nbsp;<span class="tag bull">signaal</span>' if info["signal"] else ""
        logic = "alle voorwaarden" if info["logic"] == "all" else "één voorwaarde"
        blocks.append(f'<div style="margin:10px 0 2px 0;font-weight:500">{label}'
                      f'<span class="small-note"> · {logic}</span>{sig_html}</div>' + "".join(rows))
        if info["signal"] and signal_side is None:
            signal_side = side
    if signal_side:
        _status(f"{signal_side.capitalize()}-signaal", "up",
                "Alle voorwaarden kloppen op de laatste gesloten candle.", f"{lv['tf']} · {lv['time']:%d-%m-%Y %H:%M} UTC")
    else:
        _status("Geen signaal", "", f"{total_ok} van {total} voorwaarden kloppen op de laatste gesloten candle.",
                f"{lv['tf']} · {lv['time']:%d-%m-%Y %H:%M} UTC")
    with st.container(key="panel_conditions"):
        ptitle("Voorwaarden")
        html_block("".join(blocks))


def _smc_side(symbol: str, strategy: dict) -> None:
    lv = S.live(symbol, strategy)
    if lv is None:
        _status("Niet beschikbaar", "", "Niet genoeg data voor de analyse.", "")
        return
    tone = {"signal": "up", "wait_confirm": "warn", "wait_poi": "accent", "none": ""}[lv.status]
    _status(lv.decision, tone, lv.detail, f"Laatste candle {lv.time:%d-%m-%Y %H:%M} UTC")
    with st.container(key="panel_structure"):
        ptitle("Marktstructuur")
        rows = ['<div class="row head"><span>TF</span><span>Liquiditeit</span><span>Structuur</span><span>Bias</span></div>']
        for r in lv.rows:
            lt, lc = S.fmt_bias(r["liquidity"])
            bt, bc = S.fmt_bias(r["structure"])
            xt, xc = S.fmt_bias(r["bias"] if r["available"] else None)
            rows.append(f'<div class="row"><span class="tf">{r["tf"]}</span><span><span class="tag {lc}">{lt}</span></span>'
                        f'<span><span class="tag {bc}">{bt}</span></span><span><span class="tag {xc}">{xt}</span></span></div>')
        html_block("".join(rows))
        label = "bullish" if lv.score > 55 else ("bearish" if lv.score < 45 else "neutraal")
        html_block(f'<div style="display:flex;justify-content:space-between;margin-top:12px" class="small-note">'
                   f'<span>Bias-score</span><span>{lv.score} / 100 · {label}</span></div>'
                   f'<div class="meter"><div style="width:{lv.score}%"></div></div>')
        matches = [c["combo"] for c in lv.combos if c["match"]]
        st.caption("Match: " + (", ".join(matches) if matches else "geen"))


def _kpis(res: S.Results | None, symbol: str) -> None:
    if not res or symbol not in res.symbols:
        with st.container(key="panel_kpis"):
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown('<span class="muted">Nog geen backtest voor deze markt.</span>', unsafe_allow_html=True)
            if c2.button("Backtest starten", width="stretch", key="dash_bt"):
                nav.go("backtest")
        return
    m = compute_metrics(res.trades_for(symbol), res.equity[symbol], res.initial[symbol])
    eq = res.equity[symbol]
    pf = m.get("Profit Factor", 0)
    kpi_strip([kpi("Balans", money(float(eq.iloc[-1])), f"{m.get('Net Profit %', 0):+.2f}%", tone_of(m.get("Net Profit", 0))),
               kpi("Trades", f"{m.get('Trades', 0)}", f"{m.get('Avg R/trade', 0):+.2f} R per trade"),
               kpi("Winrate", f"{m.get('Winrate %', 0):.1f}%"),
               kpi("Profit factor", "∞" if np.isinf(pf) else f"{pf:.2f}"),
               kpi("Max drawdown", f"{m.get('Max DD %', 0):.1f}%")])


def _bottom(res: S.Results | None, syms: list[str]) -> None:
    c1, c2 = st.columns([1, 1.3], gap="medium")
    with c1, st.container(key="panel_markets"):
        ptitle("Markten")
        for s in syms[:6]:
            m = S.mtf(s)
            if m is None:
                continue
            last, chg, spark = S.daily_change(m)
            a, b = st.columns([1, 1.4])
            a.markdown(f'<div class="mkt-name">{esc(s)}</div><div class="mkt-price">{price_fmt(last)}</div>'
                       f'<div class="{tone_of(chg)}" style="font-size:.8rem">{chg:+.2f}%</div>', unsafe_allow_html=True)
            with b:
                st.plotly_chart(sparkline(spark, UP if chg >= 0 else DOWN, 58), width="stretch",
                                config=PLOTLY_CONFIG, key=f"spark_{s}")
    with c2, st.container(key="panel_perf"):
        ptitle("Rendement laatste backtest")
        if not res:
            st.caption("Nog geen resultaten.")
            return
        fig = go.Figure()
        for s in res.views():
            e = res.equity_for(s)
            pct = (e / res.initial_for(s) - 1) * 100
            fig.add_trace(go.Scatter(x=e.index, y=pct.values, name=s, mode="lines",
                                     line=dict(color=series_color(s, res.symbols), width=1.8 if s == "TOTAAL" else 1.4,
                                               shape="hv"),
                                     hovertemplate="%{y:+.1f}%<extra>" + s + "</extra>"))
        fig.update_yaxes(ticksuffix="%")
        fig.add_hline(y=0, line=dict(color="rgba(161,161,170,.35)", width=1))
        st.plotly_chart(style(fig, 230), width="stretch", config=PLOTLY_CONFIG)


def render() -> None:
    syms = S.symbols()
    S.show_flash()
    if not syms:
        _welcome()
        return
    res = S.get_results()
    choices = S.strategy_choices()
    bar = st.columns([1.2, 2, 2.2])
    with bar[0]:
        symbol = st.selectbox("Markt", syms, key="dash_symbol", label_visibility="collapsed")
    with bar[1]:
        ids = [c["id"] for c in choices]
        last = res.meta.get("strategy_id") if res else None
        sid = st.selectbox("Strategie", ids, index=ids.index(last) if last in ids else 0, key="dash_strategy",
                           format_func=lambda i: next(c["name"] for c in choices if c["id"] == i),
                           label_visibility="collapsed")
        strategy = next(c for c in choices if c["id"] == sid)
    with bar[2]:
        notes = []
        if S.demo_on():
            notes.append("voorbeelddata")
        if res and res.meta.get("run_at"):
            notes.append(f"laatste backtest {str(res.meta['run_at'])[:16]}")
        st.markdown(f'<div class="small-note" style="text-align:right;padding-top:9px">{" · ".join(notes)}</div>',
                    unsafe_allow_html=True)

    if S.mtf(symbol) is None:
        st.warning(f"Geen data voor {symbol}.")
        return
    _kpis(res, symbol)
    st.write("")
    main, side = st.columns([3, 1.25], gap="medium")
    with main:
        chart_panel(symbol, strategy)
    with side:
        if strategy["type"] == "smc":
            _smc_side(symbol, strategy)
        else:
            _rules_side(symbol, strategy)
    _bottom(res, syms)
