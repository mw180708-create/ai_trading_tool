# wng

Backtest-platform: stel een strategie samen zonder te programmeren, upload je eigen koersdata en zie hoe de
strategie in het verleden had gepresteerd.

## Het platform (website)

Een backtest-platform waarop **iedereen** met een eigen account zijn **eigen strategie** test op **eigen data**.

| Pagina | Wat je er doet |
|---|---|
| **Inloggen** | Account maken, inloggen of eerst als gast proberen (voorbeelddata) |
| **Beheer** | Blijvende opslag koppelen en gebruikersoverzicht (alleen beheerders) |
| **Dashboard** | Grafiek (1m t/m 1W) met je trades, actuele stand van je strategie (Bias Engine of voorwaarden), performance |
| **Strategieën** | Strategie bouwen zonder code (sjablonen of leeg), bewerken, dupliceren, delen met de community, community-strategieën kopiëren |
| **Data** | Eigen bibliotheek · gedeelde bibliotheek · CSV's uploaden (elke markt) · crypto downloaden · demo |
| **Backtest** | Strategie + markten + periode + kosten per markt kiezen en draaien |
| **Resultaten** / **Trades** | KPI's, equity curve, per maand, uitsplitsingen, elke trade op de grafiek; laatste 30 runs bewaard |

**Strategie-typen**
- *Indicatoren & regels*: SMA, EMA, RSI, ATR, MACD, Bollinger, Stochastic, hoogste/laagste N candles, % verandering, vaste
  getallen; vergelijkingen (>, <, kruist boven/onder) op elke timeframe; SL (ATR / % / swing / vast), TP (RR / ATR / % / vast /
  geen), break-even, trailing stop, max. duur, exit bij tegengesteld signaal, handelsuren.
- *Smart Money (POI & liquiditeit)*: multi-timeframe bias, POI-zones en confirmatie op een lagere timeframe,
  volledig instelbaar (combinaties, POI-timeframes, confirmatie, RR, break-even).

**Accounts & privacy**: wachtwoorden als scrypt-hash; per gebruiker een eigen map `data/store/users/<naam>/`;
alleen strategie-*regels* worden gedeeld, nooit data of resultaten. Na 5 foute inlogpogingen 5 minuten blokkade.

**Online zetten (gratis, via Streamlit Community Cloud):**
1. https://share.streamlit.io → **Continue with GitHub** → **Create app**.
2. Repository `mw180708-create/ai_trading_tool`, branch `main`, main file `streamlit_app.py` → **Deploy**.

**Blijvende opslag (accounts, data, strategieën, resultaten)**
Streamlit Cloud wist de schijf bij elke herstart of update. wng bewaart daarom alles in een aparte **privé**
GitHub-repository (`wng-data`) en haalt het bij het opstarten terug. Instellen gaat via de pagina **Beheer**:
1. Klik *Token aanmaken op GitHub* (het vinkje `repo` staat al aan) en kopieer de code.
2. Plak de code en klik *Koppelen*: wng maakt de privé repository aan en slaat alles op wat er al is.
3. Zet in Streamlit → app → ⋮ → Settings → **Secrets**:
```toml
GITHUB_TOKEN = "ghp_..."
ADMIN_USERS = "jouw-gebruikersnaam"      # beheerders (komma-gescheiden)
# ALLOW_SIGNUP = "false"                 # nieuwe accounts uitzetten
# GITHUB_REPO = "eigenaar/naam"          # optioneel: andere (privé) opslag-repository
```
wng weigert gebruikersgegevens in een openbare repository op te slaan.

**Ingelogd blijven**: na het inloggen zet wng een ondertekende sessiecookie (30 dagen). Na een wachtwoordwijziging
of uitloggen is die ongeldig. Lokaal (`streamlit run app.py` of `START_WEBSITE.bat`) blijft alles bewaard in `.datastore/`.

