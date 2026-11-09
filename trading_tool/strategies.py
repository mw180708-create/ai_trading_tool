"""Strategieën als data: twee typen, sjablonen, validatie en één run-functie.

Type "smc"   : Smart Money / POI-model (het Trading Plan 2026-2028), volledig instelbaar.
Type "rules" : zelf samengestelde regels met indicatoren (zie rules_engine.py).
"""
from __future__ import annotations

import copy
import secrets
from dataclasses import asdict, fields
from datetime import datetime, timezone

import pandas as pd

from .backtester import Backtester, BacktestResult
from .config import TF_MINUTES, CostConfig, RiskConfig, StrategyConfig
from .data_loader import MultiTimeframeData
from .rules_engine import (TARGET_TYPES, describe_condition, normalize_rules, run_rules_backtest,
                           validate_rules)

TYPES = {"smc": "Smart Money (POI & liquiditeit)", "rules": "Indicatoren & regels"}
SMC_KEYS = ["bias_combos", "poi_timeframes", "scalp_poi_timeframes", "swing_poi_timeframes", "confirmation_tf",
            "min_rr", "adaptive_rr", "confirmation_mode", "tp_source", "liquidity_mode", "be_trigger_rr_swing",
            "be_trigger_rr_intraday", "sl_timeframe", "liquidity_window", "max_pois_per_tf", "arm_timeout_bars"]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def new_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3)


def smc_defaults() -> dict:
    d = asdict(StrategyConfig())
    missing = [k for k in SMC_KEYS if k not in d]
    if missing:   # zou nooit mogen gebeuren; duidelijke melding i.p.v. een kale KeyError
        raise RuntimeError(f"Verouderde instellingen geladen (mist {', '.join(missing)}). Herstart de app.")
    return {k: d[k] for k in SMC_KEYS}


def smc_config(params: dict) -> StrategyConfig:
    known = {f.name for f in fields(StrategyConfig)}
    base = asdict(StrategyConfig())
    base.update({k: v for k, v in (params or {}).items() if k in known})
    return StrategyConfig(**base)


def _op(ind, tf=None, **params):
    d = {"ind": ind, "params": params}
    if tf:
        d["tf"] = tf
    return d


