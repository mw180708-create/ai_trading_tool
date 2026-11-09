#!/usr/bin/env python3
"""Historische data ophalen en opslaan als data/SYMBOOL_TF.csv.

  python download_data.py binance --tf 1m --since 2024-01-01      # BTCUSD via ccxt (Binance BTC/USDT)
  python download_data.py binance --tf 1d --since 2017-08-01      # lange historie voor 1M/1W
  python download_data.py yahoo                                   # XAUUSD (goud futures GC=F) 1D + 1H
  python download_data.py mt5 --symbol XAUUSD --tf 1m --since 2024-01-01   # alleen Windows + MT5 terminal

TradingView: open de chart -> menu (pijltje bij chart-naam) -> "Export chart data..." en sla op
als data/XAUUSD_1D.csv, data/BTCUSD_1H.csv, enz.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"
TF_FILE = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W", "1M": "1M"}


def save(df: pd.DataFrame, symbol: str, tf: str) -> Path:
    DATA.mkdir(exist_ok=True)
    path = DATA / f"{symbol}_{TF_FILE.get(tf, tf)}.csv"
    df.index.name = "time"
    df.to_csv(path, date_format="%Y-%m-%d %H:%M:%S")
    print(f"Opgeslagen: {path} ({len(df)} bars, {df.index[0]} -> {df.index[-1]})")
    return path


def from_binance(tf: str, since: str, until: str | None, exchange: str = "binance",
                 market: str = "BTC/USDT") -> None:
    import ccxt  # pip install ccxt

    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    ms = ex.parse8601(f"{since}T00:00:00Z")
    end = ex.parse8601(f"{until}T00:00:00Z") if until else ex.milliseconds()
    rows = []
    while ms < end:
        batch = ex.fetch_ohlcv(market, timeframe=tf, since=ms, limit=1000)
        if not batch:
            break
        rows += batch
        ms = batch[-1][0] + 1
        print(f"\r  {pd.to_datetime(batch[-1][0], unit='ms')}  ({len(rows)} bars)", end="", flush=True)
        time.sleep(ex.rateLimit / 1000)
    print()
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
    df = df[~df.index.duplicated()]
    save(df[df.index < pd.Timestamp(end, unit="ms", tz="UTC")], "BTCUSD", tf)


def from_yahoo(ticker: str = "GC=F", symbol: str = "XAUUSD") -> None:
    import yfinance as yf  # pip install yfinance

    for interval, period, tf in [("1d", "max", "1d"), ("1h", "730d", "1h")]:
        df = yf.download(ticker, period=period, interval=interval, auto_adjust=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()
        df.index = pd.DatetimeIndex(df.index).tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
        save(df, symbol, tf)


def from_mt5(symbol: str, tf: str, since: str, until: str | None) -> None:
    import MetaTrader5 as mt5  # pip install MetaTrader5 (Windows)

    tf_map = {"1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15,
              "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1,
              "1w": mt5.TIMEFRAME_W1, "1M": mt5.TIMEFRAME_MN1}
    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize() mislukt: {mt5.last_error()}")
    start = pd.Timestamp(since, tz="UTC").to_pydatetime()
    end = (pd.Timestamp(until, tz="UTC") if until else pd.Timestamp.now(tz="UTC")).to_pydatetime()
    rates = mt5.copy_rates_range(symbol, tf_map[tf], start, end)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise SystemExit(f"Geen data voor {symbol} {tf}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df.index = pd.to_datetime(df.pop("time"), unit="s", utc=True)  # let op: MT5 = servertijd van broker
    df = df.rename(columns={"tick_volume": "volume"})[["open", "high", "low", "close", "volume"]]
    save(df, symbol.upper().replace(".", "")[:6], tf)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=["binance", "yahoo", "mt5"])
    ap.add_argument("--tf", default="1m", help="1m,5m,15m,1h,4h,1d,1w,1M")
    ap.add_argument("--since", default="2024-01-01")
    ap.add_argument("--until")
    ap.add_argument("--symbol", default="XAUUSD", help="(mt5) broker-symbool, bv. XAUUSD of BTCUSD")
    ap.add_argument("--exchange", default="binance", help="(binance) ccxt exchange id, bv. bybit, kraken")
    a = ap.parse_args()
    if a.source == "binance":
        from_binance(a.tf, a.since, a.until, a.exchange)
    elif a.source == "yahoo":
        from_yahoo()
    else:
        from_mt5(a.symbol, a.tf, a.since, a.until)
