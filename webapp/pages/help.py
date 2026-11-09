"""Uitleg: gebruik, data-bronnen, regels van het plan en GitHub-koppeling."""
from __future__ import annotations

import streamlit as st

from .. import state as S


def render() -> None:
    st.markdown("## ℹ️ Uitleg")
    c1, c2 = st.columns(2, gap="large")
    with c1, st.container(key="panel_howto"):
        st.markdown("""
#### Zo gebruik je de website
1. **📁 Data** – upload exports (MetaTrader / TradingView) of download BTC-data. Alles komt in je **bibliotheek** en blijft bewaard.
2. **▶️ Backtest** – kies assets en instellingen en klik op *Start backtest*.
3. **📊 Resultaten** – winst, winrate, drawdown, profit factor, equity curve en uitsplitsingen.
4. **📋 Trades** – alle trades; klik op een trade om hem op de grafiek te zien (POI, entry, SL, TP).
5. **🏠 Dashboard** – de actuele stand van je regels op de nieuwste data (Bias Engine + beslissing).

#### Data-tips
- Gebruik **1-minuut data** voor de backtest + **1D-data met jaren historie** voor de Monthly/Weekly analyse.
- Bestandsnamen zoals `XAUUSD_M1.csv`, `XAUUSD_D1.csv`, `BTCUSD_1H.csv` worden automatisch herkend
  (let op: `1M` = maand, `1m` = minuut).
- Nieuwe uploads worden samengevoegd met bestaande data: je kunt elke maand alleen de nieuwste maand toevoegen.
""")
    with c2, st.container(key="panel_rules"):
        st.markdown("""
#### De regels van het Trading Plan
| Stap | Regel |
|---|---|
| **1 · Bias** | Match op 1M+1W+1D, 1W+1D+4H, 1M+1D+1H of 1D+4H+1H (alleen Scalp). Liquiditeit én balance level dezelfde kant op, anders 50/50 → geen trade. |
| **2 · POI** | Alleen POI's in bias-richting (1M/1W/1D/4H/1H): zone tussen liquiditeit (wick) en protected zone (body). |
| **3 · Entry** | Monthly → 4H, Weekly → 1H, Daily → 15m, 4H → 5m, 1H → 1m balance shift. SL op het dichtstbijzijnde 1H protected level, TP op de eerstvolgende liquiditeit, alleen bij voldoende RR. |
| **4 · Management** | Swing (M/W POI): break-even bij 2R. Intraday & Scalp (D/4H/1H POI): break-even bij 4R. Geen partials. |
| **Risico** | Exact 1% per trade, max. 1 open trade per account. |

*Bias Engine*: per timeframe zie je **Liquiditeit** (laatste sweep / draw on liquidity), **Balance** (richting van de
laatste balance shift) en de **Bias** (beide gelijk). De **bias-score** (0-100) is het gemiddelde van de 5 timeframes:
50 = neutraal, hoger = bullish, lager = bearish.
""")
    with st.container(key="panel_github"):
        st.markdown(f"""
#### Data blijvend bewaren met GitHub
Status: **{"gekoppeld ✓" if S.store().synced else "niet gekoppeld (alleen tijdelijk bewaard op de online website)"}**

Ga naar **📁 Data** → **GitHub koppelen**. Daar maak je in 3 stappen een token, plak je het op de website en
test je het meteen. Je krijgt precies te zien wat je in Streamlit → Settings → **Secrets** moet plakken:
""")
        st.code(f'GITHUB_TOKEN = "ghp_..."\nGITHUB_REPO = "{S.DEFAULT_REPO}"', language="toml")
        st.caption("Je data komt dan in de map data/store/ van je repository. Een backtest is geen garantie voor de toekomst; "
                   "de website geeft geen financieel advies.")
