"""Uitleg: gebruik, strategie-bouwer, data, community, accounts en beheer."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from trading_tool.rules_engine import INDICATORS, OPERATORS, STOP_TYPES, TARGET_TYPES

from .. import state as S


def render() -> None:
    st.markdown("## ℹ️ Uitleg")
    c1, c2 = st.columns(2, gap="large")
    with c1, st.container(key="panel_howto"):
        st.markdown("""
#### Zo werkt het
1. **Maak een account** (of probeer eerst als gast). Je data, strategieën en resultaten zijn alleen voor jou.
2. **🧠 Strategieën** – begin vanuit een sjabloon of leeg en stel je regels samen. Geen code nodig.
3. **📁 Data** – upload exports uit MetaTrader / TradingView (elke markt) of download crypto direct.
4. **▶️ Backtest** – kies strategie, markten en periode.
5. **📊 Resultaten / 📋 Trades** – winrate, drawdown, profit factor, equity curve, elke trade op de grafiek.
   Je laatste 30 backtests worden bewaard, zodat je strategieën kunt vergelijken.
6. **🏠 Dashboard** – de actuele stand van je strategie op de nieuwste data.

#### Twee soorten strategieën
- **Indicatoren & regels**: voorwaarden zoals *EMA(20) kruist boven EMA(50)* of *RSI(14) kleiner dan 30*,
  eventueel op een hogere timeframe (*Close groter dan EMA(200) [1D]*). Kies stop loss, take profit,
  break-even, trailing stop, maximale duur en handelsuren.
- **Smart Money (POI & liquiditeit)**: het multi-timeframe model van het Trading Plan 2026-2028 –
  timeframe-combinaties, POI-timeframes, confirmatie (POI in POI), RR-filter en break-even per type trade.

#### Eerlijk backtesten
- Signalen gebruiken alleen gesloten candles; hogere timeframes alleen hun laatst gesloten candle.
- De simulatie loopt op de fijnste data die je hebt (1m is het best). Raken SL en TP dezelfde candle, dan telt de SL.
- Spread en commissie stel je per markt in. Risico per trade komt uit de strategie (standaard 1%).
""")
    with c2, st.container(key="panel_ind"):
        st.markdown("#### Indicatoren")
        st.dataframe(pd.DataFrame([{"Indicator": v[0], "Instelling (volgorde)": ", ".join(f"{n} ({d:g})" for n, d, *_ in v[1]) or "-"}
                                   for v in INDICATORS.values()]), hide_index=True, width="stretch", height=420)
        st.markdown("**Vergelijkingen:** " + ", ".join(OPERATORS.values()))
        st.markdown("**Stop loss:** " + ", ".join(STOP_TYPES.values()))
        st.markdown("**Take profit:** " + ", ".join(TARGET_TYPES.values()))
    with st.container(key="panel_share"):
        st.markdown("""
#### Community & privacy
- Zet bij een strategie **Delen met community** aan om hem zichtbaar te maken voor anderen. Zij kunnen hem
  kopiëren en aanpassen. Alleen de **regels** worden gedeeld – nooit je data of resultaten.
- **Gedeelde data** is koersdata die de beheerder voor iedereen klaarzet. Je eigen data gaat altijd voor.
- Wachtwoorden worden versleuteld (scrypt-hash) opgeslagen en nooit leesbaar bewaard.
""")
    if S.is_admin() or not S.admins():
        with st.container(key="panel_admin"):
            st.markdown("""
#### Voor de beheerder van deze website
Instellingen in Streamlit → je app → **⋮ → Settings → Secrets**:
""")
            st.code(f'GITHUB_TOKEN = "ghp_..."            # blijvende opslag (zie Data → GitHub koppelen)\n'
                    f'GITHUB_REPO = "{S.DEFAULT_REPO}"\n'
                    f'ADMIN_USERS = "jouw-gebruikersnaam"  # beheerders (komma-gescheiden)\n'
                    f'ALLOW_SIGNUP = "true"                # "false" = geen nieuwe accounts meer', language="toml")
            st.caption("Beheerders kunnen data in de gedeelde bibliotheek zetten en de GitHub-koppeling beheren. "
                       "Zet de GitHub-repository op privé: daar staan alle accounts, data en strategieën.")
    st.caption("Een backtest is geen garantie voor de toekomst; deze website geeft geen financieel advies.")
