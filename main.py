#!/usr/bin/env python3
"""Backtest het Trading Plan 2026-2028 op BTCUSD en XAUUSD.

Voorbeelden
-----------
  # Demo met synthetische data (test of alles werkt)
  python main.py --demo

  # Alle CSV's in ./data automatisch (bestandsnaam: SYMBOOL_TF.csv, bv. BTCUSD_1m.csv, XAUUSD_1D.csv)
  python main.py --data-dir data

  # Expliciet per asset
  python main.py --asset BTCUSD:1m=data/btc_1m.csv,1D=data/btc_daily.csv \
                 --asset XAUUSD:1m=data/XAUUSD_M1.csv,1D=data/XAUUSD_D1.csv --start 2024-01-01
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace

import pandas as pd

from trading_tool.backtester import Backtester
from trading_tool.config import DEFAULT_COSTS, CostConfig, RiskConfig, StrategyConfig
from trading_tool.data_loader import discover_files, load_symbol
from trading_tool.metrics import print_report, save_outputs
from trading_tool.synthetic import demo_dataset

SYMBOLS = ["BTCUSD", "XAUUSD"]


def parse_asset(spec: str) -> tuple[str, dict[str, str]]:
    sym, _, rest = spec.partition(":")
    files = dict(part.split("=", 1) for part in rest.split(",") if part)
    return sym.upper(), files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Trading Plan 2026-2028 backtester (BTCUSD / XAUUSD)")
    ap.add_argument("--demo", action="store_true", help="draai op synthetische data")
    ap.add_argument("--data-dir", default="data", help="map met SYMBOOL_TF.csv bestanden")
    ap.add_argument("--asset", action="append", default=[], help="SYMBOOL:TF=pad,TF=pad (herhaalbaar)")
    ap.add_argument("--symbols", default=",".join(SYMBOLS), help="welke symbolen (default BTCUSD,XAUUSD)")
    ap.add_argument("--start", help="start backtest (oudere data = warm-up), bv. 2024-01-01")
    ap.add_argument("--end", help="einde backtest, bv. 2025-12-31")
    ap.add_argument("--balance", type=float, default=100_000, help="startbalans per funded account")
    ap.add_argument("--risk", type=float, default=0.01, help="risico per trade (0.01 = 1%%)")
    ap.add_argument("--min-rr", type=float, default=2.0, help="minimale Risk-to-Reward")
    ap.add_argument("--no-adaptive-rr", action="store_true", help="schakel dynamische RR-eis uit")
    ap.add_argument("--confirmation", choices=["bos", "first_candle"], default="bos")
    ap.add_argument("--tp-source", choices=["poi_tf", "poi_tf_and_higher"], default="poi_tf")
    ap.add_argument("--no-costs", action="store_true", help="geen spread/commissie")
    ap.add_argument("--out", default="results", help="output map")
    args = ap.parse_args(argv)

    strategy = StrategyConfig(min_rr=args.min_rr, adaptive_rr=not args.no_adaptive_rr,
                              confirmation_mode=args.confirmation, tp_source=args.tp_source)
    risk = RiskConfig(initial_balance=args.balance, risk_per_trade=args.risk)
    wanted = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    # ---------------- data ----------------
    datasets = []
    if args.demo:
        print("DEMO-modus: synthetische data (resultaten zeggen NIETS over de echte markt)\n")
        for i, sym in enumerate(wanted):
            datasets.append(demo_dataset(sym, seed=i))
    else:
        specs = dict(parse_asset(a) for a in args.asset)
        if not specs:
            specs = {s: {tf: str(p) for tf, p in f.items()} for s, f in discover_files(args.data_dir).items()}
        specs = {s: f for s, f in specs.items() if s in wanted}
        if not specs:
            print(f"Geen data gevonden in '{args.data_dir}'. Zet bv. BTCUSD_1m.csv / XAUUSD_1D.csv daar neer,\n"
                  f"gebruik --asset, draai download_data.py, of probeer --demo.")
            return 1
        for sym, files in specs.items():
            print(f"Laden {sym}: {files}")
            datasets.append(load_symbol(sym, files, start=args.start, end=args.end))

    # ---------------- backtest ----------------
    results = []
    for mtf in datasets:
        print("\n" + mtf.summary())
        costs = CostConfig() if args.no_costs else DEFAULT_COSTS.get(mtf.symbol, CostConfig())
        t0 = time.time()
        res = Backtester(mtf, strategy, replace(risk), costs).run()
        print(f"  -> {len(res.trades)} trades in {time.time() - t0:.1f}s")
        results.append(res)

    report = print_report(results)
    files = save_outputs(results, report, args.out)
    print("\nOutput opgeslagen:")
    for f in files:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
