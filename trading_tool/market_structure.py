"""Marktstructuur-analyse per timeframe: swings, liquiditeit, balance levels, POI's.

Alle signalen zijn *lookahead-vrij*: een swing high/low op bar j is pas bekend op
bar j+n (n = fractal-lengte) en iedere waarde op bar k gebruikt alleen data t/m k.
De tijd waarop een waarde bekend is = close_time van die bar.

Operationalisatie van het Trading Plan (discretionaire begrippen -> regels):

* Swing high/low (liquiditeitspool): fractal met n bars links/rechts.
* Liquiditeit (draw on liquidity):
    - Sell-side sweep  = wick onder een onaangetaste swing low, close er weer boven
      -> sell-side liquiditeit gepakt, draw on liquidity omhoog  => Liquiditeit BULLISH
    - Buy-side sweep   = wick boven een onaangetaste swing high, close er weer onder
      => Liquiditeit BEARISH
    - Beide kanten gesweept binnen `liquidity_window` bars => 50/50
    - liquidity_mode="draw" (default): een BOS die buy-side (sell-side) liquiditeit
      doorbreekt zet de draw ook door naar de volgende buy-side (sell-side) pool.
      liquidity_mode="sweep": alleen reversal-sweeps tellen.
* Balance level (structuur):
    - Close boven de laatste swing high  = bullish balance shift / BOS => BULLISH
    - Close onder de laatste swing low   = bearish balance shift / BOS => BEARISH
* Bias per TF: Liquiditeit en Balance level gelijk -> die richting, anders 50/50.
* POI (bij elke BOS): gebied tussen de liquiditeit (extreme wick = protected level)
  en de protected zone (body van de laatste tegengestelde candle vóór de impuls).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from .data_loader import to_numpy_ns

NEVER = np.iinfo(np.int64).max


@dataclass
class POI:
    tf: str
    direction: int          # +1 bullish (demand), -1 bearish (supply)
    top: float
    bottom: float
    created_ns: int         # bekend vanaf (close van de BOS-bar)
    protected_level: float  # bullish: bottom, bearish: top
    # runtime state (backtester)
    armed_ns: int = -1
    last_touch_ns: int = -1

    def contains(self, low: float, high: float) -> bool:
        return low <= self.top and high >= self.bottom


@dataclass
class SwingPoints:
    level: np.ndarray       # prijs
    confirm_ns: np.ndarray  # bekend vanaf
    swept_ns: np.ndarray    # eerste keer doorbroken (NEVER = nog niet)

    def unswept_at(self, now_ns: int) -> np.ndarray:
        m = (self.confirm_ns <= now_ns) & (self.swept_ns > now_ns)
        return self.level[m]


@dataclass
class TFAnalysis:
    tf: str
    close_ns: np.ndarray
    structure: np.ndarray    # balance level: +1 / -1 / 0
    liquidity: np.ndarray    # +1 / -1 / 0 (50/50)
    bias: np.ndarray         # +1 / -1 / 0
    bos: np.ndarray          # BOS-event op deze bar: +1 / -1 / 0
    candle_dir: np.ndarray   # +1 bullish candle, -1 bearish candle
    swing_highs: SwingPoints
    swing_lows: SwingPoints
    pois: list[POI] = field(default_factory=list)


def find_pivots(high: np.ndarray, low: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Fractal swing highs/lows. Retourneert boolean arrays op de pivot-index."""
    N = len(high)
    is_sh = np.zeros(N, dtype=bool)
    is_sl = np.zeros(N, dtype=bool)
    if N < 2 * n + 1:
        return is_sh, is_sl
    wh = sliding_window_view(high, 2 * n + 1)
    wl = sliding_window_view(low, 2 * n + 1)
    ch, cl = high[n:N - n], low[n:N - n]
    is_sh[n:N - n] = (ch > wh[:, :n].max(1)) & (ch >= wh[:, n + 1:].max(1))
    is_sl[n:N - n] = (cl < wl[:, :n].min(1)) & (cl <= wl[:, n + 1:].min(1))
    return is_sh, is_sl


