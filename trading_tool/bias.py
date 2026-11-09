"""Stap 1: Multi-Timeframe Confluence (bias-match) - gevectoriseerd op de executie-TF."""
from __future__ import annotations

import numpy as np

from .config import BIAS_COMBOS


def combo_direction(bias_at: dict[str, np.ndarray], combo: tuple[str, ...], n: int) -> np.ndarray:
    """+1/-1 als ALLE timeframes in de combinatie dezelfde (niet-50/50) bias hebben, anders 0."""
    if any(tf not in bias_at for tf in combo):
        return np.zeros(n, np.int8)
    first = bias_at[combo[0]]
    ok = first != 0
    for tf in combo[1:]:
        ok &= bias_at[tf] == first
    return np.where(ok, first, 0).astype(np.int8)


def compute_confluence(bias_at: dict[str, np.ndarray], n: int, combos=None) -> dict[str, np.ndarray]:
    """Retourneert per executie-bar:

    standard_dir : richting als een van de combinaties 1M+1W+1D, 1W+1D+4H, 1M+1D+1H matcht
    scalp_dir    : richting als 1D+4H+1H matcht (Scalp)
    combo_id     : index (1..4) van de eerste matchende combinatie, 0 = Geen Match
    """
    standard = np.zeros(n, np.int8)
    scalp = np.zeros(n, np.int8)
    combo_id = np.zeros(n, np.int8)
    for i, (combo, kind) in enumerate(combos if combos is not None else BIAS_COMBOS, start=1):
        d = combo_direction(bias_at, tuple(combo), n)
        hit = (d != 0) & (combo_id == 0)
        combo_id[hit] = i
        if kind == "scalp":
            scalp = np.where(scalp == 0, d, scalp)
        else:
            standard = np.where(standard == 0, d, standard)
    return {"standard_dir": standard, "scalp_dir": scalp, "combo_id": combo_id}
