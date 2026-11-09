"""Centrale configuratie: timeframes, Trading Plan regels, risico en kosten.

Alle regels uit het Trading Plan 2026-2028 staan hier als data, zodat de logica
in de andere modules nergens "magische" waarden bevat.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# --------------------------------------------------------------------------- #
# Timeframes
# --------------------------------------------------------------------------- #
# Volgorde: hoog -> laag
TIMEFRAMES: list[str] = ["1M", "1W", "1D", "4H", "1H", "15m", "5m", "1m"]

TF_MINUTES: dict[str, int] = {
    "1m": 1, "5m": 5, "15m": 15, "1H": 60, "4H": 240,
    "1D": 1440, "1W": 10080, "1M": 43200,
}

# pandas resample-regels (bars gelabeld op hun OPEN-tijd)
PANDAS_RULE: dict[str, str] = {
    "1m": "1min", "5m": "5min", "15m": "15min", "1H": "1h", "4H": "4h",
    "1D": "1D", "1W": "W-MON", "1M": "MS",
}

# Aliassen zodat bestandsnamen/CLI flexibel zijn (BTCUSD_60.csv, XAUUSD_H4.csv, ...)
TF_ALIASES: dict[str, str] = {
    "1": "1m", "m1": "1m", "1min": "1m",
    "5": "5m", "m5": "5m", "5min": "5m",
    "15": "15m", "m15": "15m", "15min": "15m",
    "60": "1H", "h1": "1H", "1h": "1H",
    "240": "4H", "h4": "4H", "4h": "4H",
    "d": "1D", "d1": "1D", "1d": "1D", "daily": "1D",
    "w": "1W", "w1": "1W", "1w": "1W", "weekly": "1W",
    "mn": "1M", "mn1": "1M", "1mo": "1M", "1mn": "1M", "monthly": "1M",
}


def normalize_tf(tf: str) -> str:
    """'H4' -> '4H', '1M' (hoofdletter) = maand, '1m' (kleine letter) = minuut."""
    if tf in TF_MINUTES:
        return tf
    key = tf.strip().lower()
    if key in TF_ALIASES:
        return TF_ALIASES[key]
    raise ValueError(f"Onbekende timeframe: {tf!r}")


def tf_bar_close(open_times: pd.DatetimeIndex, tf: str) -> pd.DatetimeIndex:
    """Sluitingstijd van elke bar (= moment waarop de bar-informatie beschikbaar is)."""
    if tf == "1M":
        return open_times + pd.offsets.MonthBegin(1)
    if tf == "1W":
        return open_times + pd.Timedelta(days=7)
    return open_times + pd.Timedelta(minutes=TF_MINUTES[tf])


# --------------------------------------------------------------------------- #
# Trading Plan regels
# --------------------------------------------------------------------------- #
# Stap 1: geldige timeframe-combinaties voor een bias-match
BIAS_COMBOS: list[tuple[tuple[str, str, str], str]] = [
    (("1M", "1W", "1D"), "standard"),
    (("1W", "1D", "4H"), "standard"),
    (("1M", "1D", "1H"), "standard"),
    (("1D", "4H", "1H"), "scalp"),   # uitsluitend Scalp Trade
]

# Stap 2: POI timeframes (hoog -> laag = prioriteit)
POI_TIMEFRAMES: list[str] = ["1M", "1W", "1D", "4H", "1H"]
SCALP_POI_TIMEFRAMES: list[str] = ["1D", "4H", "1H"]
SWING_POI_TIMEFRAMES: set[str] = {"1M", "1W"}

# Stap 3: POI-in-POI -> confirmation timeframe
CONFIRMATION_TF: dict[str, str] = {
    "1M": "4H",
    "1W": "1H",
    "1D": "15m",
    "4H": "5m",
    "1H": "1m",
}


@dataclass
class StrategyConfig:
    # Fractal-lengte (bars links/rechts) om swing highs/lows te bevestigen
    swing_length: dict[str, int] = field(default_factory=lambda: {
        "1M": 2, "1W": 2, "1D": 3, "4H": 3, "1H": 3, "15m": 3, "5m": 3, "1m": 3,
    })
    # Liquiditeit = 50/50 als beide kanten binnen dit aantal bars gesweept zijn
    liquidity_window: int = 10
    # "draw"  = sweeps + BOS-continuatie bepalen de draw on liquidity
    # "sweep" = alleen reversal-sweeps (strenger, minder trades)
    liquidity_mode: str = "draw"
    # Hoeveel POI's per timeframe actief blijven (oudste valt af)
    max_pois_per_tf: int = 5
    # Hoeveel candles terug zoeken naar de laatste tegengestelde candle (POI-body)
    poi_body_lookback: int = 3
    # Na een POI-touch: zoveel confirmation-TF bars wachten op de balance shift
    arm_timeout_bars: int = 24
    # "bos"          = Break of Market Structure (close door laatste swing)
    # "first_candle" = eerste candle in bias-richting op de confirmation TF
    confirmation_mode: str = "bos"

    # Stop loss: minimale (dichtstbijzijnde) protected level op deze TF
    sl_timeframe: str = "1H"
    sl_buffer_pct: float = 0.0005      # 0.05% buffer onder/boven het level
    min_sl_pct: float = 0.0005         # trades met SL-afstand < 0.05% worden overgeslagen

    # Take profit: eerstvolgende liquiditeit
    #   "poi_tf"            = eerstvolgende swing-liquiditeit op de POI-timeframe
    #   "poi_tf_and_higher" = dichtstbijzijnde liquiditeit op POI-TF of hoger
    tp_source: str = "poi_tf"

    # RR-filter (dynamisch)
    min_rr: float = 2.0
    adaptive_rr: bool = True
    adaptive_warmup_trades: int = 20
    adaptive_margin: float = 0.25      # eis 25% boven break-even RR
    max_required_rr: float = 10.0

    # Stap 4: trade management
    be_trigger_rr_swing: float = 2.0      # Monthly/Weekly POI
    be_trigger_rr_intraday: float = 4.0   # Daily/4H/1H POI (Intraday + Scalp)


@dataclass
class RiskConfig:
    initial_balance: float = 100_000.0
    risk_per_trade: float = 0.01   # exact 1%
    max_open_trades: int = 1       # per funded account (= per symbool)


@dataclass
class CostConfig:
    spread: float = 0.0            # in prijs-eenheden, volledig betaald bij entry
    commission_pct: float = 0.0    # per kant, als fractie van de notional


DEFAULT_COSTS: dict[str, CostConfig] = {
    "BTCUSD": CostConfig(spread=15.0, commission_pct=0.0003),
    "XAUUSD": CostConfig(spread=0.30, commission_pct=0.00002),
}
