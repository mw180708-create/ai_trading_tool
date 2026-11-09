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
def secret(key: str, default: str | None = None) -> str | None:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:  # noqa: BLE001 - geen secrets.toml aanwezig
        pass
    return os.environ.get(key, default)


@st.cache_resource(show_spinner=False, ttl=900)
def _store(token: str | None, repo: str, branch: str) -> tuple[DataStore, dict]:
    """DataStore + status van de GitHub-koppeling (token wordt eerst gecontroleerd)."""
    gh = make_github_sync(token, repo, branch)
    status = {"configured": gh is not None, "ok": False, "msg": "Geen GITHUB_TOKEN ingesteld."}
    if gh is not None:
        ok, msg = gh.check()
        status.update(ok=ok, msg=msg)
    return DataStore(ROOT, github=gh if status["ok"] else None), status


def _cfg() -> tuple[str | None, str, str]:
    return secret("GITHUB_TOKEN"), secret("GITHUB_REPO", DEFAULT_REPO), secret("GITHUB_BRANCH", "main")


def store() -> DataStore:
    return _store(*_cfg())[0]


def github_status() -> dict:
    return _store(*_cfg())[1]


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
