"""Gedeelde status: databibliotheek, GitHub-koppeling, cached data en backtest-resultaten."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import streamlit as st

import secrets as pysecrets

from trading_tool import strategies as strat
from trading_tool.accounts import Accounts
from trading_tool.backtester import BacktestResult
from trading_tool.config import TF_MINUTES
from trading_tool.data_loader import MultiTimeframeData, build_multi_timeframe
from trading_tool.github_sync import GitHubSync
from trading_tool.live import LiveState, analyze_live
from trading_tool.rules_engine import live_status
from trading_tool.storage import DataStore, make_github_sync
from trading_tool.synthetic import demo_dataset

ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / ".wng_cache"        # lokale kopie van de (privé) opslag-repository
LOCAL_ROOT = ROOT / ".datastore"        # nieuwe/gewijzigde bestanden op deze server
DATA_REPO_NAME = "wng-data"             # standaardnaam van de privé opslag-repository
DEFAULT_REPO = ""                       # leeg = <eigenaar van het token>/wng-data
SYMBOLS = ["BTCUSD", "EURUSD"]          # alleen voor de demo


# --------------------------------------------------------------------------- #
# Config / opslag
# --------------------------------------------------------------------------- #
def _read_secrets() -> tuple[dict, str | None]:
    """Alle Streamlit-secrets als dict + eventuele fout (bv. ongeldige TOML)."""
    try:
        return {k: st.secrets[k] for k in st.secrets.keys()}, None
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "pars" in msg.lower() or "expected" in msg.lower() or "invalid" in msg.lower():
            return {}, msg.split(":", 1)[-1].strip() if "secrets.toml" in msg else msg
        return {}, None   # geen secrets ingesteld


def secret(key: str, default: str | None = None) -> str | None:
    sec, _ = _read_secrets()
    if key in sec:
        return str(sec[key])
    return os.environ.get(key, default)


def clean_token(tok) -> str | None:
    if tok is None:
        return None
    t = str(tok).strip().strip('"').strip("'").strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    t = t.replace(" ", "").replace("\n", "")
    return t or None


def clean_repo(repo: str | None) -> str:
    r = (repo or "").strip().strip('"').strip("'")
    for pre in ("https://github.com/", "http://github.com/", "github.com/"):
        if r.lower().startswith(pre):
            r = r[len(pre):]
    r = r.removesuffix(".git").strip("/")
    return r


def _token_from_secrets(sec: dict) -> str | None:
    """Accepteer verschillende schrijfwijzen: GITHUB_TOKEN, github_token, token, [github] token = ..."""
    for k in ("GITHUB_TOKEN", "github_token", "Github_Token", "GH_TOKEN", "TOKEN", "token"):
        if k in sec and isinstance(sec[k], str):
            return clean_token(sec[k])
    for sect in ("github", "GITHUB", "GitHub"):
        if sect in sec and hasattr(sec[sect], "get"):
            v = sec[sect].get("token") or sec[sect].get("GITHUB_TOKEN")
            if v:
                return clean_token(v)
    return None


@st.cache_resource(show_spinner=False)
def runtime_cfg() -> dict:
    """Token dat op de website is geplakt (geldig tot de website herstart)."""
    return {}


def _cfg() -> tuple[str | None, str, str, str]:
    sec, _ = _read_secrets()
    tok = _token_from_secrets(sec)
    source = "secrets"
    if not tok and runtime_cfg().get("token"):
        tok, source = runtime_cfg()["token"], "website"
    if not tok and os.environ.get("AI_TRADING_GITHUB_TOKEN"):
        tok, source = clean_token(os.environ["AI_TRADING_GITHUB_TOKEN"]), "omgeving"
    repo = sec.get("GITHUB_REPO") or sec.get("github_repo") or runtime_cfg().get("repo") or DEFAULT_REPO
    if "github" in sec and hasattr(sec["github"], "get") and sec["github"].get("repo"):
        repo = sec["github"]["repo"]
    return tok, clean_repo(str(repo)), str(sec.get("GITHUB_BRANCH", "main")), source


def _connect(token: str, repo: str, branch: str = "main") -> tuple[GitHubSync | None, dict]:
    """Token controleren, opslag-repository bepalen/aanmaken (privé) en schrijfrecht testen."""
    gh = make_github_sync(token, repo or "x/x", branch)
    status = {"configured": True, "ok": False, "msg": "", "repo": repo}
    login = gh.user_login()
    if login is None:
        status["msg"] = ("GitHub accepteert het token niet: het is ongeldig, verlopen of niet volledig gekopieerd. "
                         "Maak eventueel een nieuw token.")
        return None, status
    gh.repo = repo or f"{login}/{DATA_REPO_NAME}"
    status["repo"] = gh.repo
    ok, msg = gh.ensure_repo()
    if not ok:
        status["msg"] = msg
        return None, status
    ok, msg = gh.check()
    if ok:
        info = gh._get(f"/repos/{gh.repo}").json()
        if not info.get("private", False):
            ok, msg = False, (f"De repository '{gh.repo}' is openbaar. Accounts en data van gebruikers horen niet in een "
                              f"openbare repository. Laat GITHUB_REPO leeg (dan maakt wng de privé repository "
                              f"'{DATA_REPO_NAME}' aan) of zet deze repository op privé.")
    status.update(ok=ok, msg=msg)
    return (gh if ok else None), status


@st.cache_resource(show_spinner="Opslag laden…", ttl=6 * 3600)
def _github(token: str | None, repo: str, branch: str, source: str) -> tuple[GitHubSync | None, dict]:
    """GitHub-koppeling + status. Bij een geldige koppeling worden alle gegevens teruggehaald (na een herstart)."""
    if not token:
        return None, {"configured": False, "ok": False, "msg": "Geen token ingesteld.", "source": source, "repo": repo}
    try:
        gh, status = _connect(token, repo, branch)
    except Exception as e:  # noqa: BLE001 - netwerkfout e.d.
        return None, {"configured": True, "ok": False, "msg": f"GitHub niet bereikbaar ({e}).", "source": source,
                      "repo": repo}
    status["source"] = source
    if gh is not None:
        try:
            status["restored"] = gh.restore("data/store", CACHE_ROOT)
        except Exception as e:  # noqa: BLE001
            status.update(ok=False, msg=f"Gegevens terughalen mislukt: {e}")
            return None, status
    return gh, status


def github() -> GitHubSync | None:
    return _github(*_cfg())[0]


def github_status() -> dict:
    st_ = dict(_github(*_cfg())[1])
    st_["secrets_error"] = _read_secrets()[1]
    return st_


def test_token(token: str, repo: str | None = None) -> tuple[bool, str, str]:
    """(ok, melding, repository) - maakt de privé repository aan als die nog niet bestaat."""
    tok = clean_token(token)
    if not tok:
        return False, "Plak eerst een token.", ""
    try:
        gh, status = _connect(tok, clean_repo(repo))
    except Exception as e:  # noqa: BLE001
        return False, f"GitHub niet bereikbaar ({e}).", ""
    return status["ok"], status["msg"], status["repo"]


def use_token_now(token: str, repo: str | None = None) -> None:
    runtime_cfg()["token"] = clean_token(token)
    runtime_cfg()["repo"] = clean_repo(repo)
    reset_github()


def reset_github() -> None:
    _github.clear()
    _accounts.clear()


# --------------------------------------------------------------------------- #
# Gebruikers
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def _accounts(cfg_key: tuple) -> Accounts:
    return Accounts(CACHE_ROOT, github=_github(*cfg_key)[0], local_root=LOCAL_ROOT)   # onthoudt foute pogingen


def accounts() -> Accounts:
    return _accounts(_cfg())


def user() -> str | None:
    return st.session_state.get("user")


def is_guest() -> bool:
    return bool(st.session_state.get("guest"))


def logged_in() -> bool:
    return user() is not None or is_guest()


def display_name() -> str:
    return "Gast" if is_guest() else (user() or "")


def login_as(username: str) -> None:
    _reset_session()
    st.session_state["user"] = username


def login_guest() -> None:
    _reset_session()
    st.session_state["guest"] = pysecrets.token_hex(6)
    st.session_state["demo"] = True


def logout() -> None:
    _reset_session()
    from .session_cookie import forget
    forget()


def _reset_session() -> None:
    for k in list(st.session_state.keys()):
        if k != "_flash":
            del st.session_state[k]


def admins() -> set[str]:
    raw = secret("ADMIN_USERS", "") or ""
    return {a.strip().lower() for a in raw.replace(";", ",").split(",") if a.strip()}


def is_admin() -> bool:
    return user() is not None and user() in admins()


def can_manage() -> bool:
    """Beheer-pagina: beheerders, of (zolang er geen beheerder is ingesteld) elke ingelogde gebruiker."""
    return user() is not None and (is_admin() or not admins())


def persistent() -> bool:
    return github() is not None


def _all_stores() -> list[DataStore]:
    gh = github()
    stores = [DataStore(CACHE_ROOT, local_root=LOCAL_ROOT, github=gh)]
    users_dir = LOCAL_ROOT / "users"
    if users_dir.is_dir():
        stores += [DataStore(CACHE_ROOT, local_root=LOCAL_ROOT, github=gh, namespace=f"users/{d.name}")
                   for d in sorted(users_dir.iterdir()) if d.is_dir()]
    return stores


def unsynced_count() -> int:
    return sum(len(s_.unsynced_files()) for s_ in _all_stores())


def push_all_unsynced() -> tuple[int, str | None]:
    """Sla alles wat alleen op deze server staat (accounts, data, strategieën) op in de opslag-repository."""
    total, errors = 0, []
    for s_ in _all_stores():
        if s_.github is None:
            return 0, "geen koppeling"
        if s_.unsynced_files():
            rep = s_.push_unsynced()
            total += rep.total
            if rep.error:
                errors.append(rep.error)
    return total, ("; ".join(errors) if errors else None)


def signup_open() -> bool:
    return str(secret("ALLOW_SIGNUP", "true")).strip().lower() not in ("0", "false", "nee", "no")


def namespace() -> str:
    if is_guest():
        return f"guests/{st.session_state['guest']}"
    return f"users/{user()}"


def store() -> DataStore:
    """De eigen (afgeschermde) opslag van de ingelogde gebruiker."""
    if is_guest():
        return DataStore(CACHE_ROOT, local_root=LOCAL_ROOT, namespace=namespace())   # gasten: nooit naar GitHub
    return DataStore(CACHE_ROOT, local_root=LOCAL_ROOT, github=github(), namespace=namespace())


def shared_store() -> DataStore:
    """Gedeelde bibliotheek (alleen beheerders mogen erin schrijven)."""
    return DataStore(CACHE_ROOT, local_root=LOCAL_ROOT, github=github())


# --------------------------------------------------------------------------- #
# Marktdata (eigen + gedeeld)
# --------------------------------------------------------------------------- #
def demo_on() -> bool:
    return bool(st.session_state.get("demo", False))


def fingerprint() -> str:
    if demo_on():
        return "demo"
    return f"{namespace()}|{store().fingerprint()}|{shared_store().fingerprint()}"


def symbols() -> list[str]:
    if demo_on():
        return SYMBOLS
    found = set(store().symbols()) | set(shared_store().symbols())
    return sorted(found)


def data_origin(symbol: str) -> dict[str, str]:
    """{tf: 'eigen' | 'gedeeld'} - welke bron gebruikt wordt per timeframe."""
    own, shared = set(store().timeframes(symbol)), set(shared_store().timeframes(symbol))
    return {tf: ("eigen" if tf in own else "gedeeld") for tf in sorted(own | shared, key=lambda t: -TF_MINUTES[t])}


@st.cache_resource(show_spinner=False, max_entries=8)
def _mtf(ns: str, symbol: str, fp: str) -> MultiTimeframeData | None:
    if fp == "demo":
        return demo_dataset(symbol, seed=SYMBOLS.index(symbol) if symbol in SYMBOLS else 0)
    src = shared_store().load_symbol(symbol)
    src.update(DataStore(CACHE_ROOT, local_root=LOCAL_ROOT, namespace=ns).load_symbol(symbol))   # eigen data voor
    return build_multi_timeframe(symbol, src) if src else None


def mtf(symbol: str) -> MultiTimeframeData | None:
    return _mtf(namespace(), symbol, fingerprint())


# --------------------------------------------------------------------------- #
# Strategieën
# --------------------------------------------------------------------------- #
def list_strategies() -> list[dict]:
    st_ = store()
    out = []
    for name in st_.list_files("strategies"):
        s = st_.get_json(f"strategies/{name}")
        if isinstance(s, dict) and s.get("id"):
            out.append(strat.normalize(s))
    return sorted(out, key=lambda s: s.get("updated", ""), reverse=True)


def get_strategy(sid: str) -> dict | None:
    s = store().get_json(f"strategies/{sid}.json")
    return strat.normalize(s) if isinstance(s, dict) else None


def save_strategy(s: dict):
    s = dict(s, updated=strat.now_iso(), owner=display_name())
    rep = store().put_json(f"strategies/{s['id']}.json", s, f"Strategie opgeslagen: {s['name']}")
    _public.clear()
    return rep


def delete_strategy(sid: str):
    rep = store().delete_files([f"strategies/{sid}.json"], "Strategie verwijderd")
    _public.clear()
    return rep


@st.cache_data(show_spinner=False, ttl=120)
def _public(_marker: int = 0) -> list[dict]:
    acc = accounts()
    out = []
    for u in acc.list_users():
        stx = acc.store_for(u)
        for name in stx.list_files("strategies"):
            s = stx.get_json(f"strategies/{name}")
            if isinstance(s, dict) and s.get("public"):
                s = strat.normalize(s)
                s["owner"] = u
                out.append(s)
    return sorted(out, key=lambda s: s.get("updated", ""), reverse=True)


def public_strategies() -> list[dict]:
    return _public()


# --------------------------------------------------------------------------- #
# Live status (dashboard)
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False, max_entries=12)
def _live_smc(ns: str, symbol: str, fp: str, key: str, params_json: str) -> LiveState | None:
    import json
    m = _mtf(ns, symbol, fp)
    if m is None:
        return None
    try:
        return analyze_live(m, strat.smc_config(json.loads(params_json)))
    except Exception:  # noqa: BLE001
        return None


@st.cache_resource(show_spinner=False, max_entries=12)
def _live_rules(ns: str, symbol: str, fp: str, key: str, params_json: str) -> dict | None:
    import json
    m = _mtf(ns, symbol, fp)
    if m is None:
        return None
    try:
        return live_status(m, json.loads(params_json))
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def live(symbol: str, strategy: dict):
    import json
    pj = json.dumps(strategy["params"], sort_keys=True, default=str)
    key = f"{strategy.get('id')}|{strategy.get('updated')}"
    if strategy["type"] == "smc":
        return _live_smc(namespace(), symbol, fingerprint(), key, pj)
    return _live_rules(namespace(), symbol, fingerprint(), key, pj)


# --------------------------------------------------------------------------- #
# Resultaten (meerdere runs per gebruiker)
# --------------------------------------------------------------------------- #
@dataclass
class Results:
    trades: pd.DataFrame
    equity: dict[str, pd.Series]
    initial: dict[str, float]
    stats: dict[str, dict]
    meta: dict = field(default_factory=dict)

    @property
    def symbols(self) -> list[str]:
        return list(self.equity)

    @property
    def is_smc(self) -> bool:
        return self.meta.get("strategy_type", "smc") == "smc"

    def views(self) -> list[str]:
        return self.symbols + (["TOTAAL"] if len(self.symbols) > 1 else [])

    def trades_for(self, view: str) -> pd.DataFrame:
        if self.trades.empty:
            return self.trades
        t = self.trades if view == "TOTAAL" else self.trades[self.trades["symbol"] == view]
        return t.sort_values("exit_time").reset_index(drop=True)

    def initial_for(self, view: str) -> float:
        return sum(self.initial.values()) if view == "TOTAAL" else self.initial[view]

    def equity_for(self, view: str) -> pd.Series:
        if view != "TOTAAL":
            return self.equity[view]
        curves = [s[~s.index.duplicated(keep="last")] for s in self.equity.values()]
        idx = curves[0].index
        for c in curves[1:]:
            idx = idx.union(c.index)
        return sum(c.reindex(idx).ffill().fillna(c.iloc[0]) for c in curves)


def results_from_backtests(res: list[BacktestResult], meta: dict) -> Results:
    trades = pd.concat([r.trades for r in res if not r.trades.empty], ignore_index=True) \
        if any(not r.trades.empty for r in res) else pd.DataFrame()
    return Results(trades, {r.symbol: r.equity for r in res}, {r.symbol: r.initial_balance for r in res},
                   {r.symbol: r.stats for r in res}, meta)


def save_run(r: Results):
    eq = pd.concat([pd.DataFrame({"symbol": s, "time": e.index, "equity": e.values}) for s, e in r.equity.items()],
                   ignore_index=True)
    meta = dict(r.meta, initial=r.initial, stats=r.stats)
    run_id = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d-%H%M%S") + "-" + pysecrets.token_hex(2)
    r.meta["run_id"] = run_id
    rep = store().save_run(run_id, r.trades, eq, meta)
    st.session_state["run_id"] = run_id
    st.session_state["results"] = r
    return rep


def list_runs() -> list[tuple[str, dict]]:
    st_ = store()
    return [(rid, st_.run_meta(rid) or {}) for rid in st_.list_runs()]


def _load_run(run_id: str) -> Results | None:
    loaded = store().load_run(run_id)
    if not loaded:
        return None
    trades, eq, meta = loaded
    equity = {s: pd.Series(g["equity"].to_numpy(), index=pd.DatetimeIndex(g["time"]), name=s)
              for s, g in eq.groupby("symbol", sort=False)}
    if not equity:
        return None
    meta["run_id"] = run_id
    return Results(trades, equity, {k: float(v) for k, v in meta.get("initial", {}).items()},
                   meta.get("stats", {}), meta)


def select_run(run_id: str) -> None:
    st.session_state["run_id"] = run_id
    st.session_state.pop("results", None)


def get_results() -> Results | None:
    if st.session_state.get("results") is not None:
        return st.session_state["results"]
    rid = st.session_state.get("run_id")
    runs = store().list_runs()
    if not runs:
        return None
    if rid not in runs:
        rid = runs[0]
    res = _load_run(rid)
    st.session_state["run_id"] = rid
    st.session_state["results"] = res
    return res


def delete_run(run_id: str):
    rep = store().delete_run(run_id)
    if st.session_state.get("run_id") == run_id:
        st.session_state.pop("run_id", None)
        st.session_state.pop("results", None)
    return rep


# --------------------------------------------------------------------------- #
# Kleine helpers
# --------------------------------------------------------------------------- #
def flash(msg: str, kind: str = "success") -> None:
    st.session_state.setdefault("_flash", []).append((kind, msg))


def show_flash() -> None:
    for kind, msg in st.session_state.pop("_flash", []):
        getattr(st, kind)(msg)


def daily_change(m: MultiTimeframeData) -> tuple[float, float, pd.Series]:
    """(laatste prijs, verandering % t.o.v. vorige dag-close, closes laatste 60 dagen)."""
    d = m["1D"] if "1D" in m else m[m.base_tf]
    last = float(m[m.base_tf]["close"].iloc[-1])
    prev = float(d["close"].iloc[-2]) if len(d) > 1 else last
    return last, (last / prev - 1) * 100 if prev else 0.0, d["close"].iloc[-60:]


def fmt_bias(v) -> tuple[str, str]:
    if v is None:
        return "–", "na"
    return {1: ("Bullish", "bull"), -1: ("Bearish", "bear"), 0: ("50/50", "")}[int(v)]


def strategy_choices() -> list[dict]:
    """Eigen strategieën; heeft iemand er nog geen, dan de sjablonen als startpunt."""
    own = list_strategies()
    if own:
        return own
    return [strat.normalize(dict(strat.from_template(k, display_name()), id=f"tpl-{k}"))
            for k in strat.TEMPLATES if k != "blank"]