**Grenzen van deze versie** (voor een groot publiek platform nodig): een echte database + bestandsopslag i.p.v. GitHub,
krachtigere hosting (Streamlit Community Cloud heeft ±1 GB geheugen), e-mailverificatie en "wachtwoord vergeten",
betaalde abonnementen, en een beveiligingsaudit.

## Installatie

```bash
pip install -r requirements.txt
```

| Library | Waarvoor | Verplicht |
|---|---|---|
| `pandas`, `numpy` | data, resampling, berekeningen | ja |
| `matplotlib` | equity curve (`equity_curve.png`) | aanbevolen |
| `ccxt` | BTC-historie downloaden (Binance/Bybit/Kraken) | optioneel |
| `yfinance` | goud-historie (GC=F) 1D/1H | optioneel |
| `MetaTrader5` | directe export uit MT5 (alleen Windows) | optioneel |
| `pytest` | tests | optioneel |

Ik gebruik geen Backtrader of VectorBT. Het "POI-in-POI"-model heeft per timeframe een eigen
toestand (POI's die geraakt zijn, wachten op een LTF-shift, BE-verplaatsing), en dat past niet goed
in hun standaardmodel. Een eigen event-driven engine (pandas/numpy) is hier transparanter en
controleerbaar zonder lookahead.

## Snel starten

```bash
python main.py --demo                 # test met synthetische data
python -m pytest -q tests             # tests (o.a. lookahead-controle)
```

### Met echte data

Zet CSV's in `data/` als `SYMBOOL_TF.csv`. Let op: `1M` = maand en `1m` = minuut.

```
data/BTCUSD_1m.csv    <- backtest-periode (executie)
data/BTCUSD_1D.csv    <- lange historie (warm-up voor 1M/1W/1D)
data/XAUUSD_1m.csv
data/XAUUSD_1D.csv
```

```bash
python main.py --data-dir data --start 2024-01-01
python main.py --asset XAUUSD:1m=exports/XAUUSD_M1.csv,1D=exports/XAUUSD_D1.csv --start 2024-06-01
```

Bronnen:
- **TradingView**: chart → *Export chart data…* (CSV met `time,open,high,low,close`).
- **MetaTrader 5**: History Center-export (`<DATE> <TIME> <OPEN>…`), of
  `python download_data.py mt5 --symbol XAUUSD --tf 1m --since 2024-01-01`.
- **Crypto**: `python download_data.py binance --tf 1m --since 2024-01-01` en `--tf 1d --since 2017-08-01`.
- **Goud zonder MT5**: `python download_data.py yahoo` (alleen 1D/1H, futures GC=F).

Alle timeframes (1M, 1W, 1D, 4H, 1H, 15m, 5m, 1m) worden uit de fijnste bron opgebouwd. Een
grovere bron met meer historie wordt ervoor geplakt als warm-up. Ontbreekt 1m-data, dan gebeurt
de confirmatie op de fijnste timeframe die er wel is (de tool meldt dat).

Belangrijke opties: `--min-rr 2`, `--no-adaptive-rr`, `--confirmation bos|first_candle`,
`--tp-source poi_tf|poi_tf_and_higher`, `--risk 0.01`, `--balance 100000`, `--no-costs`.
De overige parameters staan in `trading_tool/config.py`.

## Hoe het plan in regels is vertaald

Begrippen als "liquiditeit" en "balance level" zijn discretionair. Voor de backtest zijn ze zo
gedefinieerd (zie `trading_tool/market_structure.py`):

| Plan-begrip | Implementatie |
|---|---|
| Swing / liquiditeitspool | Fractal high/low (n bars links/rechts, per TF instelbaar). Pas bekend na n bars. |
| Liquiditeit Bullish | Laatste event = sell-side sweep (wick onder swing low, close erboven) of bullish BOS (draw naar volgende buy-side). |
| Liquiditeit Bearish | Laatste event = buy-side sweep of bearish BOS. |
| Liquiditeit 50/50 | Beide kanten gesweept binnen `liquidity_window` bars. |
| Balance level | Richting van de laatste balance shift: close boven de laatste swing high (bull) of onder de laatste swing low (bear). |
| Bias per TF | Liq = Bal → die richting; elke andere combinatie → 50/50 (geen trade). |
| Match | 1M+1W+1D, 1W+1D+4H, 1M+1D+1H (alle POI's) of 1D+4H+1H (alleen D/4H/1H POI's, Scalp). Andere combinaties → geen trade. |
| POI | Bij elke BOS: zone van de protected level (extreme wick = liquiditeit) tot de body van de laatste tegengestelde candle (protected zone). Alleen POI's in bias-richting. Vervalt bij een close voorbij het protected level. Elke POI wordt maar één keer getraded. |
| Confirmation | M→4H, W→1H, D→15m, 4H→5m, 1H→1m. Na een touch van de POI: BOS op de LTF (of eerste candle in bias-richting met `--confirmation first_candle`). |
| Entry | Close van de confirmatie-candle, plus spread. |
| SL | Dichtstbijzijnde nog niet geraakte 1H swing low/high (minimale 1H P), plus 0,05% buffer. |
| TP | Eerstvolgende nog niet geraakte liquiditeit op de POI-timeframe. |
| RR-filter | RR ≥ max(`min_rr`, break-even-RR × 1,25). Die laatste wordt na 20 trades dynamisch berekend uit de gerealiseerde win/loss-verhouding. |
| Management | Swing (M/W POI): BE bij 2R. Intraday/Scalp (D/4H/1H POI): BE bij 4R. Geen partials. |
| Risico | Exact 1% van de actuele equity, max. 1 open trade per account (= per symbool). |

Conservatieve aannames: raken SL en TP in dezelfde bar, dan telt de SL. BE wordt pas actief in
de bar na de trigger. Gaps worden gevuld op de open.

## Output

- Terminal: trades (Swing/Intraday/Scalp), winrate, gemiddelde RR, max drawdown, profit factor
  en net profit, per BTCUSD, per XAUUSD en totaal. Daarnaast uitsplitsingen per trade type, per
  POI-timeframe en per exit-reden.
- `results/summary.csv`, `results/trades_<SYMBOOL>.csv`, `results/equity_curve.png`.

## Projectstructuur

```
main.py                     CLI
download_data.py            data ophalen (ccxt / yfinance / MT5)
trading_tool/config.py      alle planregels en parameters
trading_tool/data_loader.py CSV-import (TV/MT4/MT5/ccxt), multi-timeframe opbouw
trading_tool/market_structure.py  swings, liquiditeit, balance levels, POI's
trading_tool/bias.py        timeframe-confluence
trading_tool/backtester.py  event-driven engine en trade management
trading_tool/metrics.py     rapportage
trading_tool/synthetic.py   synthetische testdata
trading_tool/live.py        Bias Engine: actuele stand van de regels
trading_tool/rules_engine.py regel-strategieën met indicatoren (zonder code)
trading_tool/strategies.py  strategie-schema, sjablonen, validatie, run
trading_tool/accounts.py    accounts (scrypt-hash, blokkade na foute pogingen)
trading_tool/storage.py     databibliotheek (lokaal + GitHub)
trading_tool/github_sync.py commits via de GitHub API
trading_tool/downloaders.py BTC-data downloaden (Binance / Bitstamp)
app.py / streamlit_app.py   website (Streamlit)
webapp/                     pagina's, thema en grafieken van de website
assets/                     TradingView Lightweight Charts (Apache 2.0)
tests/                      tests (lookahead, risico, CSV-formaten, opslag)
```

> Disclaimer: een backtest is geen garantie voor toekomstige resultaten. Demo-resultaten op
> synthetische data zeggen niets over de echte markt.