TEMPLATES: dict[str, dict] = {
    "trading_plan": {
        "name": "Trading Plan 2026-2028", "type": "smc", "risk_pct": 1.0,
        "description": "Multi-timeframe bias (liquiditeit + balance level), POI-in-POI entry, SL op 1H protected "
                       "level, TP op de eerstvolgende liquiditeit, BE bij 2R (swing) / 4R (intraday).",
        "params": smc_defaults(),
    },
    "ema_cross": {
        "name": "EMA-crossover 20/50 met trendfilter", "type": "rules", "risk_pct": 1.0,
        "description": "Long als EMA 20 boven EMA 50 kruist en de prijs boven de 1D EMA 200 staat (short andersom).",
        "params": normalize_rules({
            "signal_tf": "1H", "direction": "both",
            "long": {"logic": "all", "conditions": [
                {"left": _op("ema", length=20), "op": "crosses_above", "right": _op("ema", length=50)},
                {"left": _op("close"), "op": ">", "right": _op("ema", "1D", length=200)}]},
            "short": {"logic": "all", "conditions": [
                {"left": _op("ema", length=20), "op": "crosses_below", "right": _op("ema", length=50)},
                {"left": _op("close"), "op": "<", "right": _op("ema", "1D", length=200)}]},
            "stop": {"type": "atr", "value": 2.0, "length": 14}, "target": {"type": "rr", "value": 2.0}}),
    },
    "rsi_reversion": {
        "name": "RSI terugkeer naar het gemiddelde", "type": "rules", "risk_pct": 1.0,
        "description": "Long als de RSI(14) weer boven 30 komt in een uptrend (prijs > SMA 200), short andersom.",
        "params": normalize_rules({
            "signal_tf": "4H", "direction": "both",
            "long": {"logic": "all", "conditions": [
                {"left": _op("rsi", length=14), "op": "crosses_above", "right": _op("value", value=30)},
                {"left": _op("close"), "op": ">", "right": _op("sma", length=200)}]},
            "short": {"logic": "all", "conditions": [
                {"left": _op("rsi", length=14), "op": "crosses_below", "right": _op("value", value=70)},
                {"left": _op("close"), "op": "<", "right": _op("sma", length=200)}]},
            "stop": {"type": "atr", "value": 1.5, "length": 14}, "target": {"type": "rr", "value": 1.5}}),
    },
    "donchian": {
        "name": "Donchian breakout (trendvolger)", "type": "rules", "risk_pct": 1.0,
        "description": "Long bij een close boven de hoogste high van 20 dagen, short onder de laagste low. "
                       "Geen vaste TP: een trailing stop van 3× ATR laat winst doorlopen.",
        "params": normalize_rules({
            "signal_tf": "1D", "direction": "both",
            "long": {"logic": "all", "conditions": [
                {"left": _op("close"), "op": ">", "right": _op("highest", length=20)}]},
            "short": {"logic": "all", "conditions": [
                {"left": _op("close"), "op": "<", "right": _op("lowest", length=20)}]},
            "stop": {"type": "atr", "value": 2.0, "length": 20}, "target": {"type": "none", "value": 0},
            "trailing_atr": 3.0, "trailing_length": 20}),
    },
    "blank": {
        "name": "Nieuwe strategie (leeg)", "type": "rules", "risk_pct": 1.0, "description": "",
        "params": normalize_rules({"long": {"logic": "all", "conditions": [
            {"left": _op("close"), "op": "crosses_above", "right": _op("sma", length=50)}]},
            "direction": "long"}),
    },
}


def from_template(key: str, owner: str) -> dict:
    t = copy.deepcopy(TEMPLATES[key])
    return {"id": new_id(), "owner": owner, "public": False, "created": now_iso(), "updated": now_iso(),
            "template": key, **t}


def normalize(strategy: dict) -> dict:
    s = copy.deepcopy(strategy)
    s.setdefault("type", "rules")
    s.setdefault("name", "Naamloze strategie")
    s.setdefault("description", "")
    s.setdefault("risk_pct", 1.0)
    s.setdefault("public", False)
    if s["type"] == "smc":
        base = smc_defaults()
        base.update({k: v for k, v in (s.get("params") or {}).items() if k in SMC_KEYS})
        s["params"] = base
    else:
        s["params"] = normalize_rules(s.get("params"))
    return s


def validate(strategy: dict) -> list[str]:
    s = normalize(strategy)
    errs = []
    if not str(s.get("name", "")).strip():
        errs.append("Geef de strategie een naam.")
    if not 0.01 <= float(s.get("risk_pct", 1)) <= 10:
        errs.append("Risico per trade moet tussen 0,01% en 10% liggen.")
    if s["type"] == "rules":
        errs += validate_rules(s["params"])
    elif s["type"] == "smc":
        p = s["params"]
        if not p["bias_combos"]:
            errs.append("Kies minstens één timeframe-combinatie voor de bias.")
        for combo, kind in p["bias_combos"]:
            if not combo or any(t not in TF_MINUTES for t in combo) or kind not in ("standard", "scalp"):
                errs.append(f"Ongeldige combinatie: {combo}")
        if not p["poi_timeframes"]:
            errs.append("Kies minstens één POI-timeframe.")
        for t in p["poi_timeframes"]:
            c = p["confirmation_tf"].get(t)
            if c not in TF_MINUTES:
                errs.append(f"Kies een confirmatie-timeframe voor de {t} POI.")
            elif TF_MINUTES[c] >= TF_MINUTES[t]:
                errs.append(f"De confirmatie voor de {t} POI moet op een lagere timeframe ({c} is niet lager).")
    else:
        errs.append(f"Onbekend strategietype: {s['type']}")
    return errs


