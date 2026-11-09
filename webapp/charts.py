"""Grafieken: snelle candlestick-chart (TradingView Lightweight Charts, lokaal meegeleverd) + Plotly."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit.components.v1 as components

from .theme import ACCENT, DOWN, GOLD, NEUTRAL, UP

LIB = Path(__file__).resolve().parents[1] / "assets" / "lightweight-charts.standalone.production.js"


@lru_cache(maxsize=1)
def _lib_js() -> str:
    return LIB.read_text(encoding="utf-8")


def _epoch(idx) -> np.ndarray:
    return pd.DatetimeIndex(idx).tz_convert("UTC").as_unit("s").asi8


def candles_payload(df: pd.DataFrame, max_bars: int = 3000, emas: tuple[int, ...] = (20, 50)) -> dict:
    """OHLC -> JSON-klare dict voor de chart (laatste `max_bars` candles)."""
    ema_full = {n: df["close"].ewm(span=n, adjust=False).mean() for n in emas}
    d = df.iloc[-max_bars:]
    t = _epoch(d.index)
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    out = {"candles": [{"time": int(a), "open": float(b), "high": float(e), "low": float(f), "close": float(g)}
                       for a, b, e, f, g in zip(t, o, h, l, c)]}
    vol = d["volume"].to_numpy(float) if "volume" in d else np.zeros(len(d))
    if np.nansum(vol) > 0:
        out["volume"] = [{"time": int(a), "value": float(v), "color": "rgba(38,166,154,.35)" if g >= b
                          else "rgba(239,83,80,.35)"} for a, v, b, g in zip(t, vol, o, c)]
    out["emas"] = [{"name": f"EMA {n}", "color": col,
                    "data": [{"time": int(a), "value": float(v)} for a, v in zip(t, ema_full[n].iloc[-max_bars:].to_numpy())]}
                   for n, col in zip(emas, (GOLD, ACCENT))]
    return out


def snap_time(index: pd.DatetimeIndex, ts: pd.Timestamp) -> int | None:
    """Tijdstip -> open-tijd van de candle waarin het valt (epoch s)."""
    i = index.searchsorted(ts, side="right") - 1
    if i < 0:
        return None
    return int(pd.Timestamp(index[i]).tz_convert("UTC").timestamp())


def trade_markers(trades: pd.DataFrame, index: pd.DatetimeIndex) -> list[dict]:
    if trades is None or trades.empty or len(index) == 0:
        return []
    first, last = index[0], index[-1]
    out = []
    for _, r in trades.iterrows():
        et, xt = pd.Timestamp(r["entry_time"]), pd.Timestamp(r["exit_time"])
        # entry_time = close van de confirmatie-candle -> 1 ns terug zodat hij in die candle valt
        if first <= et <= last + pd.Timedelta(days=40):
            t = snap_time(index, et - pd.Timedelta(seconds=1))
            if t is not None:
                long = r["direction"] == "LONG"
                out.append({"time": t, "position": "belowBar" if long else "aboveBar",
                            "color": UP if long else DOWN, "shape": "arrowUp" if long else "arrowDown",
                            "text": f"{'Long' if long else 'Short'} · {r['poi_tf']}"})
        if first <= xt <= last + pd.Timedelta(days=40):
            t = snap_time(index, xt - pd.Timedelta(seconds=1))
            if t is not None:
                rr = float(r["r_multiple"])
                out.append({"time": t, "position": "aboveBar" if r["direction"] == "LONG" else "belowBar",
                            "color": UP if rr > 0.05 else (DOWN if rr < -0.05 else NEUTRAL), "shape": "circle",
                            "text": f"{r['exit_reason']} {rr:+.1f}R"})
    return sorted(out, key=lambda m: m["time"])


def tv_chart(payload: dict, height: int = 520, markers: list[dict] | None = None,
             lines: list[dict] | None = None, visible: tuple[int, int] | None = None,
             show_bars: int = 160, key: str | None = None) -> None:
    """Render de candlestick-chart. lines: [{price, color, title, style(0=solid,2=dashed)}]."""
    cfg = {"markers": markers or [], "lines": lines or [], "visible": visible, "showBars": show_bars,
           "height": height, "up": UP, "down": DOWN}
    data = json.dumps(payload, separators=(",", ":"))
    html = f"""
<div id="wrap" style="position:relative;width:100%;height:{height}px;">
  <div id="chart" style="position:absolute;inset:0;"></div>
  <div id="legend" style="position:absolute;left:10px;top:6px;z-index:5;font:12px Inter,system-ui,sans-serif;color:#c4cad6;pointer-events:none;"></div>
</div>
<script>{_lib_js()}</script>
<script>
const P = {data};
const C = {json.dumps(cfg)};
const el = document.getElementById('chart');
const chart = LightweightCharts.createChart(el, {{
  autoSize: true,
  layout: {{ background: {{ type: 'solid', color: 'rgba(0,0,0,0)' }}, textColor: '#8b95a7',
             fontFamily: 'Inter, system-ui, sans-serif', fontSize: 11 }},
  grid: {{ vertLines: {{ color: 'rgba(110,150,230,0.06)' }}, horzLines: {{ color: 'rgba(110,150,230,0.06)' }} }},
  rightPriceScale: {{ borderColor: 'rgba(110,150,230,0.18)' }},
  timeScale: {{ borderColor: 'rgba(110,150,230,0.18)', timeVisible: true, secondsVisible: false, rightOffset: 6 }},
  crosshair: {{ mode: 0, vertLine: {{ color: 'rgba(59,158,255,0.45)', labelBackgroundColor: '#1d2a40' }},
                horzLine: {{ color: 'rgba(59,158,255,0.45)', labelBackgroundColor: '#1d2a40' }} }},
}});
const s = chart.addCandlestickSeries({{ upColor: C.up, downColor: C.down, borderVisible: false,
  wickUpColor: C.up, wickDownColor: C.down }});
