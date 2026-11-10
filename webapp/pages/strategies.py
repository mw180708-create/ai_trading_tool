"""Strategieën: eigen strategieën beheren, bouwen zonder code en delen met de community."""
from __future__ import annotations

import copy

import pandas as pd
import streamlit as st

from trading_tool import strategies as strat
from trading_tool.config import TF_MINUTES, TIMEFRAMES
from trading_tool.rules_engine import INDICATORS, OPERATORS, STOP_TYPES, TARGET_TYPES

from .. import nav
from .. import state as S
from ..theme import badge, esc, html_block

TF_CHOICES = TIMEFRAMES                       # 1M ... 1m
IND_LABEL = {k: v[0] for k, v in INDICATORS.items()}
LABEL_IND = {v: k for k, v in IND_LABEL.items()}
OP_LABEL = OPERATORS
LABEL_OP = {v: k for k, v in OP_LABEL.items()}
SIG = "(signaal-TF)"


# --------------------------------------------------------------------------- #
# Hulpfuncties voor de voorwaarden-tabel
# --------------------------------------------------------------------------- #
def _params_to_text(ind: str, params: dict) -> str:
    spec = INDICATORS[ind][1]
    return ", ".join(f"{params.get(n, d):g}" for n, d, *_ in spec)


def _text_to_params(ind: str, text: str) -> dict:
    spec = INDICATORS[ind][1]
    vals = [v.strip() for v in str(text or "").replace(";", ",").split(",") if v.strip()]
    out = {}
    for (name, default, lo, hi), v in zip(spec, vals):
        try:
            x = float(v.replace(" ", ""))
        except ValueError:
            x = default
        out[name] = min(max(x, lo), hi)
    for name, default, *_ in spec[len(vals):]:
        out[name] = default
    return out


def conds_to_df(conds: list[dict]) -> pd.DataFrame:
    rows = []
    for c in conds:
        l, r = c.get("left", {}), c.get("right", {})
        rows.append({
            "Links": IND_LABEL.get(l.get("ind"), "Close (slotkoers)"),
            "Instelling L": _params_to_text(l.get("ind", "close"), l.get("params", {})),
            "TF L": l.get("tf") or SIG,
            "Vergelijking": OP_LABEL.get(c.get("op"), "groter dan"),
            "Rechts": IND_LABEL.get(r.get("ind"), "Vast getal"),
            "Instelling R": _params_to_text(r.get("ind", "value"), r.get("params", {})),
            "TF R": r.get("tf") or SIG,
        })
    return pd.DataFrame(rows, columns=["Links", "Instelling L", "TF L", "Vergelijking", "Rechts", "Instelling R", "TF R"])


