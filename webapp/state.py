"""Gedeelde status: databibliotheek, GitHub-koppeling, cached data en backtest-resultaten."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from trading_tool.backtester import BacktestResult
from trading_tool.config import StrategyConfig
from trading_tool.data_loader import MultiTimeframeData, build_multi_timeframe
from trading_tool.live import LiveState, analyze_live
from trading_tool.storage import DataStore, make_github_sync
from trading_tool.synthetic import demo_dataset

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "mw180708-create/ai_trading_tool"
SYMBOLS = ["BTCUSD", "XAUUSD"]


# --------------------------------------------------------------------------- #
# Config / opslag
# --------------------------------------------------------------------------- #
def _read_secrets() -> tuple[dict, str | None]:
    """Alle Streamlit-secrets als dict + eventuele fout (bv. ongeldige TOML)."""
    try:
        return {k: st.secrets[k] for k in st.secrets.keys()}, None
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "pars" in msg.lower() or "expected" in msg.lower() or "invalid" in msg.lower():
            return {}, msg.split(":", 1)[-1].strip() if "secrets.toml" in msg else msg
        return {}, None   # geen secrets ingesteld


def secret(key: str, default: str | None = None) -> str | None:
    sec, _ = _read_secrets()
    if key in sec:
        return str(sec[key])
    return os.environ.get(key, default)


def clean_token(tok) -> str | None:
    if tok is None:
        return None
    t = str(tok).strip().strip('"').strip("'").strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    t = t.replace(" ", "").replace("\n", "")
    return t or None


def clean_repo(repo: str | None) -> str:
    r = (repo or DEFAULT_REPO).strip().strip('"').strip("'")
    for pre in ("https://github.com/", "http://github.com/", "github.com/"):
        if r.lower().startswith(pre):
            r = r[len(pre):]
    r = r.removesuffix(".git").strip("/")
    return r or DEFAULT_REPO


def _token_from_secrets(sec: dict) -> str | None:
    """Accepteer verschillende schrijfwijzen: GITHUB_TOKEN, github_token, token, [github] token = ..."""
    for k in ("GITHUB_TOKEN", "github_token", "Github_Token", "GH_TOKEN", "TOKEN", "token"):
        if k in sec and isinstance(sec[k], str):
            return clean_token(sec[k])
    for sect in ("github", "GITHUB", "GitHub"):
        if sect in sec and hasattr(sec[sect], "get"):
            v = sec[sect].get("token") or sec[sect].get("GITHUB_TOKEN")
            if v:
                return clean_token(v)
    return None


@st.cache_resource(show_spinner=False)
def runtime_cfg() -> dict:
    """Token dat op de website is geplakt (geldig tot de website herstart)."""
    return {}


def _cfg() -> tuple[str | None, str, str, str]:
    sec, _ = _read_secrets()
    tok = _token_from_secrets(sec)
    source = "secrets"
    if not tok and runtime_cfg().get("token"):
        tok, source = runtime_cfg()["token"], "website"
    if not tok and os.environ.get("AI_TRADING_GITHUB_TOKEN"):
        tok, source = clean_token(os.environ["AI_TRADING_GITHUB_TOKEN"]), "omgeving"
    repo = sec.get("GITHUB_REPO") or sec.get("github_repo") or runtime_cfg().get("repo") or DEFAULT_REPO
    if "github" in sec and hasattr(sec["github"], "get") and sec["github"].get("repo"):
        repo = sec["github"]["repo"]
    return tok, clean_repo(str(repo)), str(sec.get("GITHUB_BRANCH", "main")), source


@st.cache_resource(show_spinner=False, ttl=1800)
def _store(token: str | None, repo: str, branch: str, source: str) -> tuple[DataStore, dict]:
    """DataStore + status van de GitHub-koppeling (token wordt eerst gecontroleerd)."""
    gh = make_github_sync(token, repo, branch)
    status = {"configured": gh is not None, "ok": False, "msg": "Geen token ingesteld.", "source": source,
              "repo": repo}
    if gh is not None:
        ok, msg = gh.check()
        status.update(ok=ok, msg=msg)
    return DataStore(ROOT, github=gh if status["ok"] else None), status


def store() -> DataStore:
    return _store(*_cfg())[0]


def github_status() -> dict:
    st_ = dict(_store(*_cfg())[1])
    st_["secrets_error"] = _read_secrets()[1]
    return st_


def test_token(token: str, repo: str | None = None) -> tuple[bool, str]:
    gh = make_github_sync(clean_token(token), clean_repo(repo), "main")
    if gh is None:
        return False, "Plak eerst een token."
    return gh.check()


def use_token_now(token: str, repo: str | None = None) -> None:
    runtime_cfg()["token"] = clean_token(token)
    runtime_cfg()["repo"] = clean_repo(repo)
    _store.clear()


def reset_github() -> None:
    _store.clear()


def demo_on() -> bool:
    return bool(st.session_state.get("demo", False))


def fingerprint() -> str:
    return "demo" if demo_on() else store().fingerprint()


def symbols() -> list[str]:
    if demo_on():
        return SYMBOLS
    found = store().symbols()
    return [s for s in SYMBOLS if s in found] + [s for s in found if s not in SYMBOLS]


@st.cache_resource(show_spinner=False, max_entries=6)
def _mtf(symbol: str, fp: str) -> MultiTimeframeData | None:
    if fp == "demo":
        return demo_dataset(symbol, seed=SYMBOLS.index(symbol) if symbol in SYMBOLS else 0)
    src = store().load_symbol(symbol)
    return build_multi_timeframe(symbol, src) if src else None


def mtf(symbol: str) -> MultiTimeframeData | None:
    return _mtf(symbol, fingerprint())


@st.cache_resource(show_spinner=False, max_entries=8)
def _live(symbol: str, fp: str) -> LiveState | None:
    m = _mtf(symbol, fp)
    if m is None:
        return None
    try:
        return analyze_live(m, StrategyConfig())
    except Exception:  # noqa: BLE001
        return None


def live(symbol: str) -> LiveState | None:
    return _live(symbol, fingerprint())


# --------------------------------------------------------------------------- #
# Resultaten
# --------------------------------------------------------------------------- #
@dataclass
class Results:
    trades: pd.DataFrame
    equity: dict[str, pd.Series]
    initial: dict[str, float]
    stats: dict[str, dict]
    meta: dict = field(default_factory=dict)

    @property
    def symbols(self) -> list[str]:
        return list(self.equity)

    def views(self) -> list[str]:
        return self.symbols + (["TOTAAL"] if len(self.symbols) > 1 else [])

    def trades_for(self, view: str) -> pd.DataFrame:
        if self.trades.empty:
            return self.trades
        t = self.trades if view == "TOTAAL" else self.trades[self.trades["symbol"] == view]
        return t.sort_values("exit_time").reset_index(drop=True)

    def initial_for(self, view: str) -> float:
        return sum(self.initial.values()) if view == "TOTAAL" else self.initial[view]

    def equity_for(self, view: str) -> pd.Series:
        if view != "TOTAAL":
            return self.equity[view]
        curves = [s[~s.index.duplicated(keep="last")] for s in self.equity.values()]
        idx = curves[0].index
        for c in curves[1:]:
            idx = idx.union(c.index)
        return sum(c.reindex(idx).ffill().fillna(c.iloc[0]) for c in curves)


def results_from_backtests(res: list[BacktestResult], meta: dict) -> Results:
    trades = pd.concat([r.trades for r in res if not r.trades.empty], ignore_index=True) \
        if any(not r.trades.empty for r in res) else pd.DataFrame()
    return Results(trades, {r.symbol: r.equity for r in res}, {r.symbol: r.initial_balance for r in res},
                   {r.symbol: r.stats for r in res}, meta)


def persist_results(r: Results):
    eq = pd.concat([pd.DataFrame({"symbol": s, "time": e.index, "equity": e.values}) for s, e in r.equity.items()],
                   ignore_index=True)
    meta = dict(r.meta, initial=r.initial, stats=r.stats)
    if demo_on() or r.meta.get("demo"):
        return None  # demo-resultaten niet opslaan
    return store().save_results(r.trades, eq, meta)


def get_results() -> Results | None:
    if "results" in st.session_state:
        return st.session_state["results"]
    loaded = store().load_results()
    res = None
    if loaded:
        trades, eq, meta = loaded
        equity = {s: pd.Series(g["equity"].to_numpy(), index=pd.DatetimeIndex(g["time"]), name=s)
                  for s, g in eq.groupby("symbol", sort=False)}
        if equity:
            res = Results(trades, equity, {k: float(v) for k, v in meta.get("initial", {}).items()},
                          meta.get("stats", {}), meta)
    st.session_state["results"] = res
    return res


def set_results(r: Results | None) -> None:
    st.session_state["results"] = r


def flash(msg: str, kind: str = "success") -> None:
    st.session_state.setdefault("_flash", []).append((kind, msg))


def show_flash() -> None:
    for kind, msg in st.session_state.pop("_flash", []):
        getattr(st, kind)(msg)


def daily_change(m: MultiTimeframeData) -> tuple[float, float, pd.Series]:
    """(laatste prijs, verandering % t.o.v. vorige dag-close, closes laatste 60 dagen)."""
    d = m["1D"] if "1D" in m else m[m.base_tf]
    last = float(m[m.base_tf]["close"].iloc[-1])
    prev = float(d["close"].iloc[-2]) if len(d) > 1 else last
    return last, (last / prev - 1) * 100 if prev else 0.0, d["close"].iloc[-60:]


def fmt_bias(v) -> tuple[str, str]:
    if v is None:
        return "–", "na"
    return {1: ("▲ Bull", "bull"), -1: ("▼ Bear", "bear"), 0: ("● 50/50", "")}[int(v)]


def np_float(x) -> float:
    return float(np.asarray(x).item()) if np.ndim(x) == 0 else float(x)
