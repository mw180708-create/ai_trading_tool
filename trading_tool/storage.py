"""Databibliotheek: geüploade/gedownloade koersdata en backtest-resultaten blijvend bewaren.

Opslag-indeling (per jaar, zodat bestanden klein blijven en alleen gewijzigde jaren
opnieuw worden opgeslagen):

    data/store/BTCUSD/M1/2024.parquet                      <- gedeelde bibliotheek (root)
    data/store/users/<gebruiker>/XAUUSD/D1/2019.parquet    <- eigen data van een gebruiker
    data/store/users/<gebruiker>/strategies/<id>.json      <- eigen strategieën
    data/store/users/<gebruiker>/results/<run>/...         <- backtest-runs

* Lokaal wordt altijd geschreven naar `.datastore/` (staat in .gitignore).
* Met een GitHub-token wordt dezelfde inhoud ook in de repository (`data/store/`) gecommit,
  zodat de data een herstart van de website (Streamlit Cloud) overleeft.
* Bij het lezen wordt per bestand de nieuwste versie (lokaal of repository) gebruikt.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import TF_MINUTES, TIMEFRAMES
from .github_sync import GitHubError, GitHubSync

TF_CODE = {"1M": "MN1", "1W": "W1", "1D": "D1", "4H": "H4", "1H": "H1", "15m": "M15", "5m": "M5", "1m": "M1"}
CODE_TF = {v: k for k, v in TF_CODE.items()}
STORE_REL = "data/store"
RESULTS_DIR = "results"
RESERVED = {"users", "guests", "_results", "results", "strategies", "account"}
BOOKKEEPING = {"deleted.json", "synced.json"}
OHLCV = ["open", "high", "low", "close", "volume"]


def _df_to_parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, compression="zstd")
    return buf.getvalue()


@dataclass
class SaveReport:
    added: int = 0
    total: int = 0
    years: list[int] = field(default_factory=list)
    synced: bool = False
    error: str | None = None


class DataStore:
    def __init__(self, repo_root: str | Path, local_root: str | Path | None = None,
                 github: GitHubSync | None = None, namespace: str | None = None):
        self.repo_root = Path(repo_root)
        self.namespace = namespace.strip("/") if namespace else None
        self.rel_root = STORE_REL + (f"/{self.namespace}" if self.namespace else "")
        self.repo_dir = self.repo_root / self.rel_root
        base_local = Path(local_root) if local_root else self.repo_root / ".datastore"
        self.local_dir = base_local / self.namespace if self.namespace else base_local
        self.github = github
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self._tomb_path = self.local_dir / "deleted.json"
        self._sync_path = self.local_dir / "synced.json"

    # ------------------------------------------------------------------ #
    # interne helpers
    # ------------------------------------------------------------------ #
    @property
    def synced(self) -> bool:
        return self.github is not None

    def _tombstones(self) -> dict[str, float]:
        try:
            return json.loads(self._tomb_path.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _set_tombstones(self, t: dict[str, float]) -> None:
        self._tomb_path.write_text(json.dumps(t))

    def _synced_map(self) -> dict[str, int]:
        try:
            return json.loads(self._sync_path.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _mark_synced(self, rels: list[str]) -> None:
        m = self._synced_map()
        for rel in rels:
            p = self.local_dir / rel
            if p.exists():
                m[rel] = p.stat().st_mtime_ns
        self._sync_path.write_text(json.dumps(m))

    def _is_on_github(self, rel: str) -> bool:
        """rel = pad binnen de store, bv. 'BTCUSD/M1/2024.parquet'."""
        local = self.local_dir / rel
        if not local.exists():
            return (self.repo_dir / rel).exists()
        repo = self.repo_dir / rel
        if repo.exists() and repo.stat().st_mtime >= local.stat().st_mtime:
            return True
        return self._synced_map().get(rel) == local.stat().st_mtime_ns

    def unsynced_files(self) -> list[str]:
        """Lokale bestanden (data, strategieën, resultaten) die nog niet op GitHub staan."""
        out = []
        for p in sorted(self.local_dir.rglob("*")):
            if not p.is_file() or p.name in BOOKKEEPING:
                continue
            rel = p.relative_to(self.local_dir).as_posix()
            if self.namespace is None and rel.split("/", 1)[0] in ("users", "guests"):
                continue   # andere namespaces hebben hun eigen administratie
            if rel.split("/", 1)[0] == "guests":
                continue
            if not self._is_on_github(rel):
                out.append(rel)
        return out

    def push_unsynced(self, max_batch_mb: float = 40.0) -> SaveReport:
        """Stuur alle nog niet gesynchroniseerde bestanden naar GitHub (in een paar commits)."""
        rep = SaveReport()
        if not self.github:
            rep.error = "GitHub is niet gekoppeld."
            return rep
        files = self.unsynced_files()
        batch: dict[str, bytes] = {}
        size = 0.0

        def flush():
            nonlocal batch, size
            if batch:
                self.github.commit_files({f"{self.rel_root}/{k}": v for k, v in batch.items()},
                                         f"Data: {len(batch)} bestand(en) naar GitHub gezet")
                self._mark_synced(list(batch))
                rep.total += len(batch)
            batch, size = {}, 0.0
        try:
            for rel in files:
                data = (self.local_dir / rel).read_bytes()
                if size + len(data) / 1e6 > max_batch_mb:
                    flush()
                batch[rel] = data
                size += len(data) / 1e6
            flush()
            rep.synced = True
        except Exception as e:  # noqa: BLE001
            rep.error = str(e)
        return rep

    def _resolve(self, rel_dir: str) -> dict[str, Path]:
        """{bestandsnaam: pad} met de nieuwste versie per bestand (lokaal of repo)."""
        tomb = self._tombstones()
        out: dict[str, Path] = {}
        for base in (self.repo_dir, self.local_dir):
            d = base / rel_dir
            if not d.is_dir():
                continue
            for p in d.iterdir():
                if not p.is_file() or p.name.startswith("."):
                    continue
                rel = f"{rel_dir}/{p.name}"
                if rel in tomb and p.stat().st_mtime <= tomb[rel]:
                    continue
                if p.name not in out or p.stat().st_mtime > out[p.name].stat().st_mtime:
                    out[p.name] = p
        return out

    def _symbols_tfs(self) -> list[tuple[str, str]]:
        found = set()
        for base in (self.repo_dir, self.local_dir):
            if not base.is_dir():
                continue
            for sd in base.iterdir():
                if not sd.is_dir() or sd.name.startswith(("_", ".")) or sd.name in RESERVED:
                    continue
                for td in sd.iterdir():
                    if td.is_dir() and td.name in CODE_TF:
                        found.add((sd.name, CODE_TF[td.name]))
        return sorted(found, key=lambda x: (x[0], -TF_MINUTES[x[1]]))

    # ------------------------------------------------------------------ #
    # publieke API - koersdata
    # ------------------------------------------------------------------ #
    def fingerprint(self) -> str:
        h = hashlib.sha1()
        for sym, tf in self._symbols_tfs():
            for name, p in sorted(self._resolve(f"{sym}/{TF_CODE[tf]}").items()):
                st = p.stat()
                h.update(f"{sym}/{tf}/{name}:{st.st_mtime_ns}:{st.st_size};".encode())
        return h.hexdigest()

    def symbols(self) -> list[str]:
        return sorted({s for s, _ in self._symbols_tfs()})

    def timeframes(self, symbol: str) -> list[str]:
        return [tf for s, tf in self._symbols_tfs() if s == symbol and self._resolve(f"{s}/{TF_CODE[tf]}")]

    def load(self, symbol: str, tf: str) -> pd.DataFrame | None:
        files = self._resolve(f"{symbol}/{TF_CODE[tf]}")
        if not files:
            return None
        parts = [pd.read_parquet(p) for _, p in sorted(files.items())]
        df = pd.concat(parts).sort_index()
        df = df[~df.index.duplicated(keep="last")]
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df[OHLCV]

    def load_symbol(self, symbol: str) -> dict[str, pd.DataFrame]:
        out = {}
        for tf in self.timeframes(symbol):
            df = self.load(symbol, tf)
            if df is not None and len(df):
                out[tf] = df
        return out

    def datasets(self) -> pd.DataFrame:
        rows = []
        for sym, tf in self._symbols_tfs():
            files = self._resolve(f"{sym}/{TF_CODE[tf]}")
            if not files:
                continue
            df = self.load(sym, tf)
            on_gh = all(self._is_on_github(f"{sym}/{TF_CODE[tf]}/{n}") for n in files)
            rows.append({
                "Asset": sym, "Timeframe": tf, "Bars": len(df),
                "Van": df.index[0].strftime("%Y-%m-%d"), "Tot": df.index[-1].strftime("%Y-%m-%d"),
                "Grootte (MB)": round(sum(p.stat().st_size for p in files.values()) / 1e6, 2),
                "Opslag": "GitHub ✓" if on_gh else ("Nog niet op GitHub" if self.synced else "Tijdelijk (server)"),
            })
        cols = ["Asset", "Timeframe", "Bars", "Van", "Tot", "Grootte (MB)", "Opslag"]
        return pd.DataFrame(rows, columns=cols)

    def save(self, symbol: str, tf: str, df: pd.DataFrame, message: str | None = None) -> SaveReport:
        """Voeg data toe aan de bibliotheek (samenvoegen met bestaande data, nieuwste wint)."""
        symbol = symbol.upper()
        new = df[OHLCV].copy()
        if new.index.tz is None:
            new.index = new.index.tz_localize("UTC")
        new = new[~new.index.duplicated(keep="last")].sort_index()
        old = self.load(symbol, tf)
        before = 0 if old is None else len(old)
        merged = new if old is None else pd.concat([old, new])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()

        years = sorted(set(new.index.year))
        code = TF_CODE[tf]
        local_d = self.local_dir / symbol / code
        local_d.mkdir(parents=True, exist_ok=True)
        payload: dict[str, bytes] = {}
        for y in years:
            part = merged[merged.index.year == y]
            data = _df_to_parquet_bytes(part)
            (local_d / f"{y}.parquet").write_bytes(data)
            payload[f"{self.rel_root}/{symbol}/{code}/{y}.parquet"] = data

        tomb = self._tombstones()
        changed = False
        for y in years:
            changed |= tomb.pop(f"{symbol}/{code}/{y}.parquet", None) is not None
        if changed:
            self._set_tombstones(tomb)

        rep = SaveReport(added=len(merged) - before, total=len(merged), years=years)
        if self.github:
            try:
                self.github.commit_files(payload, message or f"Data: {symbol} {tf} bijgewerkt ({', '.join(map(str, years))})")
                self._mark_synced([f"{symbol}/{code}/{y}.parquet" for y in years])
                rep.synced = True
            except Exception as e:  # noqa: BLE001 - lokale opslag is gelukt, sync-fout melden
                rep.error = str(e)
        return rep

    def delete(self, symbol: str, tf: str) -> SaveReport:
        code = TF_CODE[tf]
        files = self._resolve(f"{symbol}/{code}")
        tomb = self._tombstones()
        now = time.time()
        for name in files:
            lp = self.local_dir / symbol / code / name
            if lp.exists():
                lp.unlink()
            if (self.repo_dir / symbol / code / name).exists():
                tomb[f"{symbol}/{code}/{name}"] = now
        self._set_tombstones(tomb)
        rep = SaveReport()
        if self.github and files:
            try:
                self.github.commit_files({f"{self.rel_root}/{symbol}/{code}/{n}": None for n in files},
                                         f"Data: {symbol} {tf} verwijderd")
                rep.synced = True
            except Exception as e:  # noqa: BLE001
                rep.error = str(e)
        return rep

    # ------------------------------------------------------------------ #
    # generieke documenten (strategieën, profiel, resultaten)
    # ------------------------------------------------------------------ #
    def put_files(self, files: dict[str, bytes], message: str) -> SaveReport:
        """Schrijf meerdere bestanden (pad relatief binnen deze store) lokaal + naar GitHub."""
        tomb = self._tombstones()
        changed = False
        for rel, data in files.items():
            p = self.local_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            changed |= tomb.pop(rel, None) is not None
        if changed:
            self._set_tombstones(tomb)
        rep = SaveReport(total=len(files))
        if self.github and files:
            try:
                self.github.commit_files({f"{self.rel_root}/{k}": v for k, v in files.items()}, message)
                self._mark_synced(list(files))
                rep.synced = True
            except Exception as e:  # noqa: BLE001
                rep.error = str(e)
        return rep

    def get_file(self, rel: str) -> bytes | None:
        d, _, name = rel.rpartition("/")
        p = self._resolve(d).get(name)
        return p.read_bytes() if p else None

    def list_files(self, rel_dir: str) -> list[str]:
        return sorted(self._resolve(rel_dir))

    def list_dirs(self, rel_dir: str) -> list[str]:
        names = set()
        for base in (self.repo_dir, self.local_dir):
            d = base / rel_dir
            if d.is_dir():
                names |= {p.name for p in d.iterdir() if p.is_dir()}
        # een map telt alleen als er nog (niet-verwijderde) bestanden in zitten
        return sorted(n for n in names if self._resolve(f"{rel_dir}/{n}"))

    def delete_files(self, rels: list[str], message: str) -> SaveReport:
        tomb = self._tombstones()
        now = time.time()
        existing = []
        for rel in rels:
            lp = self.local_dir / rel
            found = False
            if lp.exists():
                lp.unlink()
                found = True
            if (self.repo_dir / rel).exists():
                tomb[rel] = now
                found = True
            if found:
                existing.append(rel)
        self._set_tombstones(tomb)
        rep = SaveReport(total=len(existing))
        if self.github and existing:
            try:
                self.github.commit_files({f"{self.rel_root}/{r}": None for r in existing}, message)
                rep.synced = True
            except Exception as e:  # noqa: BLE001
                rep.error = str(e)
        return rep

    def put_json(self, rel: str, obj, message: str) -> SaveReport:
        return self.put_files({rel: json.dumps(obj, default=str, indent=1).encode()}, message)

    def get_json(self, rel: str):
        raw = self.get_file(rel)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    # backtest-runs
    # ------------------------------------------------------------------ #
    def save_run(self, run_id: str, trades: pd.DataFrame, equity: pd.DataFrame, meta: dict,
                 keep: int = 30) -> SaveReport:
        base = f"{RESULTS_DIR}/{run_id}"
        files = {
            f"{base}/trades.parquet": _df_to_parquet_bytes(trades.reset_index(drop=True)),
            f"{base}/equity.parquet": _df_to_parquet_bytes(equity.reset_index(drop=True)),
            f"{base}/meta.json": json.dumps(meta, default=str, indent=1).encode(),
        }
        rep = self.put_files(files, f"Backtest opgeslagen: {meta.get('strategy_name', run_id)}")
        old = self.list_runs()[keep:]
        if old:
            self.delete_files([f"{RESULTS_DIR}/{r}/{n}" for r in old for n in
                               ("trades.parquet", "equity.parquet", "meta.json")], "Oude backtests opgeruimd")
        return rep

    def list_runs(self) -> list[str]:
        """Run-id's, nieuwste eerst (id begint met een tijdstempel)."""
        return sorted(self.list_dirs(RESULTS_DIR), reverse=True)

    def run_meta(self, run_id: str) -> dict | None:
        return self.get_json(f"{RESULTS_DIR}/{run_id}/meta.json")

    def load_run(self, run_id: str) -> tuple[pd.DataFrame, pd.DataFrame, dict] | None:
        files = self._resolve(f"{RESULTS_DIR}/{run_id}")
        if not {"trades.parquet", "equity.parquet", "meta.json"} <= set(files):
            return None
        try:
            return (pd.read_parquet(files["trades.parquet"]), pd.read_parquet(files["equity.parquet"]),
                    json.loads(files["meta.json"].read_text()))
        except Exception:  # noqa: BLE001
            return None

    def delete_run(self, run_id: str) -> SaveReport:
        return self.delete_files([f"{RESULTS_DIR}/{run_id}/{n}" for n in ("trades.parquet", "equity.parquet",
                                                                          "meta.json")], "Backtest verwijderd")


def make_github_sync(token: str | None, repo: str | None, branch: str = "main") -> GitHubSync | None:
    if not token or not repo:
        return None
    return GitHubSync(token=token.strip(), repo=repo.strip(), branch=branch)


__all__ = ["DataStore", "SaveReport", "TF_CODE", "CODE_TF", "make_github_sync", "GitHubError", "TIMEFRAMES"]
