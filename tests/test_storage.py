import base64
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_tool.github_sync import GitHubSync  # noqa: E402
from trading_tool.live import analyze_live  # noqa: E402
from trading_tool.storage import DataStore  # noqa: E402
from trading_tool.synthetic import demo_dataset, generate_ohlc  # noqa: E402


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status
        self.content = b"x"
        self.text = str(data)

    def json(self):
        return self._data


class FakeGitHub:
    """Minimale nabootsing van de GitHub Git Data API."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.headers = {}
        self._blobs: dict[str, bytes] = {}
        self._pending = None

    def request(self, method, url, timeout=None, json=None, params=None):
        path = url.split("/repos/owner/repo", 1)[1]
        self.calls.append((method, path))
        if method == "GET" and path == "":
            return FakeResp({"full_name": "owner/repo", "permissions": {"push": True}})
        if method == "GET" and path.startswith("/git/ref/heads/"):
            return FakeResp({"object": {"sha": "c1"}})
        if method == "GET" and path.startswith("/git/commits/"):
            return FakeResp({"tree": {"sha": "t1"}})
        if method == "POST" and path == "/git/blobs":
            sha = f"b{len(self._blobs)}"
            self._blobs[sha] = base64.b64decode(json["content"])
            return FakeResp({"sha": sha})
        if method == "POST" and path == "/git/trees":
            self._pending = json["tree"]
            return FakeResp({"sha": "t2"})
        if method == "POST" and path == "/git/commits":
            assert json["parents"] == ["c1"]
            return FakeResp({"sha": "c2"})
        if method == "PATCH":
            for e in self._pending:
                if e["sha"] is None:
                    self.files.pop(e["path"], None)
                else:
                    self.files[e["path"]] = self._blobs[e["sha"]]
            return FakeResp({})
        return FakeResp({"message": "not found"}, 404)


def _sample(start="2023-01-01", end="2023-03-01", freq="1h"):
    return generate_ohlc("BTCUSD", start, end, freq, seed=1)


def test_store_save_merge_load_delete(tmp_path):
    store = DataStore(tmp_path)
    a = _sample("2023-12-01", "2024-01-15")
    b = _sample("2024-01-10", "2024-02-01")
    r1 = store.save("BTCUSD", "1H", a)
    assert r1.added == len(a) and r1.years == [2023, 2024]
    r2 = store.save("BTCUSD", "1H", b)
    loaded = store.load("BTCUSD", "1H")
    assert loaded.index.is_monotonic_increasing and not loaded.index.duplicated().any()
    assert loaded.index[0] == a.index[0] and loaded.index[-1] == b.index[-1]
    assert r2.added == len(loaded) - len(a)
    assert store.symbols() == ["BTCUSD"] and store.timeframes("BTCUSD") == ["1H"]
    ds = store.datasets()
    assert ds.iloc[0]["Bars"] == len(loaded)
    fp1 = store.fingerprint()
    store.delete("BTCUSD", "1H")
    assert store.load("BTCUSD", "1H") is None and store.fingerprint() != fp1


def test_month_and_minute_do_not_collide(tmp_path):
    store = DataStore(tmp_path)
    store.save("XAUUSD", "1m", _sample("2024-01-01", "2024-01-02", "1min"))
    store.save("XAUUSD", "1M", _sample("2020-01-01", "2024-01-01", "1D").resample("MS").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}))
    assert set(store.timeframes("XAUUSD")) == {"1m", "1M"}


def test_github_sync_commits_and_deletes(tmp_path):
    fake = FakeGitHub()
    gh = GitHubSync(token="t", repo="owner/repo", session=fake)
    assert gh.check()[0]
    store = DataStore(tmp_path, github=gh)
    rep = store.save("BTCUSD", "1D", _sample("2023-06-01", "2024-02-01", "1D"))
    assert rep.synced and rep.error is None
    assert set(fake.files) == {"data/store/BTCUSD/D1/2023.parquet", "data/store/BTCUSD/D1/2024.parquet"}
    # repository-kopie (na "git pull") wordt gelezen als de lokale kopie weg is
    for path, data in fake.files.items():
        p = tmp_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    fresh = DataStore(tmp_path, local_root=tmp_path / "other_local")
    assert len(fresh.load("BTCUSD", "1D")) == rep.total
    store.delete("BTCUSD", "1D")
    assert fake.files == {}
    assert store.load("BTCUSD", "1D") is None   # tombstone verbergt de oude repo-kopie


def test_runs_history_and_namespaces(tmp_path):
    alice = DataStore(tmp_path, namespace="users/alice")
    bob = DataStore(tmp_path, namespace="users/bob")
    shared = DataStore(tmp_path)
    trades = pd.DataFrame({"symbol": ["BTCUSD"], "r_multiple": [1.5],
                           "entry_time": [pd.Timestamp("2024-01-01", tz="UTC")]})
    eq = pd.DataFrame({"symbol": ["BTCUSD"] * 2, "time": pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True),
                       "equity": [100.0, 101.5]})
    for i in range(3):
        alice.save_run(f"2024010{i}-000000-x", trades, eq, {"run_at": str(i)}, keep=2)
    assert alice.list_runs() == ["20240102-000000-x", "20240101-000000-x"]   # oudste opgeruimd
    t, e, meta = alice.load_run("20240102-000000-x")
    assert t["r_multiple"].iloc[0] == 1.5 and e["equity"].iloc[-1] == 101.5 and meta["run_at"] == "2"
    # data en documenten zijn gescheiden per gebruiker
    alice.save("XAUUSD", "1D", _sample("2022-01-01", "2023-03-01", "1D"))
    alice.put_json("strategies/s1.json", {"name": "Mijn strategie"}, "test")
    assert bob.symbols() == [] and bob.list_files("strategies") == [] and bob.list_runs() == []
    assert shared.symbols() == []          # gedeelde bibliotheek ziet gebruikersmappen niet als assets
    assert alice.get_json("strategies/s1.json")["name"] == "Mijn strategie"
    alice.delete_files(["strategies/s1.json"], "weg")
    assert alice.list_files("strategies") == []


def test_live_state():
    s = analyze_live(demo_dataset("BTCUSD"))
    assert 0 <= s.score <= 100 and len(s.rows) == 5
    assert s.status in {"none", "wait_poi", "wait_confirm", "signal"} and s.decision


class StatusSession:
    """Geeft vaste statuscodes terug voor de check()-stappen."""

    def __init__(self, repo_status, blob_status=201):
        self.repo_status, self.blob_status, self.headers = repo_status, blob_status, {}

    def request(self, method, url, timeout=None, json=None, params=None):
        if method == "GET":
            return FakeResp({"full_name": "owner/repo"}, self.repo_status)
        return FakeResp({"sha": "x"}, self.blob_status)


def test_check_messages():
    mk = lambda r, b=201: GitHubSync(token="t", repo="owner/repo", session=StatusSession(r, b)).check()  # noqa: E731
    ok, msg = mk(200)
    assert ok and "schrijven werkt" in msg
    ok, msg = mk(401)
    assert not ok and "ongeldig" in msg
    ok, msg = mk(404)
    assert not ok and "geen toegang" in msg
    ok, msg = mk(200, 403)
    assert not ok and "Read and write" in msg


def test_secret_cleaning():
    from webapp.state import _token_from_secrets, clean_repo, clean_token
    assert clean_token('  "ghp_abc123" \n') == "ghp_abc123"
    assert clean_token("Bearer ghp_x") == "ghp_x"
    assert clean_repo("https://github.com/mw180708-create/ai_trading_tool.git") == "mw180708-create/ai_trading_tool"
    assert _token_from_secrets({"github_token": "ghp_1"}) == "ghp_1"
    assert _token_from_secrets({"github": {"token": "ghp_2"}}) == "ghp_2"
    assert _token_from_secrets({}) is None


def test_push_unsynced_after_connecting(tmp_path):
    store = DataStore(tmp_path)                      # eerst zonder GitHub
    store.save("XAUUSD", "1D", _sample("2023-06-01", "2024-02-01", "1D"))
    assert len(store.unsynced_files()) == 2
    assert set(store.datasets()["Opslag"]) == {"Tijdelijk (server)"}
    fake = FakeGitHub()
    store.github = GitHubSync(token="t", repo="owner/repo", session=fake)   # daarna koppelen
    assert set(store.datasets()["Opslag"]) == {"Nog niet op GitHub"}
    rep = store.push_unsynced()
    assert rep.synced and rep.total == 2 and len(fake.files) == 2
    assert store.unsynced_files() == [] and set(store.datasets()["Opslag"]) == {"GitHub ✓"}


def test_commit_retries_when_branch_moved(tmp_path):
    class Racy(FakeGitHub):
        def __init__(self):
            super().__init__()
            self.patches = 0

        def request(self, method, url, timeout=None, json=None, params=None):
            if method == "PATCH":
                self.patches += 1
                if self.patches == 1:          # iemand anders committe net -> GitHub weigert
                    return FakeResp({"message": "Update is not a fast forward"}, 422)
            return super().request(method, url, timeout=timeout, json=json, params=params)
    fake = Racy()
    gh = GitHubSync(token="t", repo="owner/repo", session=fake)
    gh.commit_files({"a.txt": b"x"}, "test")
    assert fake.patches == 2 and fake.files == {"a.txt": b"x"}


def test_user_files_go_to_user_folder_on_github(tmp_path):
    from trading_tool.accounts import Accounts
    fake = FakeGitHub()
    acc = Accounts(tmp_path, github=GitHubSync(token="t", repo="owner/repo", session=fake))
    assert acc.register("dana", "lang-genoeg-123")[0]
    acc.store_for("dana").save("EURUSD", "1H", _sample("2023-01-01", "2023-03-01", "1h"))
    acc.store_for("dana").put_json("strategies/x.json", {"id": "x"}, "s")
    paths = sorted(fake.files)
    assert "data/store/users/dana/account/profile.json" in paths
    assert "data/store/users/dana/EURUSD/H1/2023.parquet" in paths
    assert "data/store/users/dana/strategies/x.json" in paths
    assert all(p.startswith("data/store/users/dana/") for p in paths)
