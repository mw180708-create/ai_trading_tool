"""Opmaak: donker trading-dashboard thema + kleine HTML-bouwstenen (kaarten, chips, badges)."""
from __future__ import annotations

import html

import streamlit as st

# Kleuren (categorisch gevalideerd voor het donkere oppervlak)
SERIES = {"BTCUSD": "#3987e5", "XAUUSD": "#d95926", "TOTAAL": "#c3c2b7"}
UP, DOWN, NEUTRAL = "#26a69a", "#ef5350", "#8b95a7"
ACCENT, GOLD = "#3b9eff", "#e8b339"
SYMBOL_NAME = {"BTCUSD": "Bitcoin · BTC/USD", "XAUUSD": "Goud · XAU/USD"}
SYMBOL_ICON = {"BTCUSD": "₿", "XAUUSD": "Au"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root{
  --bg:#0a0e15; --panel:#111722; --panel2:#151d2b; --line:rgba(110,150,230,.16);
  --text:#e6e9ef; --muted:#8b95a7; --accent:#3b9eff; --gold:#e8b339; --up:#26a69a; --down:#ef5350;
}
.stApp{
  background:
    radial-gradient(1100px 520px at 75% -12%, rgba(59,158,255,.13), transparent 60%),
    radial-gradient(800px 480px at -8% 108%, rgba(232,179,57,.07), transparent 60%),
    var(--bg);
}
html, body, .stApp, .stMarkdown, button, input, textarea, select{font-family:Inter, system-ui, sans-serif;}
.block-container{padding-top:4.2rem; padding-bottom:3rem; max-width:1520px;}
h1, h2, h3, h4{font-family:'Space Grotesk', Inter, sans-serif !important; letter-spacing:.01em;}
header[data-testid="stHeader"]{background:rgba(10,14,21,.82); backdrop-filter:blur(10px); border-bottom:1px solid var(--line);}

/* Glas-panelen: alle containers met key die begint met "panel" */
div[class*="st-key-panel"]{
  background:linear-gradient(180deg, rgba(21,29,43,.92), rgba(15,21,32,.92));
  border:1px solid var(--line) !important; border-radius:16px; padding:16px 18px 14px 18px;
  box-shadow:0 0 0 1px rgba(59,158,255,.04), 0 10px 30px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.03);
}
div[class*="st-key-panelglow"]{border-color:rgba(59,158,255,.35) !important;
  box-shadow:0 0 24px rgba(59,158,255,.12), 0 10px 30px rgba(0,0,0,.35);}

