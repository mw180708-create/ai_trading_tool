"""Actuele stand van het Trading Plan op de laatste beschikbare data ("Bias Engine").

Geeft per timeframe Liquiditeit / Balance level / Bias, de timeframe-match, de actieve POI's
en een beslissing volgens de regels (geen trade / wacht op POI / wacht op confirmatie / signaal).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .bias import compute_confluence
from .config import (BIAS_COMBOS, CONFIRMATION_TF, POI_TIMEFRAMES, SCALP_POI_TIMEFRAMES, TF_MINUTES,
                     StrategyConfig)
from .data_loader import MultiTimeframeData, to_numpy_ns
from .market_structure import analyze_timeframe

BIAS_TFS = ["1M", "1W", "1D", "4H", "1H"]
LABEL = {1: "Bullish", -1: "Bearish", 0: "50/50"}


@dataclass
class LivePOI:
    tf: str
    direction: int
    top: float
    bottom: float
    created: pd.Timestamp
    distance_pct: float      # 0 = prijs in de zone
    touched: bool            # recent geraakt (binnen arm-timeout)
    confirmation_tf: str


@dataclass
class LiveState:
    symbol: str
    time: pd.Timestamp
    price: float
    rows: list[dict]                       # per TF: liquidity / structure / bias
    combos: list[dict]                     # per combinatie: match + richting
    direction: int                         # +1 / -1 / 0
    scalp_only: bool
    score: int                             # 0..100 (50 = neutraal)
    pois: list[LivePOI] = field(default_factory=list)
    decision: str = ""
    detail: str = ""
    status: str = "none"                   # none / wait_poi / wait_confirm / signal


def analyze_live(mtf: MultiTimeframeData, cfg: StrategyConfig | None = None) -> LiveState:
    cfg = cfg or StrategyConfig()
    base = mtf[mtf.base_tf]
    last_close_ns = int(to_numpy_ns(base["close_time"])[-1])
    price = float(base["close"].iloc[-1])

    analyses = {}
    for tf in sorted({*BIAS_TFS, *[CONFIRMATION_TF[t] for t in POI_TIMEFRAMES]}, key=lambda t: -TF_MINUTES[t]):
        if tf in mtf:
            df = mtf[tf]
            # alleen gesloten bars meenemen
            df = df[to_numpy_ns(df["close_time"]) <= last_close_ns]
            if len(df) >= 10:
                analyses[tf] = analyze_timeframe(df, tf, cfg.swing_length.get(tf, 3), cfg.liquidity_window,
                                                 cfg.poi_body_lookback, cfg.liquidity_mode)

    rows, bias_now = [], {}
    for tf in BIAS_TFS:
        an = analyses.get(tf)
        if an is None:
            rows.append({"tf": tf, "liquidity": None, "structure": None, "bias": 0, "available": False})
            bias_now[tf] = np.zeros(1, np.int8)
            continue
        liq, st, b = int(an.liquidity[-1]), int(an.structure[-1]), int(an.bias[-1])
        rows.append({"tf": tf, "liquidity": liq, "structure": st, "bias": b, "available": True})
        bias_now[tf] = np.array([b], np.int8)

    conf = compute_confluence(bias_now, 1)
    combos = []
    for combo, kind in BIAS_COMBOS:
        vals = [int(bias_now[t][0]) for t in combo]
        match = vals[0] != 0 and all(v == vals[0] for v in vals)
        combos.append({"combo": "+".join(combo), "kind": kind, "match": match, "direction": vals[0] if match else 0})

    if conf["standard_dir"][0] != 0:
        direction, scalp_only = int(conf["standard_dir"][0]), False
    elif conf["scalp_dir"][0] != 0:
        direction, scalp_only = int(conf["scalp_dir"][0]), True
    else:
        direction, scalp_only = 0, False

    avail = [r["bias"] for r in rows if r["available"]]
    score = int(round(50 + 50 * (np.mean(avail) if avail else 0)))

    state = LiveState(mtf.symbol, base["close_time"].iloc[-1], price, rows, combos, direction, scalp_only, score)

    # ---------- actieve POI's ----------
    closes = base["close"].to_numpy(float)
    lows = base["low"].to_numpy(float)
    highs = base["high"].to_numpy(float)
    t_ns = to_numpy_ns(base["close_time"])
    suf_min = np.minimum.accumulate(closes[::-1])[::-1]
    suf_max = np.maximum.accumulate(closes[::-1])[::-1]
    allowed = [t for t in POI_TIMEFRAMES if not scalp_only or t in SCALP_POI_TIMEFRAMES]
    for tf in POI_TIMEFRAMES:
        an = analyses.get(tf)
        if an is None:
            continue
        ctf = CONFIRMATION_TF[tf] if CONFIRMATION_TF[tf] in mtf else mtf.base_tf
        window_ns = cfg.arm_timeout_bars * TF_MINUTES[ctf] * 60 * 10**9
        for p in an.pois[-cfg.max_pois_per_tf:]:
            i0 = int(np.searchsorted(t_ns, p.created_ns, side="right"))
            if i0 >= len(closes):
                continue
            if (p.direction == 1 and suf_min[i0] < p.bottom) or (p.direction == -1 and suf_max[i0] > p.top):
                continue  # ongeldig: close voorbij protected level
            j0 = max(i0, int(np.searchsorted(t_ns, last_close_ns - window_ns, side="left")))
            touched = bool(np.any((lows[j0:] <= p.top) & (highs[j0:] >= p.bottom))) if j0 < len(lows) else False
            if p.bottom <= price <= p.top:
                dist = 0.0
            else:
                dist = (p.bottom - price) / price * 100 if price < p.bottom else (p.top - price) / price * 100
            state.pois.append(LivePOI(tf, p.direction, p.top, p.bottom, pd.Timestamp(p.created_ns, tz="UTC"),
                                      dist, touched, ctf))

    # ---------- beslissing ----------
    name = {1: "BULLISH", -1: "BEARISH"}
    if direction == 0:
        state.status, state.decision = "none", "GEEN TRADE"
        state.detail = "Geen geldige timeframe-match (bias 50/50). Volgens het plan wordt er niet gehandeld."
        return state

    combo_txt = next(c["combo"] for c in combos if c["match"])
    relevant = [p for p in state.pois if p.direction == direction and p.tf in allowed]
    armed = [p for p in relevant if p.touched]
    state.detail = f"Bias {name[direction]} via {combo_txt}" + (" (alleen Scalp)" if scalp_only else "") + ". "
    if armed:
        p = armed[0]
        an_c = analyses.get(p.confirmation_tf)
        sig = an_c is not None and int(an_c.bos[-1]) == direction
        if sig:
            state.status, state.decision = "signal", f"{name[direction]} SIGNAAL"
            state.detail += (f"{p.tf} POI geraakt én {p.confirmation_tf} balance shift op de laatste candle. "
                             "Entry volgens de regels (SL op 1H protected level, TP op eerstvolgende liquiditeit).")
        else:
            state.status, state.decision = "wait_confirm", "WACHT OP CONFIRMATIE"
            state.detail += f"Prijs in/bij de {p.tf} POI → wacht op een {p.confirmation_tf} balance shift."
    elif relevant:
        p = min(relevant, key=lambda x: abs(x.distance_pct))
        state.status, state.decision = "wait_poi", f"{name[direction]} — WACHT OP POI"
        state.detail += (f"Dichtstbijzijnde {p.tf} POI: {p.bottom:,.2f} – {p.top:,.2f} "
                         f"({abs(p.distance_pct):.2f}% van de prijs).")
    else:
        state.status, state.decision = "wait_poi", f"{name[direction]} — GEEN POI"
        state.detail += f"Er is nog geen geldige {name[direction].lower()} POI. Wacht op een nieuwe balance shift."
    return state
