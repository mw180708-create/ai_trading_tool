"""wng - opmaak: rustig, neutraal, minimalistisch. Eén accentkleur, platte panelen, dunne randen."""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parents[1] / "assets"
LOGO = ASSETS / "wng-logo.svg"
ICON = ASSETS / "wng-icon.svg"

# Kleuren
SERIES = {"TOTAAL": "#a1a1aa"}                       # per markt: zie series_color()
_CATEGORICAL = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"]   # gevalideerd, donker
UP, DOWN, NEUTRAL = "#26a69a", "#ef5350", "#71717a"
ACCENT = "#5b7cfa"
EMA_FAST, EMA_SLOW = "#c8a24a", "#5b7cfa"


def series_color(name: str, order: list[str] | None = None) -> str:
    if name in SERIES:
        return SERIES[name]
    order = order or [name]
    i = order.index(name) if name in order else 0
    return _CATEGORICAL[i % len(_CATEGORICAL)]


CSS = """
<style>
:root{
  --bg:#0b0b0c; --surface:#111113; --surface-2:#161618; --line:#222226; --line-2:#2c2c31;
  --text:#ececee; --muted:#8b8b94; --subtle:#5f5f69; --accent:#5b7cfa; --up:#26a69a; --down:#ef5350;
}
.stApp{background:var(--bg);}
.block-container{padding-top:4.2rem; padding-bottom:2rem; max-width:1400px;}
header[data-testid="stHeader"]{background:rgba(11,11,12,.92); backdrop-filter:blur(8px); border-bottom:1px solid var(--line);}
h1,h2,h3,h4{letter-spacing:-.01em;}
p, li{line-height:1.55;}

/* panelen: containers met een key die met "panel" begint */
div[class*="st-key-panel"]{
  background:var(--surface); border:1px solid var(--line) !important; border-radius:8px; padding:16px 18px;
}
div[class*="st-key-panelglow"]{border-color:var(--line-2) !important;}

/* rustige multiselect-labels i.p.v. felle blokken */
span[data-baseweb="tag"]{background:var(--surface-2) !important; border:1px solid var(--line-2) !important;}
span[data-baseweb="tag"] span{color:var(--text) !important;}

/* meldingen: ingetogen, alleen een dun gekleurd randje */
div[data-testid="stAlertContainer"]{background:var(--surface) !important; border:1px solid var(--line) !important;
  border-left:2px solid var(--subtle) !important; border-radius:6px !important; padding:10px 14px !important;}
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]){border-left-color:var(--up) !important;}
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]){border-left-color:#c8a24a !important;}
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]){border-left-color:var(--down) !important;}
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]){border-left-color:var(--accent) !important;}
[data-testid^="stAlertContent"], [data-testid^="stAlertContent"] p, [data-testid^="stAlertContent"] strong{color:var(--text) !important;}
[data-testid^="stAlertContent"] svg, div[data-testid="stAlertContainer"] [data-testid="stAlertDynamicIcon"]{display:none;}

/* kop, account, melding, voettekst */
.page-title{font-size:1.3rem; font-weight:600; letter-spacing:-.015em; margin:0;}
div[class*="st-key-acct"]{display:flex; justify-content:flex-end; padding-top:4px;}
div[class*="st-key-acct"] button{border-color:transparent !important; background:transparent !important; color:var(--muted) !important;}
div[class*="st-key-acct"] button:hover{color:var(--text) !important;}
.notice{font-size:.85rem; color:#d6c08a; padding:8px 12px; border:1px solid rgba(200,162,74,.3); border-radius:6px;
  background:rgba(200,162,74,.06);}
.footer{margin-top:56px; padding-top:16px; border-top:1px solid var(--line); color:var(--subtle); font-size:.76rem;
  display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px;}
.footer a{color:var(--subtle); text-decoration:underline; text-underline-offset:2px;}
div[class*="st-key-cookie_sink"]{display:none;}

/* inloggen */
.auth-title{font-size:1.5rem; font-weight:600; letter-spacing:-.02em; margin-top:7vh;}
.auth-sub{color:var(--muted); font-size:.92rem; margin:6px 0 22px 0;}
.auth-divider{display:flex; align-items:center; gap:12px; color:var(--subtle); font-size:.78rem; margin:8px 0 12px 0;}
.auth-divider:before, .auth-divider:after{content:""; flex:1; height:1px; background:var(--line);}

/* kerncijfers in één strook */
.kpis{display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); border:1px solid var(--line);
  border-radius:8px; background:var(--surface);}
.kpis > div{padding:14px 18px; border-left:1px solid var(--line);}
.kpis > div:first-child{border-left:none;}

/* tabbladen */
.stTabs [data-baseweb="tab-list"]{gap:22px; border-bottom:1px solid var(--line);}
.stTabs [data-baseweb="tab"]{padding:8px 0; font-weight:500;}

.page-sub{color:var(--muted); font-size:.9rem; margin-top:2px;}
.ptitle{font-size:.8rem; font-weight:500; color:var(--muted); margin:0 0 10px 0;}

.kpi-label{font-size:.78rem; font-weight:500; color:var(--muted);}
.kpi-value{font-size:1.55rem; font-weight:600; letter-spacing:-.02em; line-height:1.3; margin-top:2px; white-space:nowrap;
  font-variant-numeric:tabular-nums;}
.kpi-value.sm{font-size:1.1rem; white-space:normal; overflow-wrap:anywhere;}
.kpi-sub{font-size:.82rem; color:var(--muted); margin-top:2px;}
.up{color:var(--up) !important;} .down{color:var(--down) !important;} .muted{color:var(--muted) !important;}
.kv{display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--line); font-size:.88rem;}
.kv:last-child{border-bottom:none;} .kv b{font-weight:600; font-variant-numeric:tabular-nums;}

.row{display:grid; grid-template-columns:40px 1fr 1fr 84px; gap:8px; align-items:center; padding:8px 0;
  border-bottom:1px solid var(--line); font-size:.85rem;}
.row:last-child{border-bottom:none;}
.row.head{color:var(--subtle); font-size:.74rem; padding-bottom:6px;}
.row.two{grid-template-columns:16px 1fr;}
.tf{font-weight:600; font-variant-numeric:tabular-nums;}
.tag{display:inline-block; padding:1px 8px; border-radius:4px; font-size:.75rem; font-weight:500; color:var(--muted);
  border:1px solid var(--line-2); white-space:nowrap;}
.tag.bull{color:var(--up); border-color:rgba(38,166,154,.35);}
.tag.bear{color:var(--down); border-color:rgba(239,83,80,.35);}
.tag.na{opacity:.45;}
.dot{display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--subtle); vertical-align:middle;}
.dot.up{background:var(--up);} .dot.down{background:var(--down);} .dot.accent{background:var(--accent);}
.dot.warn{background:#c8a24a;}

.status-title{font-weight:600; font-size:1rem; display:flex; align-items:center; gap:8px;}
.status-detail{color:#b4b4bc; font-size:.86rem; margin-top:6px; line-height:1.5;}

.badge{display:inline-flex; align-items:center; gap:6px; padding:2px 9px; border-radius:4px; font-size:.75rem; font-weight:500;
  color:var(--muted); border:1px solid var(--line-2);}
.badge.ok{color:var(--up); border-color:rgba(38,166,154,.35);}
.badge.warn{color:#c8a24a; border-color:rgba(200,162,74,.35);}
.badge.info{color:var(--muted);}

.meter{height:4px; background:var(--line-2); border-radius:2px; overflow:hidden; margin-top:10px;}
.meter > div{height:100%; background:var(--text);}

.mkt{display:flex; justify-content:space-between; align-items:baseline;}
.mkt-name{font-weight:500; color:var(--muted); font-size:.85rem;}
.mkt-price{font-size:1.15rem; font-weight:600; font-variant-numeric:tabular-nums;}

.steps{list-style:none; padding:0; margin:0; counter-reset:s;}
.steps li{counter-increment:s; padding:6px 0 6px 28px; position:relative; color:#c4c4cc;}
.steps li:before{content:counter(s); position:absolute; left:0; top:6px; color:var(--subtle); font-weight:600;
  font-variant-numeric:tabular-nums;}
.small-note{color:var(--muted); font-size:.8rem;}
.hero{font-size:2.1rem; font-weight:600; letter-spacing:-.03em; line-height:1.15;}
.hero-sub{color:var(--muted); font-size:1rem; margin-top:14px; max-width:520px; line-height:1.6;}
.feature{padding:12px 0; border-top:1px solid var(--line);}
.feature b{font-weight:600;} .feature span{color:var(--muted); font-size:.9rem;}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x))


def ptitle(text: str) -> None:
    st.markdown(f'<div class="ptitle">{esc(text)}</div>', unsafe_allow_html=True)


def kpi_strip(cards: list[str]) -> None:
    st.markdown('<div class="kpis">' + "".join(f"<div>{c}</div>" for c in cards) + "</div>", unsafe_allow_html=True)


def footer() -> None:
    st.markdown('<div class="footer"><span>wng</span><span>Grafieken: <a href="https://www.tradingview.com/" '
                'target="_blank" rel="noopener">TradingView Lightweight Charts</a> · Een backtest is geen garantie '
                'voor de toekomst en geen financieel advies.</span></div>', unsafe_allow_html=True)


def page_header(title: str, sub: str | None = None) -> None:
    st.markdown(f'<div class="page-title">{esc(title)}</div>' + (f'<div class="page-sub">{esc(sub)}</div>' if sub else ""),
                unsafe_allow_html=True)


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
    return f"{v:,.5f}" if abs(v) < 10 else f"{v:,.2f}"


def html_block(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)
