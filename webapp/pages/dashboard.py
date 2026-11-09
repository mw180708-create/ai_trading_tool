"""Dashboard: koersgrafiek, Bias Engine (stand van de regels), portfolio en markt-overzicht."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from trading_tool.metrics import compute_metrics

from .. import nav
from .. import state as S
from ..charts import PLOTLY_CONFIG, candles_payload, gauge, sparkline, style, trade_markers, tv_chart
from ..theme import DOWN, SERIES, SYMBOL_NAME, UP, badge, esc, html_block, kpi, kv, money, price_fmt, ptitle, tone_of

CHART_TFS = ["1m", "5m", "15m", "1H", "4H", "1D", "1W"]


def _welcome() -> None:
    with st.container(key="panelglow_welcome"):
        st.markdown("### Welkom 👋")
        html_block('<ol class="steps">'
                   '<li><b>Kies of bouw een strategie</b>: vanuit een sjabloon (o.a. het Trading Plan 2026-2028, EMA-crossover, '
                   'RSI, Donchian) of helemaal zelf.</li>'
                   '<li><b>Voeg data toe</b>: upload een export uit MetaTrader/TradingView (elke markt) of download crypto direct.</li>'
                   '<li><b>Backtest</b> en bekijk resultaten, grafieken en elke trade in detail.</li></ol>')
        c1, c2, c3, _ = st.columns([1, 1, 1, 1])
        if c1.button("🧠  Strategie maken", type="primary", width="stretch"):
            nav.go("strategies")
        if c2.button("📁  Data toevoegen", width="stretch"):
            nav.go("data")
        if c3.button("🧪  Probeer met demo-data", width="stretch"):
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
        html_block(f'<div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap">'
                       f'<span class="coin {symbol}">{"₿" if symbol == "BTCUSD" else "Au"}</span>'
                       f'<span style="font-family:Space Grotesk;font-weight:700;font-size:1.25rem">{esc(SYMBOL_NAME.get(symbol, symbol))}</span>'
                       f'<span style="font-family:Space Grotesk;font-size:1.25rem" class="{tone_of(chg)}">{price_fmt(last)}</span>'
                       f'<span class="{tone_of(chg)}">{chg:+.2f}%</span></div>')
        tf = st.segmented_control("Timeframe", tfs, default=default, key=f"dash_tf_{symbol}",
                                  label_visibility="collapsed") or default
        payload = _payload(S.namespace(), symbol, tf, S.fingerprint())
        res = S.get_results()
        trades = res.trades_for(symbol) if res and symbol in res.symbols else pd.DataFrame()
        markers = trade_markers(trades, m[tf].index[-3000:])
        lv = S.live(symbol, strategy) if strategy["type"] == "smc" else None
        lines = []
        if lv:
            near = sorted(lv.pois, key=lambda p: abs(p.distance_pct))[:2]
            for p in near:
                col = UP if p.direction == 1 else DOWN
                lines += [{"price": p.top, "color": col, "title": f"{p.tf} POI", "style": 2},
                          {"price": p.bottom, "color": col, "title": "", "style": 2}]
        tv_chart(payload, height=470, markers=markers, lines=lines, key=f"dash_{symbol}_{tf}")
        st.caption("▲▼ entries en ● exits uit je laatste backtest · stippellijnen = dichtstbijzijnde actieve POI's · "
                   "goud/blauw = EMA 20/50 · scroll om te zoomen, sleep om te schuiven.")


def _rules_panel(symbol: str, strategy: dict) -> None:
    lv = S.live(symbol, strategy)
    with st.container(key="panelglow_engine"):
        ptitle("Strategie-status · " + symbol)
        if not lv or lv.get("error"):
            st.caption(f"Kan de voorwaarden niet berekenen: {lv.get('error') if lv else 'geen data'}")
            return
        total_ok, total = 0, 0
        signal_side = None
        for side, icon in (("long", "🟢 Long"), ("short", "🔴 Short")):
            info = lv["sides"].get(side, {})
            if not info.get("rows"):
                continue
            chip = '<span class="chip bull">SIGNAAL</span>' if info["signal"] else ""
            html_block(f'<div style="margin:6px 0 2px 0;font-weight:600">{icon} '
                       f'<span class="small-note">({"alle" if info["logic"] == "all" else "één van"})</span> {chip}</div>')
            rows = []
            for r in info["rows"]:
                total += 1
                total_ok += r["ok"]
                vals = "" if r["left"] is None else f'<span class="small-note"> {r["left"]:,.2f} vs {r["right"]:,.2f}</span>' \
                    if r["right"] is not None else ""
                rows.append(f'<div class="engine-row" style="grid-template-columns:28px 1fr">'
                            f'<span class="chip {"bull" if r["ok"] else "bear"}">{"✓" if r["ok"] else "✗"}</span>'
                            f'<span>{esc(r["text"])}{vals}</span></div>')
            html_block("".join(rows))
            if info["signal"] and signal_side is None:
                signal_side = side
    with st.container(key="panel_decision"):
        ptitle("Beslissing (volgens de regels)")
        if signal_side:
            title, cls = f"🟢 {signal_side.upper()} SIGNAAL", "signal"
            detail = "Alle voorwaarden kloppen op de laatste gesloten candle. Entry volgens je SL/TP-regels."
        else:
            title, cls = "⚪ GEEN SIGNAAL", "none"
            detail = f"{total_ok} van {total} voorwaarden kloppen op de laatste gesloten candle."
        html_block(f'<div class="decision {cls}"><div class="decision-title">{title}</div>'
                   f'<div class="decision-detail">{esc(detail)}</div></div>')
        st.caption(f"Laatste {lv['tf']}-candle: {lv['time']:%d-%m-%Y %H:%M} UTC · geen financieel advies.")


def _engine_panel(symbol: str, strategy: dict) -> None:
    if strategy["type"] != "smc":
        _rules_panel(symbol, strategy)
        return
    lv = S.live(symbol, strategy)
    with st.container(key="panelglow_engine"):
        ptitle("Bias Engine · " + symbol)
        if lv is None:
            st.caption("Niet genoeg data voor de analyse.")
            return
        rows = ['<div class="engine-row engine-head"><span>TF</span><span>Liquiditeit</span>'
                '<span>Balance</span><span>Bias</span></div>']
        for r in lv.rows:
            lt, lc = S.fmt_bias(r["liquidity"])
            bt, bc = S.fmt_bias(r["structure"])
            xt, xc = S.fmt_bias(r["bias"] if r["available"] else None)
            rows.append(f'<div class="engine-row"><span class="tf">{r["tf"]}</span>'
                        f'<span><span class="chip {lc}">{lt}</span></span>'
                        f'<span><span class="chip {bc}">{bt}</span></span>'
                        f'<span><span class="chip {xc}">{xt}</span></span></div>')
        html_block("".join(rows))
        matches = [c["combo"] + (" (scalp)" if c["kind"] == "scalp" else "") for c in lv.combos if c["match"]]
        st.caption("Match: " + (", ".join(matches) if matches else "geen geldige combinatie"))
    with st.container(key="panel_decision"):
        ptitle("Beslissing (volgens de regels)")
        icon = {"signal": "🟢", "wait_confirm": "🟡", "wait_poi": "🔵", "none": "⚪"}[lv.status]
        html_block(f'<div class="decision {lv.status}"><div class="decision-title">{icon} {esc(lv.decision)}</div>'
                   f'<div class="decision-detail">{esc(lv.detail)}</div></div>')
        st.caption(f"Laatste candle: {lv.time:%d-%m-%Y %H:%M} UTC · geen financieel advies.")


def _left_panels(res: S.Results | None, symbol: str, strategy: dict) -> None:
    with st.container(key="panel_portfolio"):
        if res:
            view = "TOTAAL" if len(res.symbols) > 1 else res.symbols[0]
            eq = res.equity_for(view)
            init = res.initial_for(view)
            pnl = float(eq.iloc[-1] - init)
            html_block(kpi("Backtest balans", money(float(eq.iloc[-1])), f"{pnl / init * 100:+.2f}%  ({money(pnl)})",
                           tone_of(pnl)))
        else:
            html_block(kpi("Backtest balans", "—", "Nog geen backtest"))
    with st.container(key="panel_bt"):
        ptitle("Backtest")
        if res:
            st.caption(res.meta.get("strategy_name", "Trading Plan"))
            m = compute_metrics(res.trades_for(symbol) if symbol in res.symbols else pd.DataFrame(),
                                res.equity[symbol] if symbol in res.symbols else pd.Series(dtype=float),
                                res.initial.get(symbol, 1))
            if m.get("Trades"):
                pf = m["Profit Factor"]
                html_block(kv([("Trades " + symbol, f'{m["Trades"]}', None),
                               ("Winrate", f'{m["Winrate %"]:.1f}%', None),
                               ("Profit factor", "∞" if np.isinf(pf) else f"{pf:.2f}", tone_of(pf - 1)),
                               ("Max drawdown", f'{m["Max DD %"]:.1f}%', "down")]))
            else:
                st.caption(f"Geen trades voor {symbol} in de laatste backtest.")
        else:
            st.caption("Start een backtest om hier resultaten te zien.")
        if st.button("▶  Backtest starten", width="stretch", key="dash_bt"):
            nav.go("backtest")
    if strategy["type"] == "smc":
        lv = S.live(symbol, strategy)
        with st.container(key="panel_gauge"):
            ptitle("Bias-score (1M → 1H)")
            st.plotly_chart(gauge(lv.score if lv else 50, 170), width="stretch", config=PLOTLY_CONFIG)


def _bottom(res: S.Results | None, syms: list[str]) -> None:
    c1, c2 = st.columns([1, 1])
    with c1, st.container(key="panel_market"):
        ptitle("Markt-overzicht")
        cols = st.columns(len(syms))
        for col, s in zip(cols, syms):
            m = S.mtf(s)
            if m is None:
                continue
            last, chg, spark = S.daily_change(m)
            with col:
                html_block(f'<div class="mkt"><div><span class="coin {s}">{"₿" if s == "BTCUSD" else "Au"}</span>'
                           f'<span class="mkt-name">{s}</span></div><span class="{tone_of(chg)}">{chg:+.2f}%</span></div>'
                           f'<div class="mkt-price">{price_fmt(last)}</div>')
                st.plotly_chart(sparkline(spark, UP if chg >= 0 else DOWN, 70), width="stretch",
                                config=PLOTLY_CONFIG, key=f"spark_{s}")
        st.caption("Laatste 60 dagen (dag-closes) uit je data.")
    with c2, st.container(key="panel_perf"):
        ptitle("Backtest performance")
        if not res:
            st.caption("Nog geen resultaten.")
            return
        fig = go.Figure()
        for s in res.views():
            e = res.equity_for(s)
            pct = (e / res.initial_for(s) - 1) * 100
            fig.add_trace(go.Scatter(x=e.index, y=pct.values, name=s, mode="lines",
                                     line=dict(color=SERIES.get(s, "#c3c2b7"), width=2 if s == "TOTAAL" else 1.6,
                                               shape="hv"),
                                     hovertemplate="%{y:+.1f}%<extra>" + s + "</extra>"))
        fig.update_yaxes(ticksuffix="%")
        fig.add_hline(y=0, line=dict(color="rgba(139,149,167,.4)", width=1))
        st.plotly_chart(style(fig, 200), width="stretch", config=PLOTLY_CONFIG)


def render() -> None:
    syms = S.symbols()
    S.show_flash()
    if not syms:
        _welcome()
        return
    res = S.get_results()
    head = st.columns([2, 1.4, 1.6])
    with head[0]:
        symbol = st.segmented_control("Markt", syms[:6], default=syms[0], key="dash_symbol",
                                      label_visibility="collapsed") or syms[0]
        if len(syms) > 6:
            more = st.selectbox("Andere markt", ["–"] + syms[6:], key="dash_more", label_visibility="collapsed")
            symbol = more if more != "–" else symbol
    choices = S.strategy_choices()
    with head[1]:
        ids = [c["id"] for c in choices]
        last = res.meta.get("strategy_id") if res else None
        sid = st.selectbox("Strategie", ids, index=ids.index(last) if last in ids else 0, key="dash_strategy",
                           format_func=lambda i: "🧠 " + next(c["name"] for c in choices if c["id"] == i),
                           label_visibility="collapsed")
        strategy = next(c for c in choices if c["id"] == sid)
    with head[2]:
        tags = [badge("Demo-data (nep)", "warn")] if S.demo_on() else []
        st_ = S.store()
        tags.append(badge("Opslag: GitHub ✓", "ok") if st_.synced else badge("Opslag: tijdelijk", "warn"))
        if res and res.meta.get("run_at"):
            tags.append(badge(f"Backtest: {str(res.meta['run_at'])[:16]}", "info"))
        html_block(f'<div style="display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;padding-top:6px">{"".join(tags)}</div>')

    m = S.mtf(symbol)
    if m is None:
        st.warning(f"Geen data voor {symbol}.")
        return
    left, center, right = st.columns([1.05, 3.2, 1.45], gap="medium")
    with left:
        _left_panels(res, symbol, strategy)
    with center:
        chart_panel(symbol, strategy)
    with right:
        _engine_panel(symbol, strategy)
    _bottom(res, syms)
