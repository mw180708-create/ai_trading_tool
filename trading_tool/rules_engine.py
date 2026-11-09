"""Regel-strategieën: zelf samen te stellen met indicatoren, zonder te programmeren.

Een strategie is pure data (JSON), dus veilig voor een website met veel gebruikers:

    {
      "signal_tf": "1H",                 # op welke timeframe signalen ontstaan
      "direction": "both",               # long / short / both
      "long":  {"logic": "all", "conditions": [ {left, op, right}, ... ]},
      "short": {"logic": "all", "conditions": [ ... ]},
      "stop":   {"type": "atr", "value": 2.0, "length": 14},     # atr | percent | swing | fixed
      "target": {"type": "rr",  "value": 2.0, "length": 14},     # rr | atr | percent | fixed | none
      "breakeven_r": 0, "trailing_atr": 0, "trailing_length": 14,
      "max_bars": 0, "exit_on_opposite": false,
      "session": {"start": 0, "end": 24}                        # uren UTC
    }

Operand: {"ind": "ema", "params": {"length": 50}, "tf": "1D"}   (tf optioneel = signal_tf)
Operatoren: > < >= <= crosses_above crosses_below

Lookahead-vrij: een signaal ontstaat bij de close van de signaal-candle, indicatoren van een
hogere timeframe gebruiken alleen de laatst gesloten candle van die timeframe. De simulatie
loopt bar-voor-bar op de fijnste data (SL en TP in dezelfde bar -> SL).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtester import BacktestResult
from .config import TF_MINUTES, TIMEFRAMES, CostConfig, RiskConfig
from .data_loader import MultiTimeframeData, to_numpy_ns

# key: (label, [(param, default, min, max)])
_MACD = [("fast", 12, 1, 200), ("slow", 26, 2, 400), ("signal", 9, 1, 100)]
_BB = [("length", 20, 2, 500), ("mult", 2.0, 0.1, 10.0)]
INDICATORS: dict[str, tuple[str, list[tuple[str, float, float, float]]]] = {
    "close": ("Close (slotkoers)", []),
    "open": ("Open", []),
    "high": ("High", []),
    "low": ("Low", []),
    "volume": ("Volume", []),
    "sma": ("SMA (gemiddelde)", [("length", 20, 1, 1000)]),
    "ema": ("EMA (exp. gemiddelde)", [("length", 20, 1, 1000)]),
    "rsi": ("RSI", [("length", 14, 2, 200)]),
    "atr": ("ATR", [("length", 14, 1, 500)]),
    "macd": ("MACD-lijn", _MACD),
    "macd_signal": ("MACD-signaallijn", _MACD),
    "macd_hist": ("MACD-histogram", _MACD),
    "bb_upper": ("Bollinger bovenband", _BB),
    "bb_mid": ("Bollinger midden", _BB),
    "bb_lower": ("Bollinger onderband", _BB),
    "highest": ("Hoogste high vorige N candles", [("length", 20, 1, 1000)]),
    "lowest": ("Laagste low vorige N candles", [("length", 20, 1, 1000)]),
    "stoch_k": ("Stochastic %K", [("length", 14, 1, 200), ("smooth", 3, 1, 50)]),
    "stoch_d": ("Stochastic %D", [("length", 14, 1, 200), ("smooth", 3, 1, 50), ("signal", 3, 1, 50)]),
    "change_pct": ("Verandering % over N candles", [("length", 1, 1, 500)]),
    "value": ("Vast getal", [("value", 50.0, -1e12, 1e12)]),
}
OPERATORS = {">": "groter dan", "<": "kleiner dan", ">=": "groter of gelijk aan", "<=": "kleiner of gelijk aan",
             "crosses_above": "kruist boven", "crosses_below": "kruist onder"}
STOP_TYPES = {"atr": "ATR × waarde", "percent": "% van de entry", "swing": "Laagste low / hoogste high van N candles",
              "fixed": "Vaste afstand (prijs)"}
TARGET_TYPES = {"rr": "Risk-to-Reward (× risico)", "atr": "ATR × waarde", "percent": "% van de entry",
                "fixed": "Vaste afstand (prijs)", "none": "Geen (exit via signaal/tijd/trailing)"}

DEFAULT_RULES: dict = {
    "signal_tf": "1H",
    "direction": "both",
    "long": {"logic": "all", "conditions": []},
    "short": {"logic": "all", "conditions": []},
    "stop": {"type": "atr", "value": 2.0, "length": 14},
    "target": {"type": "rr", "value": 2.0, "length": 14},
    "breakeven_r": 0.0,
    "trailing_atr": 0.0,
    "trailing_length": 14,
    "max_bars": 0,
    "exit_on_opposite": False,
    "session": {"start": 0, "end": 24},
}


def normalize_rules(spec: dict | None) -> dict:
    out = copy.deepcopy(DEFAULT_RULES)
    for k, v in (spec or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# Indicatoren
# --------------------------------------------------------------------------- #
def _p(params: dict, key: str, ind: str) -> float:
    for name, default, lo, hi in INDICATORS[ind][1]:
        if name == key:
            v = float(params.get(key, default))
            return min(max(v, lo), hi)
    raise KeyError(key)


def compute_indicator(df: pd.DataFrame, ind: str, params: dict | None = None) -> np.ndarray:
    params = params or {}
    c, h, l = df["close"], df["high"], df["low"]
    if ind in ("close", "open", "high", "low", "volume"):
        return df[ind].to_numpy(float)
    if ind == "value":
        return np.full(len(df), _p(params, "value", ind))
    n = int(_p(params, "length", ind)) if any(x[0] == "length" for x in INDICATORS[ind][1]) else 0
    if ind == "sma":
        s = c.rolling(n, min_periods=n).mean()
    elif ind == "ema":
        s = c.ewm(span=n, adjust=False, min_periods=n).mean()
    elif ind == "rsi":
        d = c.diff()
        up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        rs = up / dn.replace(0, np.nan)
        s = (100 - 100 / (1 + rs)).where(dn != 0, 100.0)
    elif ind == "atr":
        s = _atr(df, n)
    elif ind in ("macd", "macd_signal", "macd_hist"):
        f, sl, sg = (int(_p(params, k, ind)) for k in ("fast", "slow", "signal"))
        line = c.ewm(span=f, adjust=False).mean() - c.ewm(span=sl, adjust=False).mean()
        sig = line.ewm(span=sg, adjust=False).mean()
        s = {"macd": line, "macd_signal": sig, "macd_hist": line - sig}[ind]
        s = s.where(np.arange(len(c)) >= sl)
    elif ind in ("bb_upper", "bb_mid", "bb_lower"):
        m = _p(params, "mult", ind)
        mid = c.rolling(n, min_periods=n).mean()
        sd = c.rolling(n, min_periods=n).std(ddof=0)
        s = {"bb_upper": mid + m * sd, "bb_mid": mid, "bb_lower": mid - m * sd}[ind]
    elif ind == "highest":
        s = h.rolling(n, min_periods=n).max().shift(1)
    elif ind == "lowest":
        s = l.rolling(n, min_periods=n).min().shift(1)
    elif ind in ("stoch_k", "stoch_d"):
        sm = int(_p(params, "smooth", ind))
        ll, hh = l.rolling(n, min_periods=n).min(), h.rolling(n, min_periods=n).max()
        k = (100 * (c - ll) / (hh - ll).replace(0, np.nan)).rolling(sm, min_periods=sm).mean()
        s = k if ind == "stoch_k" else k.rolling(int(_p(params, "signal", ind)),
                                                  min_periods=int(_p(params, "signal", ind))).mean()
    elif ind == "change_pct":
        s = c.pct_change(n) * 100
    else:
        raise ValueError(f"Onbekende indicator: {ind}")
    return s.to_numpy(float)


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


# --------------------------------------------------------------------------- #
# Beschrijven & valideren
# --------------------------------------------------------------------------- #
SHORT_LABEL = {"highest": "Hoogste high", "lowest": "Laagste low", "change_pct": "Verandering %",
               "macd": "MACD", "macd_signal": "MACD-signaal", "macd_hist": "MACD-hist", "bb_upper": "BB boven",
               "bb_mid": "BB midden", "bb_lower": "BB onder", "stoch_k": "Stoch %K", "stoch_d": "Stoch %D"}


def describe_operand(op: dict, signal_tf: str | None = None) -> str:
    ind = op.get("ind", "close")
    label = SHORT_LABEL.get(ind) or INDICATORS.get(ind, (ind, []))[0].split(" (")[0]
    if ind == "value":
        return f"{float(op.get('params', {}).get('value', 0)):g}"
    ps = [f"{op.get('params', {}).get(name, default):g}" for name, default, *_ in INDICATORS.get(ind, ("", []))[1]]
    txt = f"{label}({', '.join(ps)})" if ps else label
    tf = op.get("tf")
    if tf and tf != signal_tf:
        txt += f" [{tf}]"
    return txt


def describe_condition(cond: dict, signal_tf: str | None = None) -> str:
    return (f"{describe_operand(cond.get('left', {}), signal_tf)} {OPERATORS.get(cond.get('op'), cond.get('op'))} "
            f"{describe_operand(cond.get('right', {}), signal_tf)}")


def validate_rules(spec: dict) -> list[str]:
    s = normalize_rules(spec)
    errs = []
    if s["signal_tf"] not in TF_MINUTES:
        errs.append(f"Onbekende signaal-timeframe: {s['signal_tf']}")
    if s["direction"] not in ("long", "short", "both"):
        errs.append("Richting moet long, short of both zijn.")
    sides = {"long": ["long"], "short": ["short"], "both": ["long", "short"]}.get(s["direction"], [])
    for side in sides:
        block = s[side]
        if not block.get("conditions"):
            errs.append(f"Voeg minstens één {side}-voorwaarde toe.")
        if block.get("logic", "all") not in ("all", "any"):
            errs.append(f"{side}: logica moet 'all' of 'any' zijn.")
        for i, cnd in enumerate(block.get("conditions", []), 1):
            if cnd.get("op") not in OPERATORS:
                errs.append(f"{side} voorwaarde {i}: onbekende operator.")
            for part in ("left", "right"):
                o = cnd.get(part, {})
                if o.get("ind") not in INDICATORS:
                    errs.append(f"{side} voorwaarde {i}: onbekende indicator '{o.get('ind')}'.")
                if o.get("tf") and o["tf"] not in TF_MINUTES:
                    errs.append(f"{side} voorwaarde {i}: onbekende timeframe '{o['tf']}'.")
    if s["stop"].get("type") not in STOP_TYPES:
        errs.append("Onbekend type stop loss.")
    elif float(s["stop"].get("value", 0)) <= 0:
        errs.append("Stop loss-waarde moet groter dan 0 zijn.")
    if s["target"].get("type") not in TARGET_TYPES:
        errs.append("Onbekend type take profit.")
    elif s["target"]["type"] != "none" and float(s["target"].get("value", 0)) <= 0:
        errs.append("Take profit-waarde moet groter dan 0 zijn.")
    return errs


# --------------------------------------------------------------------------- #
# Signalen
# --------------------------------------------------------------------------- #
def _operand_values(mtf: MultiTimeframeData, sig: pd.DataFrame, sig_ns: np.ndarray, op: dict,
                    signal_tf: str, cache: dict) -> np.ndarray:
    tf = op.get("tf") or signal_tf
    if tf not in mtf:
        raise ValueError(f"Timeframe {tf} is niet beschikbaar in je data.")
    key = (tf, op.get("ind"), tuple(sorted((op.get("params") or {}).items())))
    if key in cache:
        return cache[key]
    if tf == signal_tf:
        vals = compute_indicator(sig, op["ind"], op.get("params"))
    else:
        df = mtf[tf]
        raw = compute_indicator(df, op["ind"], op.get("params"))
        idx = np.searchsorted(to_numpy_ns(df["close_time"]), sig_ns, side="right") - 1
        vals = np.where(idx >= 0, raw[np.clip(idx, 0, None)], np.nan)
    cache[key] = vals
    return vals


def _condition(left: np.ndarray, op: str, right: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        if op == ">":
            return left > right
        if op == "<":
            return left < right
        if op == ">=":
            return left >= right
        if op == "<=":
            return left <= right
        lp, rp = np.roll(left, 1), np.roll(right, 1)
        lp[0] = rp[0] = np.nan
        if op == "crosses_above":
            return (left > right) & (lp <= rp)
        if op == "crosses_below":
            return (left < right) & (lp >= rp)
    raise ValueError(op)


def compute_signals(mtf: MultiTimeframeData, spec: dict) -> dict:
    s = normalize_rules(spec)
    tf = s["signal_tf"]
    if tf not in mtf:
        raise ValueError(f"De signaal-timeframe {tf} zit niet in je data (beschikbaar: "
                         f"{', '.join(t for t in TIMEFRAMES if t in mtf)}).")
    sig = mtf[tf]
    sig_ns = to_numpy_ns(sig["close_time"])
    cache: dict = {}
    out = {"tf": tf, "frame": sig, "close_ns": sig_ns, "details": {}}
    for side in ("long", "short"):
        enabled = s["direction"] in (side, "both") and s[side].get("conditions")
        if not enabled:
            out[side] = np.zeros(len(sig), bool)
            out["details"][side] = []
            continue
        parts = []
        for cnd in s[side]["conditions"]:
            lv = _operand_values(mtf, sig, sig_ns, cnd["left"], tf, cache)
            rv = _operand_values(mtf, sig, sig_ns, cnd["right"], tf, cache)
            parts.append((cnd, _condition(lv, cnd["op"], rv), lv, rv))
        arr = np.stack([p[1] for p in parts])
        res = arr.all(0) if s[side].get("logic", "all") == "all" else arr.any(0)
        st_, en = int(s["session"].get("start", 0)), int(s["session"].get("end", 24))
        if (st_, en) != (0, 24):
            hours = sig.index.hour.to_numpy()
            ok = (hours >= st_) & (hours < en) if st_ < en else (hours >= st_) | (hours < en)
            res = res & ok
        out[side] = res
        out["details"][side] = parts
    return out


def live_status(mtf: MultiTimeframeData, spec: dict) -> dict:
    """Stand van alle voorwaarden op de laatste gesloten signaal-candle."""
    s = normalize_rules(spec)
    sg = compute_signals(mtf, s)
    k = len(sg["frame"]) - 1
    last_base_ns = int(to_numpy_ns(mtf[mtf.base_tf]["close_time"])[-1])
    while k > 0 and sg["close_ns"][k] > last_base_ns:   # nog niet gesloten candle overslaan
        k -= 1
    res = {"time": pd.Timestamp(sg["close_ns"][k], tz="UTC"), "tf": sg["tf"], "sides": {}}
    for side in ("long", "short"):
        rows = [{"text": describe_condition(c, s["signal_tf"]), "ok": bool(m[k]),
                 "left": float(lv[k]) if np.isfinite(lv[k]) else None,
                 "right": float(rv[k]) if np.isfinite(rv[k]) else None}
                for c, m, lv, rv in sg["details"].get(side, [])]
        res["sides"][side] = {"rows": rows, "signal": bool(sg[side][k]) if rows else False,
                              "logic": s[side].get("logic", "all")}
    return res


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #
@dataclass
class _Pos:
    d: int
    i: int
    k: int
    entry: float
    sl: float
    sl0: float
    tp: float
    size: float
    risk_amount: float
    risk_px: float
    rr: float
    be_trigger: float
    be: bool = False
    trailed: bool = False


def run_rules_backtest(mtf: MultiTimeframeData, spec: dict, risk: RiskConfig | None = None,
                       costs: CostConfig | None = None, start: pd.Timestamp | None = None,
                       name: str = "Regels") -> BacktestResult:
    s = normalize_rules(spec)
    errs = validate_rules(s)
    if errs:
        raise ValueError(" ".join(errs))
    risk = risk or RiskConfig()
    costs = costs or CostConfig()
    sg = compute_signals(mtf, s)
    sig = sg["frame"]
    base = mtf[mtf.base_tf]
    o, h, l, c = (base[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    t_ns = to_numpy_ns(base["close_time"])
    times = pd.DatetimeIndex(base["close_time"])
    N = len(c)
    start_i = 0
    if start is not None:
        start_i = int(np.searchsorted(t_ns, to_numpy_ns(pd.DatetimeIndex([start]))[0]))

    # signaal-candle k is bekend bij executie-bar ev[k]
    ev = np.searchsorted(t_ns, sg["close_ns"], side="right") - 1
    closed_k = np.full(N, -1, dtype=np.int64)
    valid = (ev >= 0) & (sg["close_ns"] <= t_ns[-1])
    closed_k[ev[valid]] = np.nonzero(valid)[0]

    sc, sh, sl_ = (sig[k].to_numpy(float) for k in ("close", "high", "low"))
    stop, target = s["stop"], s["target"]
    atr_stop = _atr(sig, int(stop.get("length", 14))).to_numpy(float)
    atr_tgt = _atr(sig, int(target.get("length", 14))).to_numpy(float)
    atr_trail = _atr(sig, int(s.get("trailing_length", 14))).to_numpy(float)
    swing_n = max(1, int(stop.get("value", 10))) if stop["type"] == "swing" else 1
    swing_lo = pd.Series(sl_).rolling(swing_n, min_periods=1).min().to_numpy()
    swing_hi = pd.Series(sh).rolling(swing_n, min_periods=1).max().to_numpy()

    equity = risk.initial_balance
    eq_t, eq_v = [times[start_i] if N else None], [equity]
    trades: list[dict] = []
    stats = {"signals": 0, "skip_rr": 0, "skip_no_tp": 0, "skip_sl": 0}
    pos: _Pos | None = None
    be_r, trail, max_bars = float(s.get("breakeven_r") or 0), float(s.get("trailing_atr") or 0), int(s.get("max_bars") or 0)

    def close(i: int, price: float, reason: str) -> None:
        nonlocal equity, pos
        p = pos
        pnl = (price - p.entry) * p.d * p.size - costs.commission_pct * p.size * (p.entry + price)
        equity += pnl
        trades.append({
            "symbol": mtf.symbol, "direction": "LONG" if p.d == 1 else "SHORT",
            "trade_type": "Long" if p.d == 1 else "Short", "poi_tf": sg["tf"], "confirmation_tf": "-",
            "bias_combo": name, "poi_top": np.nan, "poi_bottom": np.nan,
            "entry_time": times[p.i], "entry": p.entry, "stop_loss": p.sl0, "take_profit": p.tp if np.isfinite(p.tp) else np.nan,
            "planned_rr": p.rr, "required_rr": np.nan, "exit_time": times[i], "exit": price, "exit_reason": reason,
            "be_moved": p.be, "r_multiple": pnl / p.risk_amount, "pnl": pnl, "equity": equity,
        })
        eq_t.append(times[i]); eq_v.append(equity)
        pos = None

    for i in range(start_i, N):
        # ---------- management ----------
        if pos is not None and i > pos.i:
            d = pos.d
            hit_reason = "TRAIL" if pos.trailed else ("BE" if pos.be else "SL")
            if d == 1:
                if o[i] <= pos.sl:
                    close(i, o[i], hit_reason)
                elif l[i] <= pos.sl:
                    close(i, pos.sl, hit_reason)
                elif o[i] >= pos.tp:
                    close(i, o[i], "TP")
                elif h[i] >= pos.tp:
                    close(i, pos.tp, "TP")
                elif be_r > 0 and not pos.be and h[i] >= pos.be_trigger:
                    pos.sl, pos.be = max(pos.sl, pos.entry), True
            else:
                if o[i] >= pos.sl:
                    close(i, o[i], hit_reason)
                elif h[i] >= pos.sl:
                    close(i, pos.sl, hit_reason)
                elif o[i] <= pos.tp:
                    close(i, o[i], "TP")
                elif l[i] <= pos.tp:
                    close(i, pos.tp, "TP")
                elif be_r > 0 and not pos.be and l[i] <= pos.be_trigger:
                    pos.sl, pos.be = min(pos.sl, pos.entry), True
            k = closed_k[i]
            if pos is not None and k >= 0 and k > pos.k:
                if trail > 0 and np.isfinite(atr_trail[k]):
                    new = sc[k] - d * trail * atr_trail[k]
                    if (d == 1 and new > pos.sl) or (d == -1 and new < pos.sl):
                        pos.sl, pos.trailed = new, True
                if max_bars > 0 and k - pos.k >= max_bars:
                    close(i, c[i], "TIME")
                elif s.get("exit_on_opposite") and ((d == 1 and sg["short"][k]) or (d == -1 and sg["long"][k])):
                    close(i, c[i], "SIGNAL")

        # ---------- entry ----------
        k = closed_k[i]
        if pos is not None or k < 0:
            continue
        d = 1 if sg["long"][k] else (-1 if sg["short"][k] else 0)
        if d == 0:
            continue
        stats["signals"] += 1
        entry = c[i] + d * costs.spread
        st = stop["type"]
        v = float(stop.get("value", 1))
        if st == "atr":
            dist = v * atr_stop[k]
        elif st == "percent":
            dist = entry * v / 100
        elif st == "swing":
            ref = swing_lo[k] if d == 1 else swing_hi[k]
            dist = (entry - ref * (1 - 0.0005)) if d == 1 else (ref * (1 + 0.0005) - entry)
        else:
            dist = v
        if not np.isfinite(dist) or dist <= max(entry * 0.0001, costs.spread):
            stats["skip_sl"] += 1
            continue
        slp = entry - d * dist
        tt, tv = target["type"], float(target.get("value", 1))
        tdist = {"rr": tv * dist, "atr": tv * atr_tgt[k], "percent": entry * tv / 100, "fixed": tv}.get(tt, np.inf)
        if not np.isfinite(tdist) and tt != "none":
            stats["skip_no_tp"] += 1
            continue
        tpp = entry + d * tdist if tt != "none" else (np.inf if d == 1 else -np.inf)
        risk_amount = equity * risk.risk_per_trade
        pos = _Pos(d=d, i=i, k=int(k), entry=entry, sl=slp, sl0=slp, tp=tpp, size=risk_amount / dist,
                   risk_amount=risk_amount, risk_px=dist, rr=tdist / dist if tt != "none" else np.nan,
                   be_trigger=entry + d * be_r * dist)

    if pos is not None:
        close(N - 1, c[-1], "EOD")
    eq = pd.Series(eq_v, index=pd.DatetimeIndex(eq_t), name=mtf.symbol)
    return BacktestResult(mtf.symbol, pd.DataFrame(trades), eq, risk.initial_balance, stats)