def analyze_timeframe(df: pd.DataFrame, tf: str, swing_length: int,
                      liquidity_window: int = 10, poi_body_lookback: int = 3,
                      liquidity_mode: str = "draw") -> TFAnalysis:
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    close_ns = to_numpy_ns(df["close_time"])
    N, n = len(df), swing_length

    is_sh, is_sl = find_pivots(h, l, n)

    structure = np.zeros(N, np.int8)
    liquidity = np.zeros(N, np.int8)
    bos = np.zeros(N, np.int8)
    candle_dir = np.sign(c - o).astype(np.int8)

    sh_lvl, sh_conf, sh_swept, sh_idx = [], [], [], []
    sl_lvl, sl_conf, sl_swept, sl_idx = [], [], [], []
    # onaangetaste pools, gesorteerd op prijs: (level, swing_id)
    act_highs: list[tuple[float, int]] = []
    act_lows: list[tuple[float, int]] = []
    last_sh = last_sl = -1            # id van laatste swing (voor BOS)
    sh_broken = sl_broken = True
    last_bull_sweep = last_bear_sweep = -10**9   # sell-side / buy-side sweep (reversal)
    last_bull_evt = last_bear_evt = -10**9       # laatste liquiditeits-event per richting
    use_bos = liquidity_mode == "draw"
    struct = 0
    pois: list[POI] = []

    for k in range(N):
        # 1) swings bevestigen (pivot j = k - n is pas nu bekend)
        j = k - n
        if j >= 0:
            if is_sh[j]:
                sid = len(sh_lvl)
                sh_lvl.append(h[j]); sh_conf.append(close_ns[k]); sh_swept.append(NEVER); sh_idx.append(j)
                bisect.insort(act_highs, (h[j], sid))
                last_sh, sh_broken = sid, False
            if is_sl[j]:
                sid = len(sl_lvl)
                sl_lvl.append(l[j]); sl_conf.append(close_ns[k]); sl_swept.append(NEVER); sl_idx.append(j)
                bisect.insort(act_lows, (l[j], sid))
                last_sl, sl_broken = sid, False

        # 2) liquiditeit: pools die geraakt worden
        rejected_high = False
        while act_highs and h[k] > act_highs[0][0]:
            lvl, sid = act_highs.pop(0)
            sh_swept[sid] = close_ns[k]
            if c[k] <= lvl:
                rejected_high = True
        rejected_low = False
        while act_lows and l[k] < act_lows[-1][0]:
            lvl, sid = act_lows.pop()
            sl_swept[sid] = close_ns[k]
            if c[k] >= lvl:
                rejected_low = True
        if rejected_high:
            last_bear_sweep = last_bear_evt = k
        if rejected_low:
            last_bull_sweep = last_bull_evt = k

        # 3) balance level / BOS
        if last_sh >= 0 and not sh_broken and c[k] > sh_lvl[last_sh]:
            sh_broken, struct, bos[k] = True, 1, 1
            a = sh_idx[last_sh]
            p = a + int(np.argmin(l[a:k + 1]))            # protected low
            top = None
            for q in range(p, max(a, p - poi_body_lookback) - 1, -1):
                if c[q] < o[q]:                           # laatste bearish candle
                    top = o[q]
                    break
            if top is None or top <= l[p]:
                top = max(o[p], c[p]) if max(o[p], c[p]) > l[p] else h[p]
            pois.append(POI(tf, 1, float(top), float(l[p]), int(close_ns[k]), float(l[p])))
        if last_sl >= 0 and not sl_broken and c[k] < sl_lvl[last_sl]:
            sl_broken, struct, bos[k] = True, -1, -1
            a = sl_idx[last_sl]
            p = a + int(np.argmax(h[a:k + 1]))            # protected high
            bot = None
            for q in range(p, max(a, p - poi_body_lookback) - 1, -1):
                if c[q] > o[q]:                           # laatste bullish candle
                    bot = o[q]
                    break
            if bot is None or bot >= h[p]:
                bot = min(o[p], c[p]) if min(o[p], c[p]) < h[p] else l[p]
            pois.append(POI(tf, -1, float(h[p]), float(bot), int(close_ns[k]), float(h[p])))
        structure[k] = struct
        if use_bos and bos[k] == 1:
            last_bull_evt = k        # buy-side doorbroken -> draw naar volgende buy-side
        elif use_bos and bos[k] == -1:
            last_bear_evt = k

        # 4) liquiditeit-bias
        bull_recent = k - last_bull_sweep <= liquidity_window
        bear_recent = k - last_bear_sweep <= liquidity_window
        if last_bull_evt < 0 and last_bear_evt < 0:
            liquidity[k] = 0
        elif bull_recent and bear_recent:
            liquidity[k] = 0                              # 50/50: beide kanten gesweept
        else:
            liquidity[k] = 1 if last_bull_evt > last_bear_evt else -1

    # Bias: Liq bull + Bal bull -> bull; Liq bear + Bal bear -> bear; rest 50/50
    bias = np.where((liquidity == structure) & (structure != 0), structure, 0).astype(np.int8)

    def sp(lv, cf, sw):
        return SwingPoints(np.asarray(lv, float), np.asarray(cf, np.int64), np.asarray(sw, np.int64))

    return TFAnalysis(tf, close_ns, structure, liquidity, bias, bos, candle_dir,
                      sp(sh_lvl, sh_conf, sh_swept), sp(sl_lvl, sl_conf, sl_swept), pois)