def df_to_conds(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, row in df.iterrows():
        if not isinstance(row.get("Links"), str) or not isinstance(row.get("Rechts"), str):
            continue
        li, ri = LABEL_IND.get(row["Links"], "close"), LABEL_IND.get(row["Rechts"], "value")
        left = {"ind": li, "params": _text_to_params(li, row.get("Instelling L", ""))}
        right = {"ind": ri, "params": _text_to_params(ri, row.get("Instelling R", ""))}
        if isinstance(row.get("TF L"), str) and row["TF L"] != SIG:
            left["tf"] = row["TF L"]
        if isinstance(row.get("TF R"), str) and row["TF R"] != SIG:
            right["tf"] = row["TF R"]
        out.append({"left": left, "op": LABEL_OP.get(row.get("Vergelijking"), ">"), "right": right})
    return out


COND_COLS = {
    "Links": st.column_config.SelectboxColumn("Links", options=list(IND_LABEL.values()), required=True, width="medium"),
    "Instelling L": st.column_config.TextColumn("Instelling", help="Bv. 20 (lengte) of 12, 26, 9 (MACD)", width="small"),
    "TF L": st.column_config.SelectboxColumn("TF", options=[SIG, *TF_CHOICES], width="small"),
    "Vergelijking": st.column_config.SelectboxColumn("Vergelijking", options=list(OP_LABEL.values()), required=True),
    "Rechts": st.column_config.SelectboxColumn("Rechts", options=list(IND_LABEL.values()), required=True, width="medium"),
    "Instelling R": st.column_config.TextColumn("Instelling", width="small"),
    "TF R": st.column_config.SelectboxColumn("TF", options=[SIG, *TF_CHOICES], width="small"),
}


# --------------------------------------------------------------------------- #
# Editors
# --------------------------------------------------------------------------- #
def _rules_editor(d: dict, key: str) -> None:
    p = d["params"]
    c1, c2 = st.columns([1, 2])
    p["signal_tf"] = c1.selectbox("Signalen op timeframe", TF_CHOICES, index=TF_CHOICES.index(p["signal_tf"]),
                                  key=f"{key}_sig", help="Op de close van deze candle wordt gekeken of de voorwaarden kloppen.")
    dirs = {"long": "Alleen long", "short": "Alleen short", "both": "Long én short"}
    p["direction"] = c2.radio("Richting", list(dirs), format_func=dirs.get, horizontal=True,
                              index=list(dirs).index(p["direction"]), key=f"{key}_dir")
    with st.expander("Welke indicatoren en instellingen zijn er?"):
        st.dataframe(pd.DataFrame([{"Indicator": v[0], "Instelling (volgorde)": ", ".join(f"{n} ({dv:g})" for n, dv, *_ in v[1]) or "-"}
                                   for v in INDICATORS.values()]), hide_index=True, width="stretch")
        st.caption("Laat 'Instelling' leeg voor de standaardwaarde. 'TF' = op welke timeframe de indicator wordt berekend "
                   "(bv. EMA 200 op 1D als trendfilter). Hogere timeframes gebruiken alleen gesloten candles.")
    for side in ("long", "short"):
        if p["direction"] not in (side, "both"):
            continue
        st.markdown(f"**{'Long' if side == 'long' else 'Short'}-voorwaarden**")
        logic = st.radio("Logica", ["all", "any"], horizontal=True, key=f"{key}_{side}_logic",
                         index=0 if p[side].get("logic", "all") == "all" else 1,
                         format_func=lambda x: "Alle voorwaarden moeten kloppen (EN)" if x == "all"
                         else "Minstens één voorwaarde (OF)", label_visibility="collapsed")
        init = f"{key}_{side}_init"
        if init not in st.session_state:          # begintabel 1x vastzetten (anders verdubbelen bewerkingen)
            st.session_state[init] = conds_to_df(p[side].get("conditions", []))
        df = st.data_editor(st.session_state[init], num_rows="dynamic", hide_index=True,
                            width="stretch", column_config=COND_COLS, key=f"{key}_{side}_tbl")
        p[side] = {"logic": logic, "conditions": df_to_conds(df)}
    st.markdown("**Stop loss & take profit**")
    a, b, c_, e = st.columns(4)
    stp = p["stop"]
    stp["type"] = a.selectbox("Stop loss", list(STOP_TYPES), format_func=STOP_TYPES.get,
                              index=list(STOP_TYPES).index(stp.get("type", "atr")), key=f"{key}_st")
    stp["value"] = b.number_input("Waarde SL" + (" (candles)" if stp["type"] == "swing" else ""), 0.0, 1e9,
                                  float(stp.get("value", 2.0)), step=0.5, key=f"{key}_sv")
    tgt = p["target"]
    tgt["type"] = c_.selectbox("Take profit", list(TARGET_TYPES), format_func=TARGET_TYPES.get,
                               index=list(TARGET_TYPES).index(tgt.get("type", "rr")), key=f"{key}_tt")
    tgt["value"] = e.number_input("Waarde TP", 0.0, 1e9, float(tgt.get("value", 2.0)), step=0.5, key=f"{key}_tv",
                                  disabled=tgt["type"] == "none")
    if stp["type"] == "atr" or tgt["type"] == "atr":
        stp["length"] = tgt["length"] = int(st.number_input("ATR-lengte", 1, 500, int(stp.get("length", 14)), key=f"{key}_atrl"))
    with st.expander("Extra uitstapregels"):
        x1, x2, x3 = st.columns(3)
        p["breakeven_r"] = x1.number_input("Break-even bij (R, 0 = uit)", 0.0, 50.0, float(p.get("breakeven_r") or 0), 0.5, key=f"{key}_be")
        p["trailing_atr"] = x2.number_input("Trailing stop (× ATR, 0 = uit)", 0.0, 50.0, float(p.get("trailing_atr") or 0), 0.5, key=f"{key}_tr")
        p["max_bars"] = int(x3.number_input("Max. duur (candles, 0 = uit)", 0, 100000, int(p.get("max_bars") or 0), key=f"{key}_mb"))
        y1, y2, y3 = st.columns(3)
        p["exit_on_opposite"] = y1.toggle("Exit bij tegengesteld signaal", bool(p.get("exit_on_opposite")), key=f"{key}_eo")
        p["session"]["start"] = int(y2.number_input("Handelen vanaf (uur UTC)", 0, 23, int(p["session"].get("start", 0)), key=f"{key}_ss"))
        p["session"]["end"] = int(y3.number_input("Handelen tot (uur UTC)", 1, 24, int(p["session"].get("end", 24)), key=f"{key}_se"))


def _smc_editor(d: dict, key: str) -> None:
    p = d["params"]
    st.markdown("**Stap 1 · Bias: welke timeframe-combinaties moeten dezelfde kant op wijzen?**")
    rows = [{"TF 1": c[0], "TF 2": c[1] if len(c) > 1 else None, "TF 3": c[2] if len(c) > 2 else None,
             "Soort": "Scalp" if k == "scalp" else "Standaard"} for c, k in p["bias_combos"]]
    bias_tfs = [t for t in TF_CHOICES if TF_MINUTES[t] >= 15]
    init = f"{key}_combos_init"
    if init not in st.session_state:
        st.session_state[init] = pd.DataFrame(rows, columns=["TF 1", "TF 2", "TF 3", "Soort"])
    df = st.data_editor(st.session_state[init], num_rows="dynamic",
                        hide_index=True, width="stretch", key=f"{key}_combos", column_config={
                            "TF 1": st.column_config.SelectboxColumn(options=bias_tfs, required=True),
                            "TF 2": st.column_config.SelectboxColumn(options=bias_tfs),
                            "TF 3": st.column_config.SelectboxColumn(options=bias_tfs),
                            "Soort": st.column_config.SelectboxColumn(options=["Standaard", "Scalp"], required=True,
                                                                      help="Scalp = alleen trades vanuit de 'scalp POI-timeframes'")})
    combos = []
    for _, r in df.iterrows():
        tfs = [t for t in (r.get("TF 1"), r.get("TF 2"), r.get("TF 3")) if isinstance(t, str)]
        if tfs:
            combos.append([list(dict.fromkeys(tfs)), "scalp" if r.get("Soort") == "Scalp" else "standard"])
    p["bias_combos"] = combos
    st.markdown("**Stap 2-3 · POI's en confirmatie (POI in POI)**")
    poi_opts = [t for t in TF_CHOICES if TF_MINUTES[t] >= 60]
    p["poi_timeframes"] = st.multiselect("POI-timeframes", poi_opts, default=[t for t in p["poi_timeframes"] if t in poi_opts],
                                         key=f"{key}_pois")
    if p["poi_timeframes"]:
        cols = st.columns(len(p["poi_timeframes"]))
        conf = {}
        for col, t in zip(cols, p["poi_timeframes"]):
            lower = [x for x in TF_CHOICES if TF_MINUTES[x] < TF_MINUTES[t]]
            cur = p["confirmation_tf"].get(t, lower[0] if lower else t)
            conf[t] = col.selectbox(f"{t} POI → confirmatie op", lower, index=lower.index(cur) if cur in lower else 0,
                                    key=f"{key}_conf_{t}")
        p["confirmation_tf"] = conf
    c1, c2 = st.columns(2)
    p["swing_poi_timeframes"] = c1.multiselect("Swing-trades (BE-regel swing)", p["poi_timeframes"],
                                               default=[t for t in p["swing_poi_timeframes"] if t in p["poi_timeframes"]],
                                               key=f"{key}_swing")
    p["scalp_poi_timeframes"] = c2.multiselect("Scalp POI-timeframes", p["poi_timeframes"],
                                               default=[t for t in p["scalp_poi_timeframes"] if t in p["poi_timeframes"]],
                                               key=f"{key}_scalp")
    st.markdown("**Entry & management**")
    a, b, c, e = st.columns(4)
    p["min_rr"] = a.number_input("Min. Risk-to-Reward", 0.5, 20.0, float(p["min_rr"]), 0.5, key=f"{key}_rr")
    p["adaptive_rr"] = b.toggle("Dynamische RR-eis", bool(p["adaptive_rr"]), key=f"{key}_ad")
    p["be_trigger_rr_swing"] = c.number_input("BE swing (R)", 0.5, 50.0, float(p["be_trigger_rr_swing"]), 0.5, key=f"{key}_bes")
    p["be_trigger_rr_intraday"] = e.number_input("BE intraday/scalp (R)", 0.5, 50.0, float(p["be_trigger_rr_intraday"]), 0.5, key=f"{key}_bei")
    a, b, c = st.columns(3)
    p["confirmation_mode"] = a.selectbox("Confirmation", ["bos", "first_candle"], index=["bos", "first_candle"].index(p["confirmation_mode"]),
                                         format_func={"bos": "Balance shift / BOS", "first_candle": "Eerste candle in richting"}.get, key=f"{key}_cm")
    p["tp_source"] = b.selectbox("Take profit", ["poi_tf", "poi_tf_and_higher"], index=["poi_tf", "poi_tf_and_higher"].index(p["tp_source"]),
                                 format_func={"poi_tf": "Liquiditeit op POI-TF", "poi_tf_and_higher": "Dichtstbijzijnde (POI-TF of hoger)"}.get, key=f"{key}_tp")
    p["liquidity_mode"] = c.selectbox("Liquiditeit", ["draw", "sweep"], index=["draw", "sweep"].index(p["liquidity_mode"]),
                                      format_func={"draw": "Sweeps + BOS", "sweep": "Alleen sweeps"}.get, key=f"{key}_lm")
    sl_opts = [t for t in TF_CHOICES if TF_MINUTES[t] <= 240]
    p["sl_timeframe"] = st.selectbox("Stop loss op protected level van", sl_opts,
                                     index=sl_opts.index(p.get("sl_timeframe", "1H")) if p.get("sl_timeframe", "1H") in sl_opts else 0,
                                     key=f"{key}_sltf")


def _close_editor() -> None:
    d = st.session_state.pop("draft", None)
    if d:
        prefix = f"ed_{d['id']}"
        for k in [k for k in st.session_state.keys() if str(k).startswith(prefix)]:
            del st.session_state[k]


def editor() -> None:
    d = st.session_state["draft"]
    key = f"ed_{d['id']}"
    with st.container(key="panelglow_editor"):
        top = st.columns([3, 1])
        top[0].markdown(f"#### {esc(d['name']) or 'Strategie'}")
        if top[1].button("Sluiten zonder opslaan", width="stretch"):
            _close_editor()
            st.rerun()
        html_block(badge(strat.TYPES[d["type"]], "info"))
        c1, c2, c3 = st.columns([2, 1, 1])
        d["name"] = c1.text_input("Naam", d["name"], max_chars=60, key=f"{key}_name")
        d["risk_pct"] = c2.number_input("Risico per trade (%)", 0.01, 10.0, float(d.get("risk_pct", 1.0)), 0.1, key=f"{key}_risk")
        d["public"] = c3.toggle("Delen met community", bool(d.get("public")), key=f"{key}_pub",
                                help="Anderen kunnen je strategie dan zien en kopiëren (niet je data of resultaten).")
        d["description"] = st.text_area("Omschrijving (optioneel)", d.get("description", ""), max_chars=600,
                                        height=70, key=f"{key}_desc")
        if d["type"] == "rules":
            _rules_editor(d, key)
        else:
            _smc_editor(d, key)

        st.markdown("**Samenvatting**")
        html_block("<ul style='margin:0 0 6px 16px;padding:0;color:#b4b4bc'>" +
                   "".join(f"<li>{esc(x)}</li>" for x in strat.describe(d)) + "</ul>")
        errs = strat.validate(d)
        for e in errs:
            st.warning(e)
        b1, b2, _ = st.columns([1, 1, 2])
        if b1.button("Opslaan", type="primary", width="stretch", disabled=bool(errs)):
            rep = S.save_strategy(d)
            S.flash(f"Strategie '{d['name']}' opgeslagen." + (f" Let op: GitHub ({rep.error})." if rep.error else ""))
            _close_editor()
            st.rerun()
        if b2.button("Opslaan en backtesten", width="stretch", disabled=bool(errs)):
            S.save_strategy(d)
            st.session_state["bt_strategy"] = d["id"]
            _close_editor()
            nav.go("backtest")


# --------------------------------------------------------------------------- #
# Lijsten
# --------------------------------------------------------------------------- #
def _card(s: dict, mine: bool, i: int) -> None:
    with st.container(key=f"panel_strat_{'m' if mine else 'c'}{i}"):
        tags = badge(strat.TYPES[s["type"]], "info")
        if mine and s.get("public"):
            tags += " " + badge("Gedeeld", "ok")
        if not mine:
            tags += " " + badge(f"door {s.get('owner', '?')}", "info")
        html_block(f"<div style='font-weight:600;font-size:1rem'>{esc(s['name'])}</div>"
                   f"<div style='margin:8px 0'>{tags}</div>"
                   + (f"<div class='small-note' style='margin-bottom:8px'>{esc(s['description'])}</div>" if s.get("description") else "")
                   + "<ul style='margin:0 0 4px 16px;padding:0;color:#b4b4bc;font-size:.84rem'>"
                   + "".join(f"<li>{esc(x)}</li>" for x in strat.describe(s)[1:]) + "</ul>")
        st.caption(f"Bijgewerkt {s.get('updated', '-')}")
        if mine:
            b = st.columns([1, 1, 0.8])
            if b[0].button("Testen", key=f"bt_{s['id']}", width="stretch", type="primary"):
                st.session_state["bt_strategy"] = s["id"]
                nav.go("backtest")
            if b[1].button("Bewerken", key=f"editbtn_{s['id']}", width="stretch"):
                st.session_state["draft"] = copy.deepcopy(s)
                st.rerun()
            with b[2].popover("Meer", width="stretch"):
                if st.button("Dupliceren", key=f"dup_{s['id']}", width="stretch"):
                    dup = dict(copy.deepcopy(s), id=strat.new_id(), name=f"{s['name']} (kopie)", public=False,
                               created=strat.now_iso())
                    S.save_strategy(dup)
                    S.flash(f"Kopie gemaakt: {dup['name']}")
                    st.rerun()
                if st.button("Verwijderen", key=f"del_{s['id']}", width="stretch"):
                    st.session_state["confirm_del"] = s["id"]
                    st.rerun()
            if st.session_state.get("confirm_del") == s["id"]:
                st.warning(f"'{s['name']}' echt verwijderen?")
                y, n = st.columns(2)
                if y.button("Ja, verwijderen", key=f"dely_{s['id']}", width="stretch"):
                    S.delete_strategy(s["id"])
                    st.session_state.pop("confirm_del", None)
                    S.flash("Strategie verwijderd.", "warning")
                    st.rerun()
                if n.button("Annuleren", key=f"deln_{s['id']}", width="stretch"):
                    st.session_state.pop("confirm_del", None)
                    st.rerun()
        else:
            if st.button("Kopiëren naar mijn strategieën", key=f"cp_{s['owner']}_{s['id']}", width="stretch"):
                cp = dict(copy.deepcopy(s), id=strat.new_id(), public=False, created=strat.now_iso(),
                          copied_from=f"{s.get('owner')}/{s['id']}", name=f"{s['name']} (van {s.get('owner')})")
                S.save_strategy(cp)
                S.flash(f"'{s['name']}' staat nu bij je eigen strategieën.")
                st.rerun()


def _grid(items: list[dict], mine: bool) -> None:
    cols = st.columns(3)
    for i, s in enumerate(items):
        with cols[i % 3]:
            _card(s, mine, i)


def _new() -> None:
    keys = list(strat.TEMPLATES)
    cols = st.columns(3)
    for i, k in enumerate(keys):
        t = strat.TEMPLATES[k]
        with cols[i % 3], st.container(key=f"panel_tpl{i}"):
            html_block(f"<div style='font-weight:600'>{esc(t['name'])}</div>"
                       f"<div style='margin:8px 0'>{badge(strat.TYPES[t['type']], 'info')}</div>"
                       f"<div class='small-note' style='min-height:5.6em'>{esc(t['description'] or 'Begin met één voorwaarde en bouw verder.')}</div>")
            if st.button("Gebruiken", key=f"tpl_{k}", width="stretch"):
                st.session_state["draft"] = strat.normalize(strat.from_template(k, S.display_name()))
                st.rerun()


def render() -> None:
    S.show_flash()
    if "draft" in st.session_state:
        editor()
        return
    own = S.list_strategies()
    labels = ["Mijn strategieën", "Sjablonen", "Community"]
    tabs = st.tabs(labels, key="strat_tabs", on_change="rerun", default=labels[0] if own else labels[1])
    if tabs[0].open:
        with tabs[0]:
            if not own:
                st.caption("Je hebt nog geen strategieën. Begin met een sjabloon.")
            _grid(own, mine=True)
    if tabs[1].open:
        with tabs[1]:
            _new()
    if tabs[2].open:
        with tabs[2]:
            pub = [s for s in S.public_strategies() if s.get("owner") != S.user()]
            if not pub:
                st.caption("Nog geen gedeelde strategieën van anderen. Je deelt een strategie via Bewerken → "
                           "Delen met community. Alleen de regels worden gedeeld, nooit data of resultaten.")
            _grid(pub, mine=False)
