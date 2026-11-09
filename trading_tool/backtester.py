"""Event-driven backtester: Bias -> POI -> POI-in-POI confirmation -> Entry -> BE/TP/SL.

Simulatie gebeurt bar-voor-bar op de fijnste beschikbare timeframe (idealiter 1m).
Regels:
  * max. 1 open trade per account (= per symbool), exact 1% risico van de equity
  * entry op de close van de confirmation-candle (+ spread)
  * SL en TP in dezelfde bar -> SL wordt aangenomen (conservatief)
  * Break-Even wordt actief vanaf de bar NA het bereiken van de BE-trigger
  * geen partial take profits, geen handmatige interventie
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .bias import compute_confluence
from .config import (BIAS_COMBOS, CONFIRMATION_TF, POI_TIMEFRAMES, SCALP_POI_TIMEFRAMES,
                     SWING_POI_TIMEFRAMES, TF_MINUTES, TIMEFRAMES, CostConfig, RiskConfig,
                     StrategyConfig)
from .data_loader import MultiTimeframeData, to_numpy_ns
from .market_structure import POI, TFAnalysis, analyze_timeframe

MINUTE_NS = 60 * 10**9


@dataclass
class Position:
    direction: int
    entry_i: int
    entry: float
    sl: float
    sl_initial: float
    tp: float
    size: float
    risk_amount: float
    trade_type: str
    poi: POI
    conf_tf: str
    combo: str
    planned_rr: float
    required_rr: float
    be_trigger: float
    be_moved: bool = False


@dataclass
class BacktestResult:
    symbol: str
    trades: pd.DataFrame
    equity: pd.Series
    initial_balance: float
    stats: dict = field(default_factory=dict)


class Backtester:
    def __init__(self, data: MultiTimeframeData, strategy: StrategyConfig | None = None,
                 risk: RiskConfig | None = None, costs: CostConfig | None = None,
                 start: pd.Timestamp | None = None, verbose: bool = True):
        self.data = data
        self.cfg = strategy or StrategyConfig()
        self.risk = risk or RiskConfig()
        self.costs = costs or CostConfig()
        self.start = start if start is not None else getattr(data, "backtest_start", None)
        self.verbose = verbose
        self.symbol = data.symbol
        self.base_tf = data.base_tf
        self.counters = {"signals": 0, "skip_rr": 0, "skip_no_tp": 0, "skip_sl": 0}

    # ------------------------------------------------------------------ #
    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def _effective_tf(self, tf: str) -> str:
        """Confirmation-TF lager dan de beschikbare data -> val terug op executie-TF."""
        if tf in self.data:
            return tf
        return self.base_tf

    def _prepare(self) -> None:
        cfg = self.cfg
        self.analysis: dict[str, TFAnalysis] = {}
        for tf in TIMEFRAMES:
            if tf in self.data:
                self.analysis[tf] = analyze_timeframe(
                    self.data[tf], tf, cfg.swing_length.get(tf, 3),
                    cfg.liquidity_window, cfg.poi_body_lookback, cfg.liquidity_mode)

        base = self.data[self.base_tf]
        self.o = base["open"].to_numpy(float)
        self.h = base["high"].to_numpy(float)
        self.l = base["low"].to_numpy(float)
        self.c = base["close"].to_numpy(float)
        self.t_ns = to_numpy_ns(base["close_time"])
        self.times = pd.DatetimeIndex(base["close_time"])
        N = len(base)

        # Laatst gesloten bar per TF op ieder executie-moment (geen lookahead)
        self.avail: dict[str, np.ndarray] = {}
        self.closed_now: dict[str, np.ndarray] = {}
        bias_at: dict[str, np.ndarray] = {}
        for tf, an in self.analysis.items():
            idx = np.searchsorted(an.close_ns, self.t_ns, side="right") - 1
            self.avail[tf] = idx
            cn = np.zeros(N, bool)
            cn[1:] = idx[1:] > idx[:-1]
            cn[0] = idx[0] >= 0
            self.closed_now[tf] = cn
            bias_at[tf] = np.where(idx >= 0, an.bias[np.clip(idx, 0, None)], 0).astype(np.int8)
        self.bias_at = bias_at
        self.conf = compute_confluence(bias_at, N)

        self.conf_tf = {p: self._effective_tf(c) for p, c in CONFIRMATION_TF.items()}
        for p, c in CONFIRMATION_TF.items():
            if p in self.data and self.conf_tf[p] != c:
                self._log(f"  [let op] {self.symbol}: geen {c} data -> {p} POI confirmatie op {self.conf_tf[p]}")

        self.start_i = 0
        if self.start is not None:
            self.start_i = int(np.searchsorted(self.t_ns, to_numpy_ns(pd.DatetimeIndex([self.start]))[0]))

    # ------------------------------------------------------------------ #
    def _required_rr(self, closed: list[dict]) -> float:
        cfg = self.cfg
        if not cfg.adaptive_rr or len(closed) < cfg.adaptive_warmup_trades:
            return cfg.min_rr
        r = np.array([t["r_multiple"] for t in closed])
        wins, losses = (r > 0.05).sum(), (r < -0.05).sum()
        if wins == 0:
            return cfg.max_required_rr
        # break-even RR = verlies-kans / win-kans ; eis een marge daarboven
        be_rr = (losses / wins) * (1 + cfg.adaptive_margin)
        return float(min(cfg.max_required_rr, max(cfg.min_rr, be_rr)))

    def _stop_loss(self, direction: int, entry: float, poi: POI, now: int) -> float | None:
        """Minimale (dichtstbijzijnde) 1H protected level aan de juiste kant van de entry."""
        tf = self.cfg.sl_timeframe if self.cfg.sl_timeframe in self.analysis else self.base_tf
        an = self.analysis[tf]
        buf = self.cfg.sl_buffer_pct
        if direction == 1:
            lv = an.swing_lows.unswept_at(now)
            lv = lv[lv < entry]
            level = lv.max() if lv.size else poi.bottom
            sl = level * (1 - buf)
            return sl if sl < entry else None
        lv = an.swing_highs.unswept_at(now)
        lv = lv[lv > entry]
        level = lv.min() if lv.size else poi.top
        sl = level * (1 + buf)
        return sl if sl > entry else None

    def _take_profit(self, direction: int, entry: float, poi_tf: str, now: int) -> float | None:
        """Eerstvolgende liquiditeitsniveau (onaangetaste swing high/low)."""
        order = TIMEFRAMES[: TIMEFRAMES.index(poi_tf) + 1][::-1]  # POI-TF, dan hoger
        best = None
        for tf in order:
            if tf not in self.analysis:
                continue
            an = self.analysis[tf]
            if direction == 1:
                lv = an.swing_highs.unswept_at(now)
                lv = lv[lv > entry]
                cand = lv.min() if lv.size else None
            else:
                lv = an.swing_lows.unswept_at(now)
                lv = lv[lv < entry]
                cand = lv.max() if lv.size else None
            if cand is not None:
                if best is None or abs(cand - entry) < abs(best - entry):
                    best = cand
            # "poi_tf": stop bij de eerste TF (POI-TF) die liquiditeit heeft
            if self.cfg.tp_source == "poi_tf" and best is not None:
                break
        return best

    # ------------------------------------------------------------------ #
    def run(self) -> BacktestResult:
        self._prepare()
        cfg, risk, costs = self.cfg, self.risk, self.costs
        o, h, l, c, t_ns = self.o, self.h, self.l, self.c, self.t_ns
        N = len(c)

        equity = risk.initial_balance
        eq_times, eq_values = [self.times[self.start_i] if N else None], [equity]
        closed: list[dict] = []
        pos: Position | None = None

        poi_tfs = [tf for tf in POI_TIMEFRAMES if tf in self.analysis]
        active: dict[str, list[POI]] = {tf: [] for tf in poi_tfs}
        ptr = {tf: 0 for tf in poi_tfs}
        standard_dir = self.conf["standard_dir"]
        scalp_dir = self.conf["scalp_dir"]
        combo_id = self.conf["combo_id"]

        def close_position(i: int, price: float, reason: str) -> None:
            nonlocal equity, pos
            p = pos
            gross = (price - p.entry) * p.direction * p.size
            comm = costs.commission_pct * p.size * (p.entry + price)
            pnl = gross - comm
            equity += pnl
            closed.append({
                "symbol": self.symbol,
                "direction": "LONG" if p.direction == 1 else "SHORT",
                "trade_type": p.trade_type,
                "poi_tf": p.poi.tf,
                "confirmation_tf": p.conf_tf,
                "bias_combo": p.combo,
                "entry_time": self.times[p.entry_i],
                "entry": p.entry,
                "stop_loss": p.sl_initial,
                "take_profit": p.tp,
                "planned_rr": p.planned_rr,
                "required_rr": p.required_rr,
                "exit_time": self.times[i],
                "exit": price,
                "exit_reason": reason,
                "be_moved": p.be_moved,
                "r_multiple": pnl / p.risk_amount,
                "pnl": pnl,
                "equity": equity,
            })
            eq_times.append(self.times[i]); eq_values.append(equity)
            pos = None

        for i in range(self.start_i, N):
            now = t_ns[i]

            # ---------- 1. Trade management (Stap 4) ----------
            if pos is not None and i > pos.entry_i:
                d = pos.direction
                if d == 1:
                    if o[i] <= pos.sl:
                        close_position(i, o[i], "BE" if pos.be_moved else "SL")
                    elif l[i] <= pos.sl:
                        close_position(i, pos.sl, "BE" if pos.be_moved else "SL")
                    elif o[i] >= pos.tp:
                        close_position(i, o[i], "TP")
                    elif h[i] >= pos.tp:
                        close_position(i, pos.tp, "TP")
                    elif not pos.be_moved and h[i] >= pos.be_trigger:
                        pos.sl, pos.be_moved = pos.entry, True
                else:
                    if o[i] >= pos.sl:
                        close_position(i, o[i], "BE" if pos.be_moved else "SL")
                    elif h[i] >= pos.sl:
                        close_position(i, pos.sl, "BE" if pos.be_moved else "SL")
                    elif o[i] <= pos.tp:
                        close_position(i, o[i], "TP")
                    elif l[i] <= pos.tp:
                        close_position(i, pos.tp, "TP")
                    elif not pos.be_moved and l[i] <= pos.be_trigger:
                        pos.sl, pos.be_moved = pos.entry, True

            # ---------- 2. POI administratie (Stap 2) ----------
            for tf in poi_tfs:
                plist = self.analysis[tf].pois
                while ptr[tf] < len(plist) and plist[ptr[tf]].created_ns <= now:
                    p = plist[ptr[tf]]
                    active[tf].append(POI(p.tf, p.direction, p.top, p.bottom, p.created_ns, p.protected_level))
                    ptr[tf] += 1
                    if len(active[tf]) > cfg.max_pois_per_tf:
                        active[tf].pop(0)
                keep = []
                timeout_ns = cfg.arm_timeout_bars * TF_MINUTES[self.conf_tf[tf]] * MINUTE_NS
                for p in active[tf]:
                    # invalidatie: close voorbij het protected level
                    if (p.direction == 1 and c[i] < p.bottom) or (p.direction == -1 and c[i] > p.top):
                        continue
                    if p.contains(l[i], h[i]):
                        if p.armed_ns < 0:
                            p.armed_ns = now
                        p.last_touch_ns = now
                    elif p.armed_ns >= 0 and now - p.last_touch_ns > timeout_ns:
                        p.armed_ns = -1          # te lang geen confirmatie
                    keep.append(p)
                active[tf] = keep

            if pos is not None:
                continue  # max 1 open trade per account

            # ---------- 3. Bias (Stap 1) ----------
            if standard_dir[i] != 0:
                direction, allowed, scalp = int(standard_dir[i]), poi_tfs, False
            elif scalp_dir[i] != 0:
                direction, allowed, scalp = int(scalp_dir[i]), [t for t in poi_tfs if t in SCALP_POI_TIMEFRAMES], True
            else:
                continue  # Geen Match / 50/50 -> geen trade
            combo_name = "+".join(BIAS_COMBOS[int(combo_id[i]) - 1][0])

            # ---------- 4. POI-in-POI confirmation (Stap 3) ----------
            done = False
            for tf in allowed:  # hoog -> laag
                ctf = self.conf_tf[tf]
                if not self.closed_now[ctf][i]:
                    continue
                k = self.avail[ctf][i]
                an_c = self.analysis[ctf]
                signal = an_c.bos[k] if cfg.confirmation_mode == "bos" else an_c.candle_dir[k]
                if signal != direction:
                    continue
                for p in active[tf]:
                    if p.direction != direction or p.armed_ns < 0:
                        continue
                    self.counters["signals"] += 1
                    entry = c[i] + direction * costs.spread
                    sl = self._stop_loss(direction, entry, p, now)
                    if sl is None or abs(entry - sl) < cfg.min_sl_pct * entry:
                        self.counters["skip_sl"] += 1
                        continue
                    tp = self._take_profit(direction, entry, tf, now)
                    if tp is None:
                        self.counters["skip_no_tp"] += 1
                        continue
                    risk_px = abs(entry - sl)
                    rr = abs(tp - entry) / risk_px
                    req = self._required_rr(closed)
                    if rr < req:
                        self.counters["skip_rr"] += 1
                        continue
                    swing = tf in SWING_POI_TIMEFRAMES
                    ttype = "Swing" if swing else ("Scalp" if scalp else "Intraday")
                    be_rr = cfg.be_trigger_rr_swing if swing else cfg.be_trigger_rr_intraday
                    risk_amount = equity * risk.risk_per_trade
                    pos = Position(
                        direction=direction, entry_i=i, entry=entry, sl=sl, sl_initial=sl, tp=tp,
                        size=risk_amount / risk_px, risk_amount=risk_amount, trade_type=ttype,
                        poi=p, conf_tf=ctf, combo=combo_name, planned_rr=rr, required_rr=req,
                        be_trigger=entry + direction * be_rr * risk_px)
                    active[tf].remove(p)   # iedere POI wordt maar 1x getraded
                    done = True
                    break
                if done:
                    break

        if pos is not None:
            close_position(N - 1, c[-1], "EOD")

        trades = pd.DataFrame(closed)
        eq = pd.Series(eq_values, index=pd.DatetimeIndex(eq_times), name=self.symbol)
        return BacktestResult(self.symbol, trades, eq, risk.initial_balance, dict(self.counters))
