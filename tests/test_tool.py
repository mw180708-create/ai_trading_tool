import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_tool.backtester import Backtester  # noqa: E402
from trading_tool.bias import compute_confluence  # noqa: E402
from trading_tool.config import CostConfig  # noqa: E402
from trading_tool.data_loader import build_multi_timeframe, read_ohlc_csv  # noqa: E402
from trading_tool.market_structure import find_pivots  # noqa: E402
from trading_tool.synthetic import generate_ohlc  # noqa: E402


def _dataset(seed=0, base_end="2024-06-01"):
    d = generate_ohlc("BTCUSD", "2017-01-01", "2023-01-01", "1h", seed=seed).resample("1D").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    b = generate_ohlc("BTCUSD", "2023-01-01", base_end, "15min", seed=seed + 1)
    b *= d["close"].iloc[-1] / b["open"].iloc[0]
    return d, b


def test_pivots():
    h = np.array([1, 2, 5, 2, 1, 3, 1], float)
    sh, sl = find_pivots(h, h, 2)
    assert sh[2] and not sh[5]
    assert sl[4]


def test_confluence_rules():
    n = 3
    bias = {"1M": np.array([1, 1, 0]), "1W": np.array([1, -1, 1]), "1D": np.array([1, 1, 1]),
            "4H": np.array([0, 1, 1]), "1H": np.array([0, 1, 1])}
    out = compute_confluence({k: v.astype(np.int8) for k, v in bias.items()}, n)
    assert out["standard_dir"].tolist() == [1, 1, 1]   # 1M+1W+1D | 1M+1D+1H | 1W+1D+4H
    assert out["combo_id"].tolist() == [1, 3, 2]
    assert out["scalp_dir"].tolist() == [0, 1, 1]


def test_no_lookahead_truncation():
    d, b = _dataset(seed=3)
    start = pd.Timestamp("2023-03-01", tz="UTC")
    cut = pd.Timestamp("2024-01-01", tz="UTC")
    full = build_multi_timeframe("BTCUSD", {"1D": d, "15m": b})
    part = build_multi_timeframe("BTCUSD", {"1D": d, "15m": b[b.index < cut]})
    cols = ["entry_time", "entry", "stop_loss", "take_profit", "exit_time", "exit"]
    r1 = Backtester(full, costs=CostConfig(), start=start, verbose=False).run().trades
    r2 = Backtester(part, costs=CostConfig(), start=start, verbose=False).run().trades
    if r1.empty:
        return
    a = r1[r1.exit_time < cut][cols].reset_index(drop=True)
    c = r2[r2.exit_time < cut][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, c)


def test_risk_is_one_percent():
    d, b = _dataset(seed=5)
    mtf = build_multi_timeframe("BTCUSD", {"1D": d, "15m": b})
    t = Backtester(mtf, costs=CostConfig(), start=pd.Timestamp("2023-03-01", tz="UTC"), verbose=False).run().trades
    sl_hits = t[t.exit_reason == "SL"]
    if len(sl_hits):
        assert np.allclose(sl_hits.r_multiple, -1.0, atol=0.02)
    # nooit overlappende trades (max 1 open trade)
    if len(t) > 1:
        assert (t.entry_time.iloc[1:].values >= t.exit_time.iloc[:-1].values).all()


def test_read_mt5_csv(tmp_path):
    p = tmp_path / "XAUUSD_1H.csv"
    p.write_text("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
                 "2024.01.02\t00:00:00\t2062.1\t2063.0\t2061.5\t2062.8\t100\t0\t20\n"
                 "2024.01.02\t01:00:00\t2062.8\t2064.0\t2062.0\t2063.5\t120\t0\t20\n")
    df = read_ohlc_csv(p)
    assert len(df) == 2 and df.index[1].hour == 1 and df["close"].iloc[-1] == 2063.5


def test_read_tradingview_csv(tmp_path):
    p = tmp_path / "BTCUSD_1D.csv"
    p.write_text("time,open,high,low,close,Volume\n1704067200,42000,43000,41000,42500,10\n"
                 "1704153600,42500,45000,42000,44900,12\n")
    df = read_ohlc_csv(p)
    assert str(df.index[0].date()) == "2024-01-01" and df["high"].iloc[1] == 45000