s.setData(P.candles);
if (P.volume) {{
  const v = chart.addHistogramSeries({{ priceFormat: {{ type: 'volume' }}, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false }});
  chart.priceScale('vol').applyOptions({{ scaleMargins: {{ top: 0.82, bottom: 0 }} }});
  v.setData(P.volume);
}}
const emaSeries = (P.emas || []).map(e => {{
  const ls = chart.addLineSeries({{ color: e.color, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false,
                                    crosshairMarkerVisible: false }});
  ls.setData(e.data); return [e, ls];
}});
if (C.markers.length) s.setMarkers(C.markers);
C.lines.forEach(l => s.createPriceLine({{ price: l.price, color: l.color, lineWidth: l.width || 1,
  lineStyle: l.style ?? 2, axisLabelVisible: true, title: l.title || '' }}));
const n = P.candles.length;
if (C.visible) {{ try {{ chart.timeScale().setVisibleRange({{ from: C.visible[0], to: C.visible[1] }}); }} catch (e) {{ chart.timeScale().fitContent(); }} }}
else if (n > C.showBars) chart.timeScale().setVisibleLogicalRange({{ from: n - C.showBars, to: n + 4 }});
else chart.timeScale().fitContent();
const legend = document.getElementById('legend');
const fmt = x => x == null ? '' : x.toLocaleString('en-US', {{ maximumFractionDigits: 2, minimumFractionDigits: 2 }});
function setLegend(bar) {{
  if (!bar) bar = P.candles[n - 1];
  if (!bar) return;
  const col = bar.close >= bar.open ? C.up : C.down;
  let h = `<span style="color:#8b95a7">O</span> <b style="color:${{col}}">${{fmt(bar.open)}}</b> &nbsp;` +
          `<span style="color:#8b95a7">H</span> <b style="color:${{col}}">${{fmt(bar.high)}}</b> &nbsp;` +
          `<span style="color:#8b95a7">L</span> <b style="color:${{col}}">${{fmt(bar.low)}}</b> &nbsp;` +
          `<span style="color:#8b95a7">C</span> <b style="color:${{col}}">${{fmt(bar.close)}}</b>`;
  emaSeries.forEach(([e]) => {{ h += ` &nbsp; <span style="color:${{e.color}}">● ${{e.name}}</span>`; }});
  legend.innerHTML = h;
}}
setLegend();
chart.subscribeCrosshairMove(p => setLegend(p && p.seriesData ? p.seriesData.get(s) : null));
</script>
"""
    components.html(html, height=height + 6)


# --------------------------------------------------------------------------- #
# Plotly
# --------------------------------------------------------------------------- #
def style(fig: go.Figure, height: int = 320, title: str | None = None, legend: bool = True) -> go.Figure:
    fig.update_layout(
        template="plotly_dark", height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=40 if title else 10, b=8),
        title=dict(text=title, x=0, font=dict(size=13, color="#c4cad6")) if title else None,
        font=dict(family="Inter, system-ui, sans-serif", size=11, color="#8b95a7"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)"),
        showlegend=legend, hoverlabel=dict(bgcolor="#151d2b", bordercolor="#2a3a55", font=dict(color="#e6e9ef")),
    )
    fig.update_xaxes(showgrid=False, linecolor="rgba(110,150,230,.18)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(110,150,230,.08)", zeroline=False)
    return fig


def gauge(score: int, height: int = 190) -> go.Figure:
    label = "Bullish" if score > 55 else ("Bearish" if score < 45 else "Neutraal")
    color = UP if score > 55 else (DOWN if score < 45 else NEUTRAL)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score, number=dict(font=dict(size=34, color="#e6e9ef", family="Space Grotesk")),
        gauge=dict(axis=dict(range=[0, 100], tickwidth=0, tickcolor="rgba(0,0,0,0)", tickfont=dict(size=10)),
                   bar=dict(color=color, thickness=0.28), bgcolor="rgba(0,0,0,0)", borderwidth=0,
                   steps=[dict(range=[0, 45], color="rgba(239,83,80,.16)"),
                          dict(range=[45, 55], color="rgba(139,149,167,.14)"),
                          dict(range=[55, 100], color="rgba(38,166,154,.16)")])))
    fig.add_annotation(x=0.5, y=0.02, text=f"<b>{label}</b>", showarrow=False, font=dict(size=13, color=color))
    return style(fig, height, legend=False).update_layout(margin=dict(l=30, r=30, t=18, b=4))


def sparkline(values: pd.Series, color: str, height: int = 64) -> go.Figure:
    fig = go.Figure(go.Scatter(x=values.index, y=values.values, mode="lines", line=dict(color=color, width=1.8),
                               fill="tozeroy", fillcolor=color.replace(")", ",.10)").replace("rgb", "rgba")
                               if color.startswith("rgb") else _hex_alpha(color, .12),
                               hovertemplate="%{x|%d-%m-%Y}<br>%{y:,.2f}<extra></extra>"))
    lo, hi = float(values.min()), float(values.max())
    pad = (hi - lo) * 0.1 or 1
    fig.update_yaxes(visible=False, range=[lo - pad, hi + pad])
    fig.update_xaxes(visible=False)
    return style(fig, height, legend=False).update_layout(margin=dict(l=0, r=0, t=0, b=0))


def _hex_alpha(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}
