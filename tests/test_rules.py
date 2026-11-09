import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_tool.config import CostConfig  # noqa: E402
from trading_tool.data_loader import build_multi_timeframe  # noqa: E402
from trading_tool.rules_engine import _condition, compute_indicator, compute_signals, validate_rules  # noqa: E402
from trading_tool.strategies import TEMPLATES, from_template, run_strategy, validate  # noqa: E402
from trading_tool.synthetic import generate_ohlc  # noqa: E402

START = pd.Timestamp("2023-03-01", tz="UTC")


def _mtf(end="2024-06-01", seed=3):
    d = generate_ohlc("BTCUSD", "2019-01-01", "2023-01-01", "1h", seed=seed).resample("1D").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    b = generate_ohlc("BTCUSD", "2023-01-01", end, "15min", seed=seed + 1)
    b *= d["close"].iloc[-1] / b["open"].iloc[0]
    return d, b


def test_crosses():
    l = np.array([1.0, 2.0, 3.0, 1.0])
    r = np.array([2.0, 2.0, 2.0, 2.0])
    assert _condition(l, "crosses_above", r).tolist() == [False, False, True, False]
    assert _condition(l, "crosses_below", r).tolist() == [False, False, False, True]


def test_indicators_basic():
    df = pd.DataFrame({"open": 1.0, "high": np.arange(1, 31, dtype=float) + 1, "low": np.arange(1, 31, dtype=float) - 1,
                       "close": np.arange(1, 31, dtype=float), "volume": 1.0})
    sma = compute_indicator(df, "sma", {"length": 5})
    assert np.isnan(sma[3]) and sma[4] == 3.0
    hi = compute_indicator(df, "highest", {"length": 3})
    assert hi[3] == df["high"].iloc[0:3].max()          # vorige 3 candles, niet de huidige
    rsi = compute_indicator(df, "rsi", {"length": 14})
    assert rsi[-1] == 100.0                               # alleen stijgende closes


def test_validation_errors():
    assert validate_rules({"direction": "long", "long": {"conditions": []}})
    bad = {"direction": "long", "long": {"conditions": [{"left": {"ind": "foo"}, "op": ">", "right": {"ind": "close"}}]}}
    assert any("onbekende indicator" in e for e in validate_rules(bad))
    s = from_template("trading_plan", "x")
    s["params"]["confirmation_tf"]["1H"] = "4H"
    assert any("lagere timeframe" in e for e in validate(s))


def test_higher_tf_alignment_no_lookahead():
    d, b = _mtf()
    m = build_multi_timeframe("BTCUSD", {"1D": d, "15m": b})
    spec = TEMPLATES["ema_cross"]["params"]
    sg = compute_signals(m, spec)
    # de 1D-waarde op een 1H-candle moet van de laatst *gesloten* dag komen
    _, _, lv, rv = sg["details"]["long"][1]
    daily = compute_indicator(m["1D"], "ema", {"length": 200})
    h1 = m["1H"]
    i = len(h1) // 2
    t = h1["close_time"].iloc[i]
    last_closed = np.searchsorted(m["1D"]["close_time"].values, t.to_datetime64(), side="right") - 1
    assert np.isclose(rv[i], daily[last_closed]) or (np.isnan(rv[i]) and np.isnan(daily[last_closed]))


def test_rules_no_lookahead_truncation_and_risk():
    d, b = _mtf()
    cut = pd.Timestamp("2024-01-01", tz="UTC")
    s = from_template("ema_cross", "x")
    full = run_strategy(s, build_multi_timeframe("BTCUSD", {"1D": d, "15m": b}), 100000, CostConfig(), START).trades
    part = run_strategy(s, build_multi_timeframe("BTCUSD", {"1D": d, "15m": b[b.index < cut]}), 100000,
                        CostConfig(), START).trades
    assert len(full) > 5
    cols = ["entry_time", "entry", "stop_loss", "take_profit", "exit_time", "exit"]
    pd.testing.assert_frame_equal(full[full.exit_time < cut][cols].reset_index(drop=True),
                                  part[part.exit_time < cut][cols].reset_index(drop=True))
    sl = full[full.exit_reason == "SL"]
    assert np.allclose(sl.r_multiple, -1.0, atol=0.05)
    tp = full[full.exit_reason == "TP"]
    assert np.allclose(tp.r_multiple, 2.0, atol=0.1)
    assert (full.entry_time.iloc[1:].values >= full.exit_time.iloc[:-1].values).all()


def test_all_templates_run():
    d, b = _mtf(end="2023-09-01")
    m = build_multi_timeframe("BTCUSD", {"1D": d, "15m": b})
    for key in TEMPLATES:
        r = run_strategy(from_template(key, "x"), m, 50000, CostConfig(), START)
        assert r.equity.iloc[0] == 50000
