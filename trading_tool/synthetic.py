"""Synthetische OHLC-data om de tool te testen zonder echte data (GEEN echte marktdata!)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def generate_ohlc(symbol: str, start: str = "2021-01-01", end: str = "2025-01-01",
                  freq: str = "5min", seed: int = 7, drift_scale: float = 0.005) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq=freq, tz="UTC", inclusive="left")
    if symbol.upper().startswith("XAU"):
        idx = idx[idx.dayofweek < 5]          # goud: geen weekend
        price0, ann_vol = 1800.0, 0.15
    else:
        price0, ann_vol = 30000.0, 0.60
    n = len(idx)
    bars_per_year = 365 * 24 * 60 / (pd.Timedelta(freq).total_seconds() / 60)
    sigma = ann_vol / np.sqrt(bars_per_year)

    # regime-switching drift + volatility clustering -> trends en ranges
    regime_len = int(bars_per_year / 6)
    n_reg = n // regime_len + 1
    drifts = np.repeat(rng.normal(0, 1.2, n_reg), regime_len)[:n] * sigma * drift_scale
    vol = np.exp(np.convolve(rng.normal(0, 0.35, n), np.ones(200) / 200 ** 0.5, mode="same") * 0.15)
    rets = drifts + sigma * vol * rng.standard_t(4, n) / np.sqrt(2)
    close = price0 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[price0], close[:-1]])
    wick = np.abs(rng.normal(0, sigma * vol * 0.7, (2, n)))
    high = np.maximum(open_, close) * np.exp(wick[0])
    low = np.minimum(open_, close) * np.exp(-wick[1])
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.integers(10, 1000, n).astype(float)}, index=idx)


def demo_dataset(symbol: str, seed: int = 0):
    """Kant-en-klare demo: 1D-historie 2016-2022 (warm-up) + 5m data 2023-2024 (backtest)."""
    from .data_loader import build_multi_timeframe

    daily = generate_ohlc(symbol, "2016-01-01", "2023-01-01", "1h", seed=11 + seed).resample("1D").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    base = generate_ohlc(symbol, "2023-01-01", "2025-01-01", "5min", seed=21 + seed)
    base *= daily["close"].iloc[-1] / base["open"].iloc[0]
    mtf = build_multi_timeframe(symbol, {"1D": daily, "5m": base})
    mtf.backtest_start = pd.Timestamp("2023-03-01", tz="UTC")
    return mtf
