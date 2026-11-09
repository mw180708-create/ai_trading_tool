"""Inlezen van TradingView / MetaTrader / crypto CSV-exports en multi-timeframe opbouw.

Ondersteunde formaten (automatisch herkend):
  * MetaTrader 5 export:  <DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> ...
  * MetaTrader 4 export:  2024.01.02,00:00,2062.1,2063.0,2061.5,2062.8,123   (geen header)
  * TradingView export:   time,open,high,low,close,Volume   (unix-seconden of ISO)
  * ccxt / Binance:       timestamp (ms),open,high,low,close,volume
  * Dukascopy:            "Gmt time",Open,High,Low,Close,Volume
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import PANDAS_RULE, TF_MINUTES, TIMEFRAMES, normalize_tf, tf_bar_close

OHLC = ["open", "high", "low", "close"]


# --------------------------------------------------------------------------- #
# CSV inlezen
# --------------------------------------------------------------------------- #
def _parse_time_column(s: pd.Series) -> pd.DatetimeIndex:
    if pd.api.types.is_numeric_dtype(s):
        v = s.astype("int64")
        unit = "ms" if v.abs().max() > 10**11 else "s"
        return pd.DatetimeIndex(pd.to_datetime(v, unit=unit, utc=True))
    txt = s.astype(str).str.strip()
    txt = txt.str.replace(r"^(\d{4})\.(\d{2})\.(\d{2})", r"\1-\2-\3", regex=True)  # MT 2024.01.02
    return pd.DatetimeIndex(pd.to_datetime(txt, utc=True, format="mixed", dayfirst=False))


def read_ohlc_csv(path: str | Path) -> pd.DataFrame:
    """Lees een OHLC CSV en geef DataFrame [open, high, low, close, volume] met UTC index."""
    path = Path(path)
    with open(path, "r", encoding="utf-8-sig") as fh:
        first = fh.readline()

    has_header = bool(re.search(r"[A-Za-z]", first.replace("<", "").split(",")[0].split("\t")[0]))
    sep = "\t" if "\t" in first else ("," if "," in first else ";" if ";" in first else r"\s+")

    if not has_header:  # MT4 history export
        raw = pd.read_csv(path, sep=sep, header=None, engine="python")
        cols = ["date", "time", "open", "high", "low", "close", "volume"][: raw.shape[1]]
        raw = raw.iloc[:, : len(cols)]
        raw.columns = cols
    else:
        raw = pd.read_csv(path, sep=sep, engine="python")
        raw.columns = [c.strip().strip("<>").strip().lower() for c in raw.columns]

    cols = set(raw.columns)
    if {"date", "time"} <= cols:
        ts = _parse_time_column(raw["date"].astype(str) + " " + raw["time"].astype(str))
    else:
        tcol = next((c for c in ["time", "timestamp", "datetime", "date", "gmt time",
                                 "local time", "open time", "open_time"] if c in cols), None)
        if tcol is None:
            raise ValueError(f"{path}: geen tijdkolom gevonden in {list(raw.columns)}")
        ts = _parse_time_column(raw[tcol])

    vol_col = next((c for c in ["volume", "tickvol", "vol", "tick_volume"] if c in cols), None)
    df = pd.DataFrame({
        "open": raw["open"].astype(float).values,
        "high": raw["high"].astype(float).values,
        "low": raw["low"].astype(float).values,
        "close": raw["close"].astype(float).values,
        "volume": raw[vol_col].astype(float).values if vol_col else 0.0,
    }, index=ts)
    df.index.name = "time"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.dropna(subset=OHLC)


# --------------------------------------------------------------------------- #
# Resampling
# --------------------------------------------------------------------------- #
def resample_ohlc(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    out = df.resample(PANDAS_RULE[tf], label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=OHLC)


def detect_tf(df: pd.DataFrame) -> str:
    """Raad de timeframe van een DataFrame aan de hand van de mediane bar-afstand."""
    minutes = df.index.to_series().diff().dropna().dt.total_seconds().median() / 60
    if minutes >= 28 * 1440:
        return "1M"
    if minutes >= 6 * 1440:
        return "1W"
    best = min((tf for tf in TF_MINUTES if tf not in ("1M", "1W")),
               key=lambda t: abs(TF_MINUTES[t] - minutes))
    return best


# --------------------------------------------------------------------------- #
# Multi-timeframe container
# --------------------------------------------------------------------------- #
@dataclass
class MultiTimeframeData:
    symbol: str
    frames: dict[str, pd.DataFrame]   # tf -> OHLC met kolom 'close_time'
    base_tf: str                      # fijnste TF = executie / simulatie TF

    def __getitem__(self, tf: str) -> pd.DataFrame:
        return self.frames[tf]

    def __contains__(self, tf: str) -> bool:
        return tf in self.frames

    def summary(self) -> str:
        lines = [f"{self.symbol} (executie-TF: {self.base_tf})"]
        for tf in TIMEFRAMES:
            if tf in self.frames:
                f = self.frames[tf]
                lines.append(f"  {tf:>4}: {len(f):>8} bars  {f.index[0]:%Y-%m-%d} -> {f.index[-1]:%Y-%m-%d}")
        return "\n".join(lines)


def build_multi_timeframe(symbol: str, sources: dict[str, pd.DataFrame]) -> MultiTimeframeData:
    """Bouw alle timeframes 1M..1m op.

    `sources` = {tf: DataFrame} met de data die je hebt (bijv. 1m voor de backtest-periode
    en 1D met lange historie voor de Monthly/Weekly analyse). Elke TF wordt opgebouwd door
    te resamplen van de fijnste bron; waar een eigen bestand voor die TF meer historie heeft,
    wordt dat ervóór geplakt (warm-up).
    """
    sources = {normalize_tf(k): v for k, v in sources.items()}
    if not sources:
        raise ValueError(f"Geen data voor {symbol}")
    order = sorted(sources, key=lambda t: TF_MINUTES[t])
    base_tf = order[0]

    frames: dict[str, pd.DataFrame] = {}
    for tf in TIMEFRAMES:
        if TF_MINUTES[tf] < TF_MINUTES[base_tf]:
            continue  # lager dan de fijnste data -> niet beschikbaar
        # fijnste bron die nog <= tf is
        finer = [s for s in order if TF_MINUTES[s] <= TF_MINUTES[tf]]
        pieces = []
        built = None
        for src in finer:  # fijn -> grof
            part = sources[src] if src == tf else resample_ohlc(sources[src], tf)
            if built is None:
                built = part
            else:  # alleen oudere historie toevoegen
                older = part[part.index < built.index[0]]
                if len(older):
                    pieces.append(older)
        frame = pd.concat(pieces[::-1] + [built]) if pieces else built
        frame = frame[~frame.index.duplicated(keep="last")].sort_index().copy()
        frame["close_time"] = tf_bar_close(frame.index, tf)
        frames[tf] = frame
    return MultiTimeframeData(symbol=symbol, frames=frames, base_tf=base_tf)


_FILE_RE = re.compile(r"^(?P<sym>[A-Za-z]+)[_\-\s,]+(?P<tf>[A-Za-z0-9]+)", re.I)


def discover_files(data_dir: str | Path) -> dict[str, dict[str, Path]]:
    """Zoek bestanden als  data/BTCUSD_1m.csv, data/XAUUSD_H4.csv, data/XAUUSD_1D.csv ..."""
    found: dict[str, dict[str, Path]] = {}
    for p in sorted(Path(data_dir).glob("*.csv")):
        m = _FILE_RE.match(p.stem)
        if not m:
            continue
        sym = m["sym"].upper().replace("XAUUSDT", "XAUUSD").replace("BTCUSDT", "BTCUSD")
        try:
            tf = normalize_tf(m["tf"])  # let op: 1M = maand, 1m = minuut
        except ValueError:
            continue
        found.setdefault(sym, {})[tf] = p
    return found


def load_symbol(symbol: str, files: dict[str, str | Path],
                start: str | None = None, end: str | None = None) -> MultiTimeframeData:
    sources = {}
    for tf, path in files.items():
        df = read_ohlc_csv(path)
        if end:
            df = df[df.index < pd.Timestamp(end, tz="UTC")]
        sources[normalize_tf(tf)] = df
    mtf = build_multi_timeframe(symbol, sources)
    mtf.backtest_start = pd.Timestamp(start, tz="UTC") if start else None  # type: ignore[attr-defined]
    return mtf


def to_numpy_ns(idx: pd.DatetimeIndex | pd.Series) -> np.ndarray:
    """Datetime -> int64 nanoseconden (UTC) voor snelle vergelijkingen."""
    return pd.DatetimeIndex(idx).tz_convert("UTC").as_unit("ns").asi8