.ptitle{font-size:.74rem; font-weight:600; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin:0 0 8px 0;}
.brand{display:flex; align-items:center; gap:12px; margin:0 0 4px 0;}
.brand-logo{width:40px; height:40px; border-radius:11px; display:grid; place-items:center; font-weight:700;
  background:linear-gradient(135deg, var(--gold), #f6d36b); color:#151006; font-family:'Space Grotesk'; font-size:1.05rem;
  box-shadow:0 0 22px rgba(232,179,57,.35);}
.brand-name{font-family:'Space Grotesk'; font-size:1.55rem; font-weight:700; line-height:1.05;}
.brand-name span{color:var(--gold);}
.brand-sub{color:var(--muted); font-size:.82rem; letter-spacing:.14em; text-transform:uppercase;}

.kpi{padding:2px 0;}
.kpi-label{font-size:.72rem; font-weight:600; letter-spacing:.12em; text-transform:uppercase; color:var(--muted);}
.kpi-value{font-family:'Space Grotesk'; font-size:1.75rem; font-weight:600; line-height:1.25; margin-top:2px; white-space:nowrap;}
.kpi-value.sm{font-size:1.3rem;}
.kpi-sub{font-size:.85rem; color:var(--muted); margin-top:2px;}
.up{color:var(--up) !important;} .down{color:var(--down) !important;} .muted{color:var(--muted) !important;}
.kv{display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px dashed rgba(139,149,167,.15); font-size:.92rem;}
.kv:last-child{border-bottom:none;} .kv b{font-family:'Space Grotesk'; font-weight:600;}

.engine-row{display:grid; grid-template-columns:42px 1fr 1fr 92px; gap:6px; align-items:center; padding:7px 0;
  border-bottom:1px solid rgba(139,149,167,.10); font-size:.86rem;}
.engine-row:last-child{border-bottom:none;}
.engine-head{color:var(--muted); font-size:.68rem; letter-spacing:.1em; text-transform:uppercase; padding-bottom:4px;}
.tf{font-family:'Space Grotesk'; font-weight:600;}
.chip{display:inline-flex; align-items:center; gap:4px; padding:2px 8px; border-radius:999px; font-size:.76rem; font-weight:600;
  border:1px solid rgba(139,149,167,.25); color:var(--muted); background:rgba(139,149,167,.08); white-space:nowrap;}
.chip.bull{color:var(--up); border-color:rgba(38,166,154,.45); background:rgba(38,166,154,.12);}
.chip.bear{color:var(--down); border-color:rgba(239,83,80,.45); background:rgba(239,83,80,.12);}
.chip.na{opacity:.5;}

.decision{border-left:3px solid var(--muted); padding:8px 0 4px 12px; margin-top:4px;}
.decision.signal{border-color:var(--up);} .decision.wait_confirm{border-color:var(--gold);}
.decision.wait_poi{border-color:var(--accent);} .decision.none{border-color:var(--muted);}
.decision-title{font-family:'Space Grotesk'; font-size:1.15rem; font-weight:700; letter-spacing:.03em;}
.decision-detail{color:#c4cad6; font-size:.88rem; margin-top:4px; line-height:1.45;}

.badge{display:inline-flex; align-items:center; gap:6px; padding:4px 11px; border-radius:999px; font-size:.78rem; font-weight:600;
  border:1px solid var(--line); background:rgba(21,29,43,.9);}
.badge.ok{color:var(--up); border-color:rgba(38,166,154,.4);}
.badge.warn{color:var(--gold); border-color:rgba(232,179,57,.4);}
.badge.info{color:var(--accent); border-color:rgba(59,158,255,.4);}

.mkt{display:flex; justify-content:space-between; align-items:flex-end;}
.mkt-name{font-weight:600;} .mkt-price{font-family:'Space Grotesk'; font-size:1.25rem; font-weight:600;}
.coin{display:inline-grid; place-items:center; width:26px; height:26px; border-radius:50%; font-size:.78rem; font-weight:700;
  margin-right:8px; vertical-align:middle;}
.coin.BTCUSD{background:rgba(57,135,229,.18); color:#7fb2f0; border:1px solid rgba(57,135,229,.5);}
.coin.XAUUSD{background:rgba(217,89,38,.16); color:#f09a74; border:1px solid rgba(217,89,38,.5);}

.steps{counter-reset:s; list-style:none; padding:0; margin:0;}
.steps li{counter-increment:s; position:relative; padding:6px 0 6px 38px; color:#c4cad6;}
.steps li:before{content:counter(s); position:absolute; left:0; top:4px; width:26px; height:26px; border-radius:50%;
  display:grid; place-items:center; font-weight:700; font-size:.8rem; color:var(--accent);
  border:1px solid rgba(59,158,255,.5); background:rgba(59,158,255,.1);}
div[data-testid="stMetric"]{background:transparent;}
.stTabs [data-baseweb="tab-list"]{gap:6px;}
.small-note{color:var(--muted); font-size:.8rem;}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x))


def ptitle(text: str) -> None:
    st.markdown(f'<div class="ptitle">{esc(text)}</div>', unsafe_allow_html=True)


def kpi(label: str, value: str, sub: str | None = None, tone: str | None = None, small: bool = False) -> str:
    sub_html = f'<div class="kpi-sub {tone or ""}">{esc(sub)}</div>' if sub else ""
    return (f'<div class="kpi"><div class="kpi-label">{esc(label)}</div>'
            f'<div class="kpi-value {"sm" if small else ""}">{esc(value)}</div>{sub_html}</div>')


def kv(rows: list[tuple[str, str, str | None]]) -> str:
    return "".join(f'<div class="kv"><span class="muted">{esc(k)}</span><b class="{t or ""}">{esc(v)}</b></div>'
                   for k, v, t in rows)


def badge(text: str, tone: str = "info") -> str:
    return f'<span class="badge {tone}">{esc(text)}</span>'


def tone_of(v: float, eps: float = 1e-9) -> str:
    return "up" if v > eps else ("down" if v < -eps else "muted")


def money(v: float, decimals: int | None = None) -> str:
    sign = "-" if v < 0 else ""
    d = decimals if decimals is not None else (0 if abs(v) >= 1000 else 2)
    return f"{sign}${abs(v):,.{d}f}"


def price_fmt(v: float) -> str:
    return f"{v:,.2f}"


def html_block(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def brand() -> None:
    html_block('<div class="brand"><div class="brand-logo">AI</div><div>'
               '<div class="brand-name">AI <span>Trading</span> Tool</div>'
               '<div class="brand-sub">Trading Plan 2026-2028 · BTCUSD & XAUUSD</div></div></div>')
