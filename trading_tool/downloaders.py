"""Koersdata direct downloaden (zonder API-key).

BTCUSD: Binance publieke marktdata (data-api.binance.vision, BTC/USDT) met Bitstamp (BTC/USD)
als automatische terugval.
XAUUSD: er is geen betrouwbare gratis bron die geautomatiseerd downloaden toestaat - gebruik
een export uit MetaTrader 5 of TradingView (upload op de website).
"""
from __future__ import annotations

import time
from typing import Callable

import pandas as pd
import requests

from .data_loader import resample_ohlc

BINANCE = "https://data-api.binance.vision/api/v3/klines"
BITSTAMP = "https://www.bitstamp.net/api/v2/ohlc/btcusd/"
BINANCE_TF = {"1m": "1m", "5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d", "1W": "1w", "1M": "1M"}
BITSTAMP_STEP = {"1m": 60, "5m": 300, "15m": 900, "1H": 3600, "4H": 14400, "1D": 86400}
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1H": 3600, "4H": 14400, "1D": 86400, "1W": 604800, "1M": 2592000}

Progress = Callable[[float, str], None]


def _ts(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _frame(rows: list[list], unit: str) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df.pop("time").astype("int64"), unit=unit, utc=True)
    df.index.name = "time"
    df = df.astype(float)
    return df[~df.index.duplicated(keep="last")].sort_index()


CRYPTO = ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "LTC", "LINK", "AVAX"]


def binance_klines(tf: str, start, end, progress: Progress | None = None,
                   session: requests.Session | None = None, base: str = "BTC") -> pd.DataFrame:
    s = session or requests.Session()
    t0, t1 = int(_ts(start).timestamp() * 1000), int(_ts(end).timestamp() * 1000)
    cur, rows = t0, []
    while cur < t1:
        r = s.get(BINANCE, params={"symbol": f"{base}USDT", "interval": BINANCE_TF[tf], "startTime": cur,
                                   "endTime": t1 - 1, "limit": 1000}, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows += [[b[0], b[1], b[2], b[3], b[4], b[5]] for b in batch]
        cur = batch[-1][0] + 1
        if progress:
            progress(min(1.0, (cur - t0) / max(1, t1 - t0)), f"Binance: {len(rows):,} candles")
        time.sleep(0.05)
    if not rows:
        raise RuntimeError("Binance gaf geen data terug")
    return _frame(rows, "ms")


def bitstamp_ohlc(tf: str, start, end, progress: Progress | None = None,
                  session: requests.Session | None = None, base: str = "BTC") -> pd.DataFrame:
    base_tf = tf if tf in BITSTAMP_STEP else "1D"
    step = BITSTAMP_STEP[base_tf]
    s = session or requests.Session()
    t0, t1 = int(_ts(start).timestamp()), int(_ts(end).timestamp())
    cur, rows = t0, []
    while cur < t1:
        r = s.get(BITSTAMP.replace("btcusd", f"{base.lower()}usd"), params={"step": step, "limit": 1000, "start": cur},
                  timeout=30)
        r.raise_for_status()
        batch = r.json().get("data", {}).get("ohlc", [])
        batch = [b for b in batch if int(b["timestamp"]) < t1]
        if not batch:
            break
        rows += [[int(b["timestamp"]), b["open"], b["high"], b["low"], b["close"], b["volume"]] for b in batch]
        nxt = int(batch[-1]["timestamp"]) + step
        if nxt <= cur:
            break
        cur = nxt
        if progress:
            progress(min(1.0, (cur - t0) / max(1, t1 - t0)), f"Bitstamp: {len(rows):,} candles")
        time.sleep(0.15)
    if not rows:
        raise RuntimeError("Bitstamp gaf geen data terug")
    df = _frame(rows, "s")
    return resample_ohlc(df, tf) if base_tf != tf else df


def download_btc(tf: str, start, end=None, source: str = "auto",
                 progress: Progress | None = None) -> tuple[pd.DataFrame, str]:
    return download_crypto("BTC", tf, start, end, source, progress)


def download_crypto(base: str, tf: str, start, end=None, source: str = "auto",
                    progress: Progress | None = None) -> tuple[pd.DataFrame, str]:
    """Download <base>USD candles (Binance <base>/USDT, terugval Bitstamp <base>/USD). Retourneert (data, bron)."""
    base = base.upper()
    end = end or pd.Timestamp.now(tz="UTC")
    errors = []
    order = {"auto": ["binance", "bitstamp"], "binance": ["binance"], "bitstamp": ["bitstamp"]}[source]
    for src in order:
        try:
            fn = binance_klines if src == "binance" else bitstamp_ohlc
            df = fn(tf, start, end, progress, base=base)
            # laatste (nog niet gesloten) candle weglaten
            now = pd.Timestamp.now(tz="UTC")
            df = df[df.index + pd.Timedelta(seconds=TF_SECONDS[tf]) <= now]
            return df, {"binance": f"Binance ({base}/USDT)", "bitstamp": f"Bitstamp ({base}/USD)"}[src]
        except Exception as e:  # noqa: BLE001 - probeer volgende bron
            errors.append(f"{src}: {e}")
    raise RuntimeError("Downloaden mislukt - " + " | ".join(errors))
