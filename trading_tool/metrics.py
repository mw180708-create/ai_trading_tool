"""Stap 5: Backtest metrics & performance-overzicht."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .backtester import BacktestResult


def max_drawdown_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return float(((equity - peak) / peak).min() * 100)


def compute_metrics(trades: pd.DataFrame, equity: pd.Series, initial: float) -> dict:
    m: dict = {"Trades": 0}
    if trades is None or trades.empty:
        return m
    r = trades["r_multiple"]
    pnl = trades["pnl"]
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gross_loss = -losses.sum()
    m.update({
        "Trades": len(trades),
        "Swing": int((trades["trade_type"] == "Swing").sum()),
        "Intraday": int((trades["trade_type"] == "Intraday").sum()),
        "Scalp": int((trades["trade_type"] == "Scalp").sum()),
        "Winrate %": 100 * (r > 0.05).mean(),
        "Break-even %": 100 * (r.abs() <= 0.05).mean(),
        "Avg planned RR": trades["planned_rr"].mean(),
        "Avg win R": r[r > 0.05].mean() if (r > 0.05).any() else 0.0,
        "Avg R/trade": r.mean(),
        "Total R": r.sum(),
        "Profit Factor": (wins.sum() / gross_loss) if gross_loss > 0 else np.inf,
        "Net Profit": pnl.sum(),
        "Net Profit %": 100 * pnl.sum() / initial,
        "Max DD %": max_drawdown_pct(equity),
    })
    return m


def _fmt(v) -> str:
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, float):
        if np.isinf(v):
            return "inf"
        return f"{v:,.2f}"
    return str(v)


COUNT_ROWS = ("Trades", "Swing", "Intraday", "Scalp")


def format_report(report: pd.DataFrame, money_rows: tuple[str, ...] = ()) -> pd.DataFrame:
    """Maak een leesbare tekst-tabel (hele getallen voor aantallen, $ voor bedragen)."""
    def cell(row: str, v) -> str:
        if pd.isna(v):
            return "-"
        if row in COUNT_ROWS:
            return f"{int(v):,}"
        if row in money_rows:
            return f"{'-' if v < 0 else ''}${abs(v):,.0f}"
        return _fmt(float(v)) if isinstance(v, (float, np.floating)) else _fmt(v)
    return pd.DataFrame({col: [cell(r, v) for r, v in report[col].items()] for col in report.columns},
                        index=report.index)


def combined_equity(results: list[BacktestResult]) -> pd.Series:
    """Totaal = som van de afzonderlijke funded accounts."""
    if not results:
        return pd.Series(dtype=float)
    curves = [r.equity[~r.equity.index.duplicated(keep="last")] for r in results]
    idx = curves[0].index
    for cu in curves[1:]:
        idx = idx.union(cu.index)
    return sum(cu.reindex(idx).ffill().fillna(cu.iloc[0]) for cu in curves)


def build_report(results: list[BacktestResult]) -> pd.DataFrame:
    rows = {}
    for res in results:
        rows[res.symbol] = compute_metrics(res.trades, res.equity, res.initial_balance)
    if len(results) > 1:
        all_trades = pd.concat([r.trades for r in results if not r.trades.empty], ignore_index=True) \
            if any(not r.trades.empty for r in results) else pd.DataFrame()
        initial = sum(r.initial_balance for r in results)
        rows["TOTAAL"] = compute_metrics(all_trades, combined_equity(results), initial)
    return pd.DataFrame(rows)


def breakdown_by(trades: pd.DataFrame, col: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    g = trades.groupby([ "symbol", col])
    return pd.DataFrame({
        "Trades": g.size(),
        "Winrate %": g["r_multiple"].apply(lambda r: 100 * (r > 0.05).mean()),
        "Avg R": g["r_multiple"].mean(),
        "Total R": g["r_multiple"].sum(),
        "Net Profit": g["pnl"].sum(),
    })


def print_report(results: list[BacktestResult]) -> pd.DataFrame:
    report = build_report(results)
    line = "=" * 78
    print(f"\n{line}\n  wng · backtest-resultaten\n{line}")
    if "Trades" not in report.index or report.loc["Trades"].fillna(0).sum() == 0:
        print("  Geen trades gegenereerd.")
    printable = format_report(report)
    print(printable.to_string())

    all_trades = [r.trades for r in results if not r.trades.empty]
    if all_trades:
        t = pd.concat(all_trades, ignore_index=True)
        print("\n--- Per trade type ---")
        print(breakdown_by(t, "trade_type").round(2).to_string())
        print("\n--- Per POI timeframe ---")
        print(breakdown_by(t, "poi_tf").round(2).to_string())
        print("\n--- Exit redenen ---")
        print(t.groupby(["symbol", "exit_reason"]).size().unstack(fill_value=0).to_string())

    print("\n--- Signaal-filter statistieken ---")
    for r in results:
        s = r.stats
        print(f"  {r.symbol}: confirmaties={s.get('signals', 0)}, overgeslagen RR-filter={s.get('skip_rr', 0)}, "
              f"geen TP-liquiditeit={s.get('skip_no_tp', 0)}, ongeldige SL={s.get('skip_sl', 0)}")
    print(line)
    return report


def save_outputs(results: list[BacktestResult], report: pd.DataFrame, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    report.to_csv(out / "summary.csv"); written.append(out / "summary.csv")
    for r in results:
        p = out / f"trades_{r.symbol}.csv"
        r.trades.to_csv(p, index=False); written.append(p)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(11, 5))
        for r in results:
            ax.step(r.equity.index, r.equity.values, where="post", label=r.symbol, linewidth=1.4)
        if len(results) > 1:
            tot = combined_equity(results)
            ax.step(tot.index, tot.values, where="post", label="TOTAAL", linewidth=2, color="black")
        ax.set_title("Equity curve (gerealiseerd) - 1% risico per trade")
        ax.set_ylabel("Balance")
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / "equity_curve.png", dpi=130)
        plt.close(fig)
        written.append(out / "equity_curve.png")
    except ImportError:
        print("  (matplotlib niet geinstalleerd -> geen equity_curve.png)")
    return written