def describe(strategy: dict) -> list[str]:
    s = normalize(strategy)
    p = s["params"]
    out = [f"Type: {TYPES.get(s['type'], s['type'])} · risico {float(s['risk_pct']):g}% per trade"]
    if s["type"] == "smc":
        out.append("Bias-combinaties: " + ", ".join("+".join(c) + (" (scalp)" if k == "scalp" else "")
                                                  for c, k in p["bias_combos"]))
        out.append("POI → confirmatie: " + ", ".join(f"{t}→{p['confirmation_tf'].get(t, '?')}" for t in p["poi_timeframes"]))
        out.append(f"Min. RR {p['min_rr']:g}{' (dynamisch)' if p['adaptive_rr'] else ''} · BE swing {p['be_trigger_rr_swing']:g}R"
                   f" · BE intraday {p['be_trigger_rr_intraday']:g}R")
        return out
    sig = p["signal_tf"]
    out.append(f"Signalen op {sig} · richting: {dict(long='alleen long', short='alleen short', both='long en short')[p['direction']]}")
    for side in ("long", "short"):
        if p["direction"] in (side, "both") and p[side]["conditions"]:
            joiner = " EN " if p[side].get("logic", "all") == "all" else " OF "
            out.append(f"{side.capitalize()}: " + joiner.join(describe_condition(c, sig) for c in p[side]["conditions"]))
    stp, tgt = p["stop"], p["target"]
    stop_txt = {"atr": f"{stp['value']:g}× ATR({stp.get('length', 14)})", "percent": f"{stp['value']:g}%",
                "swing": f"laagste/hoogste van {int(stp['value'])} candles", "fixed": f"{stp['value']:g} punten"}[stp["type"]]
    tgt_txt = {"rr": f"{tgt['value']:g}R", "atr": f"{tgt['value']:g}× ATR", "percent": f"{tgt['value']:g}%",
               "fixed": f"{tgt['value']:g} punten", "none": "geen vaste TP"}.get(tgt["type"], TARGET_TYPES.get(tgt["type"]))
    extra = []
    if p.get("breakeven_r"):
        extra.append(f"BE bij {p['breakeven_r']:g}R")
    if p.get("trailing_atr"):
        extra.append(f"trailing {p['trailing_atr']:g}× ATR")
    if p.get("max_bars"):
        extra.append(f"max {p['max_bars']} candles")
    if p.get("exit_on_opposite"):
        extra.append("exit bij tegengesteld signaal")
    out.append(f"Stop loss: {stop_txt} · take profit: {tgt_txt}" + (" · " + ", ".join(extra) if extra else ""))
    return out


def run_strategy(strategy: dict, mtf: MultiTimeframeData, balance: float, costs: CostConfig,
                 start: pd.Timestamp | None = None) -> BacktestResult:
    s = normalize(strategy)
    errs = validate(s)
    if errs:
        raise ValueError(" ".join(errs))
    risk = RiskConfig(initial_balance=float(balance), risk_per_trade=float(s["risk_pct"]) / 100)
    if s["type"] == "smc":
        return Backtester(mtf, smc_config(s["params"]), risk, costs, start=start, verbose=False).run()
    return run_rules_backtest(mtf, s["params"], risk, costs, start=start, name=s["name"])


def required_timeframes(strategy: dict) -> list[str]:
    """Timeframes die de strategie nodig heeft (om de gebruiker te waarschuwen)."""
    s = normalize(strategy)
    p = s["params"]
    if s["type"] == "smc":
        tfs = {t for c, _ in p["bias_combos"] for t in c} | set(p["poi_timeframes"]) | set(p["confirmation_tf"].values())
    else:
        tfs = {p["signal_tf"]}
        for side in ("long", "short"):
            for c in p[side]["conditions"]:
                tfs |= {c["left"].get("tf") or p["signal_tf"], c["right"].get("tf") or p["signal_tf"]}
    return sorted(tfs, key=lambda t: -TF_MINUTES[t])
