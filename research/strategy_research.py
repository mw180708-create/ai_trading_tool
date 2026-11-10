"""Systematisch strategie-onderzoek op crypto-data met de regel-engine van wng.

Vooraf vastgelegde methode (om overfitting en zelfbedrog te beperken):
  1. Data: 10 munten (Binance, USDT-paren), dagcandles voor signalen, uurcandles voor de simulatie
     (stop loss / take profit binnen de dag), risico 1% per trade, kosten 0,08% per kant.
  2. Ontwikkelperiode t/m 31-12-2022: alle varianten testen. Toetsperiode 01-01-2023 tot nu: blind,
     alleen de vooraf gekozen beste variant wordt daar één keer op getoetst.
  3. Eén set parameters voor alle munten (geen afstemming per munt).
  4. Selectie op de ontwikkelperiode: gepoolde t-waarde van het resultaat per trade (R), met als eis dat
     minstens 70% van de munten winstgevend is en er minstens 100 trades zijn.
  5. Toevalstoets in de toetsperiode: dezelfde exits met willekeurige instapmomenten (permutatietest).

Gebruik:  python research/strategy_research.py <map-met-parquet-data>
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_tool import rules_engine as RE  # noqa: E402
from trading_tool.config import CostConfig, RiskConfig  # noqa: E402
from trading_tool.data_loader import build_multi_timeframe  # noqa: E402
from trading_tool.metrics import max_drawdown_pct  # noqa: E402

COINS = ["BTC", "ETH", "BNB", "XRP", "ADA", "SOL", "DOGE", "LTC", "LINK", "AVAX"]
SPLIT = pd.Timestamp("2023-01-01", tz="UTC")
COSTS = CostConfig(spread=0.0, commission_pct=0.0008)
RISK = RiskConfig(initial_balance=10_000, risk_per_trade=0.01)
OUT = Path(__file__).resolve().parent / "results"


def op(ind, tf=None, **params):
    d = {"ind": ind, "params": params}
    if tf:
        d["tf"] = tf
    return d


def spec(long, short=None, direction="long", stop=2.0, target=None, trail=0.0, max_bars=0, opposite=False,
         tf="1D", atr=20):
    s = {"signal_tf": tf, "direction": direction,
         "long": {"logic": "all", "conditions": long},
         "short": {"logic": "all", "conditions": short or []},
         "stop": {"type": "atr", "value": stop, "length": atr},
         "target": target or {"type": "none", "value": 0},
         "trailing_atr": trail, "trailing_length": atr, "max_bars": max_bars, "exit_on_opposite": opposite}
    return RE.normalize_rules(s)


def candidates() -> dict[str, dict]:
    c = {}
    for n, trail, d in itertools.product([20, 55, 100], [2.0, 3.0, 4.0], ["long", "both"]):
        c[f"donchian_n{n}_tr{trail:g}_{d}"] = spec(
            [{"left": op("close"), "op": ">", "right": op("highest", length=n)}],
            [{"left": op("close"), "op": "<", "right": op("lowest", length=n)}], d, stop=2.0, trail=trail)
    for n, trail, d in itertools.product([50, 100, 200], [2.0, 3.0, 4.0], ["long", "both"]):
        c[f"sma_n{n}_tr{trail:g}_{d}"] = spec(
            [{"left": op("close"), "op": "crosses_above", "right": op("sma", length=n)}],
            [{"left": op("close"), "op": "crosses_below", "right": op("sma", length=n)}], d, stop=2.0, trail=trail)
    for (f, sl), trail, d in itertools.product([(10, 30), (20, 50), (50, 200)], [3.0, 4.0], ["long", "both"]):
        c[f"emax_{f}_{sl}_tr{trail:g}_{d}"] = spec(
            [{"left": op("ema", length=f), "op": "crosses_above", "right": op("ema", length=sl)}],
            [{"left": op("ema", length=f), "op": "crosses_below", "right": op("ema", length=sl)}],
            d, stop=2.5, trail=trail, opposite=True)
    for lvl, hold, tgt in itertools.product([5, 10], [3, 5], ["time", "rr"]):
        c[f"rsi2_lt{lvl}_hold{hold}_{tgt}"] = spec(
            [{"left": op("rsi", length=2), "op": "<", "right": op("value", value=lvl)},
             {"left": op("close"), "op": ">", "right": op("sma", length=200)}],
            direction="long", stop=2.0, max_bars=hold, atr=14,
            target={"type": "rr", "value": 1.5} if tgt == "rr" else None)
    for trail, d in itertools.product([2.0, 3.0], ["long", "both"]):
        c[f"bbreak_tr{trail:g}_{d}"] = spec(
            [{"left": op("close"), "op": "crosses_above", "right": op("bb_upper", length=20, mult=2.0)}],
            [{"left": op("close"), "op": "crosses_below", "right": op("bb_lower", length=20, mult=2.0)}],
            d, stop=2.0, trail=trail)
    return c


def load(data_dir: Path, coin: str, end: pd.Timestamp | None = None):
    src = {}
    for tf in ("1D", "1H"):
        p = data_dir / f"{coin}USD_{tf}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            if end is not None:
                df = df[df.index < end]
            src[tf] = df
    return build_multi_timeframe(f"{coin}USD", src) if src else None


def run(mtf, s, start=None):
    return RE.run_rules_backtest(mtf, s, RISK, COSTS, start=start, name="r")


def summarize(results: dict[str, "object"]) -> dict:
    r_all = np.concatenate([res.trades["r_multiple"].to_numpy() for res in results.values() if not res.trades.empty]) \
        if any(not res.trades.empty for res in results.values()) else np.array([])
    per = {c: (res.trades["r_multiple"].sum() if not res.trades.empty else 0.0) for c, res in results.items()}
    n = len(r_all)
    mean = r_all.mean() if n else 0.0
    sd = r_all.std(ddof=1) if n > 1 else 0.0
    wins, losses = r_all[r_all > 0].sum(), -r_all[r_all < 0].sum()
    dd = [max_drawdown_pct(res.equity) for res in results.values()]
    return {"trades": n, "mean_R": mean, "t": mean / (sd / np.sqrt(n)) if sd > 0 else 0.0,
            "winrate": float((r_all > 0.05).mean() * 100) if n else 0.0,
            "pf": wins / losses if losses > 0 else np.inf, "total_R": r_all.sum(),
            "pct_coins_pos": float(np.mean([v > 0 for v in per.values()]) * 100),
            "median_coin_R": float(np.median(list(per.values()))), "worst_dd": float(min(dd)) if dd else 0.0,
            "per_coin_R": per}


def permutation_test(mtfs, s, start, actual_mean, sims=100, seed=1):
    """Willekeurige instapmomenten (zelfde aantal signalen, zelfde exits)."""
    rng = np.random.default_rng(seed)
    orig = RE.compute_signals
    means = []
    for _ in range(sims):
        def fake(mtf, spec_, _orig=orig):
            sg = _orig(mtf, spec_)
            for side in ("long", "short"):
                k = int(sg[side].sum())
                arr = np.zeros(len(sg[side]), bool)
                if k:
                    valid = np.nonzero(sg["close_ns"] >= pd.Timestamp(start).value)[0]
                    arr[rng.choice(valid, size=min(k, len(valid)), replace=False)] = True
                sg[side] = arr
            return sg
        RE.compute_signals = fake
        try:
            rs = [run(m, s, start).trades for m in mtfs.values()]
        finally:
            RE.compute_signals = orig
        r = np.concatenate([t["r_multiple"].to_numpy() for t in rs if not t.empty]) if rs else np.array([])
        means.append(r.mean() if len(r) else 0.0)
    means = np.array(means)
    return float((means >= actual_mean).mean()), float(means.mean()), float(np.percentile(means, 95))


def main(data_dir: str) -> None:
    data_dir = Path(data_dir)
    OUT.mkdir(exist_ok=True)
    cands = candidates()
    print(f"{len(cands)} varianten x {len(COINS)} munten", flush=True)

    # ---------------- ontwikkelperiode ----------------
    dev = {c: load(data_dir, c, end=SPLIT) for c in COINS}
    dev = {c: m for c, m in dev.items() if m is not None and len(m["1D"]) > 250}
    rows = []
    t0 = time.time()
    for i, (name, s) in enumerate(cands.items(), 1):
        res = {c: run(m, s) for c, m in dev.items()}
        sm = summarize(res)
        rows.append({"variant": name, **{k: v for k, v in sm.items() if k != "per_coin_R"}})
        if i % 10 == 0:
            print(f"  {i}/{len(cands)} ({time.time() - t0:.0f}s)", flush=True)
    devdf = pd.DataFrame(rows).sort_values("t", ascending=False)
    devdf.to_csv(OUT / "ontwikkelperiode.csv", index=False)

    eligible = devdf[(devdf.pct_coins_pos >= 70) & (devdf.trades >= 100)]
    best = (eligible if len(eligible) else devdf).iloc[0]["variant"]
    print("\nTop 10 ontwikkelperiode:\n", devdf.head(10)[["variant", "trades", "mean_R", "t", "winrate", "pf",
                                                           "pct_coins_pos", "worst_dd"]].round(3).to_string(index=False))
    print(f"\nVooraf gekozen variant: {best}", flush=True)

    # ---------------- toetsperiode (blind) ----------------
    full = {c: load(data_dir, c) for c in dev}
    test_res = {c: run(m, cands[best], start=SPLIT) for c, m in full.items()}
    tsum = summarize(test_res)
    p, rand_mean, rand_p95 = permutation_test(full, cands[best], SPLIT, tsum["mean_R"], sims=100)
    # ter vergelijking: beste variant per familie ook in de toetsperiode (niet gebruikt voor de keuze)
    fam = {}
    for fname in ("donchian", "sma", "emax", "rsi2", "bbreak"):
        sub = devdf[devdf.variant.str.startswith(fname)]
        if len(sub):
            v = sub.iloc[0]["variant"]
            fam[v] = {k: val for k, val in summarize({c: run(m, cands[v], start=SPLIT)
                                                    for c, m in full.items()}).items() if k != "per_coin_R"}
    # equity per munt + portfolio (gelijk kapitaal per munt)
    eq = pd.concat({c: r.equity[~r.equity.index.duplicated(keep="last")] for c, r in test_res.items()}, axis=1)
    eq = eq.sort_index().ffill().fillna(RISK.initial_balance)
    port = eq.sum(axis=1)
    bh = {}
    for c, m in full.items():
        d = m["1D"]["close"]
        d = d[d.index >= SPLIT]
        if len(d) > 1:
            bh[c] = d / d.iloc[0]
    bhp = pd.concat(bh, axis=1).ffill().mean(axis=1)
    years = (port.index[-1] - port.index[0]).days / 365.25
    out = {
        "variant": best, "rules": cands[best], "n_variants_tested": len(cands),
        "test": {k: v for k, v in tsum.items()},
        "permutation": {"p_value": p, "random_mean_R": rand_mean, "random_p95": rand_p95},
        "portfolio": {"start": float(port.iloc[0]), "end": float(port.iloc[-1]),
                      "return_pct": float((port.iloc[-1] / port.iloc[0] - 1) * 100),
                      "cagr_pct": float(((port.iloc[-1] / port.iloc[0]) ** (1 / years) - 1) * 100) if years > 0 else 0,
                      "max_dd_pct": float(max_drawdown_pct(port)), "years": years},
        "buy_hold": {"return_pct": float((bhp.iloc[-1] - 1) * 100), "max_dd_pct": float(max_drawdown_pct(bhp))},
        "family_best_in_test": fam,
    }
    (OUT / "toetsperiode.json").write_text(json.dumps(out, indent=1, default=float))
    port.to_frame("portfolio").join(bhp.rename("buy_hold") * port.iloc[0], how="outer").ffill() \
        .to_csv(OUT / "toetsperiode_equity.csv")
    pd.concat([r.trades for r in test_res.values() if not r.trades.empty]).to_csv(OUT / "toetsperiode_trades.csv",
                                                                                  index=False)
    print(json.dumps({k: v for k, v in out.items() if k != "rules"}, indent=1, default=float))


if __name__ == "__main__":
    main(sys.argv[1])
