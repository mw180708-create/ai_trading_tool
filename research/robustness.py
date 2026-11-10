"""Robuustheidscontroles voor de gekozen strategie in de toetsperiode (2023 - nu).

* Eén gedeelde rekening: alle munten, vast risico per trade als % van de startbalans (R-curve).
* Resultaat per jaar, long vs short, kosten x2, buren in de parameterruimte.
Gebruik:  python research/robustness.py <map-met-parquet-data>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import strategy_research as R  # noqa: E402
from trading_tool.config import CostConfig  # noqa: E402
from trading_tool import rules_engine as RE  # noqa: E402


def trades_for(full, s, start, costs=None):
    out = []
    for c, m in full.items():
        res = RE.run_rules_backtest(m, s, R.RISK, costs or R.COSTS, start=start, name="r")
        if not res.trades.empty:
            out.append(res.trades)
    return pd.concat(out, ignore_index=True).sort_values("exit_time") if out else pd.DataFrame()


def r_curve_stats(t: pd.DataFrame, risk_pct: float) -> dict:
    curve = (t.set_index("exit_time")["r_multiple"].cumsum()) * risk_pct      # % van startbalans
    peak = curve.cummax()
    dd = (curve - peak).min()
    # open posities tegelijk (risico-blootstelling)
    ev = pd.concat([pd.Series(1, index=t.entry_time), pd.Series(-1, index=t.exit_time)]).sort_index().cumsum()
    years = (t.exit_time.max() - t.entry_time.min()).days / 365.25
    return {"return_pct": float(curve.iloc[-1]), "per_year_pct": float(curve.iloc[-1] / years),
            "max_dd_pct": float(dd), "return_to_dd": float(curve.iloc[-1] / abs(dd)) if dd < 0 else None,
            "max_open": int(ev.max()), "avg_open": float(ev.mean())}


def main(data_dir: str) -> None:
    data_dir = Path(data_dir)
    cands = R.candidates()
    full = {c: R.load(data_dir, c) for c in R.COINS}
    full = {c: m for c, m in full.items() if m is not None}
    out = {}
    for name in ["bbreak_tr2_both", "bbreak_tr2_long"]:
        t = trades_for(full, cands[name], R.SPLIT)
        yr = t.groupby(t.exit_time.dt.year)["r_multiple"].agg(["count", "sum", "mean"]).round(3)
        side = t.groupby("direction")["r_multiple"].agg(["count", "sum", "mean"]).round(3)
        t2 = trades_for(full, cands[name], R.SPLIT, CostConfig(spread=0.0, commission_pct=0.0016))
        out[name] = {
            "shared_account_1pct": r_curve_stats(t, 1.0),
            "shared_account_0.5pct": r_curve_stats(t, 0.5),
            "per_year": yr.reset_index().to_dict("records"),
            "per_side": side.reset_index().to_dict("records"),
            "double_costs_mean_R": float(t2["r_multiple"].mean()),
            "double_costs_total_R": float(t2["r_multiple"].sum()),
            "avg_win_R": float(t.r_multiple[t.r_multiple > 0].mean()),
            "avg_loss_R": float(t.r_multiple[t.r_multiple < 0].mean()),
            "largest_win_R": float(t.r_multiple.max()),
            "max_consecutive_losses": int((t.r_multiple < 0).astype(int).groupby((t.r_multiple >= 0).cumsum()).sum().max()),
            "avg_bars_held_days": float(((t.exit_time - t.entry_time).dt.total_seconds() / 86400).mean()),
        }
        t.to_csv(R.OUT / f"toets_trades_{name}.csv", index=False)
    # buren (in de toetsperiode) - alleen ter controle van robuustheid, niet voor de keuze
    neigh = {}
    for name in ["bbreak_tr2_both", "bbreak_tr3_both", "bbreak_tr2_long", "bbreak_tr3_long", "donchian_n20_tr2_both",
                 "donchian_n20_tr3_both", "donchian_n55_tr3_both", "sma_n50_tr3_both", "emax_20_50_tr3_both"]:
        t = trades_for(full, cands[name], R.SPLIT)
        neigh[name] = {"trades": len(t), "mean_R": round(float(t.r_multiple.mean()), 3),
                       "total_R": round(float(t.r_multiple.sum()), 1)}
    out["neighbours_in_test"] = neigh
    (R.OUT / "robuustheid.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main(sys.argv[1])
