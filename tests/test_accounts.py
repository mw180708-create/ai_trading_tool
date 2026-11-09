import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_tool import accounts as A  # noqa: E402


def test_register_login_and_isolation(tmp_path):
    acc = A.Accounts(tmp_path)
    assert acc.register("Alice", "geheim-wachtwoord", "geheim-wachtwoord")[0]
    assert not acc.register("alice", "nogeen-wachtwoord")[0]          # bestaat al (hoofdletters tellen niet)
    assert not acc.register("al", "geheim-wachtwoord")[0]              # te kort
    assert not acc.register("bob", "kort")[0]                          # wachtwoord te kort
    assert not acc.register("bob", "geheim-wachtwoord", "anders123")[0]
    assert acc.login("alice", "geheim-wachtwoord")[0]
    assert not acc.login("alice", "fout-wachtwoord")[0]
    assert not acc.login("niemand", "geheim-wachtwoord")[0]
    # wachtwoord staat nergens leesbaar opgeslagen
    raw = (tmp_path / ".datastore/users/alice/account/profile.json").read_text()
    assert "geheim-wachtwoord" not in raw and json.loads(raw)["password"]["algo"] == "scrypt"
    assert acc.profile("alice")["username"] == "alice" and "password" not in acc.profile("alice")
    assert acc.list_users() == ["alice"]
    assert acc.store_for("alice").local_dir != acc.store_for("bob").local_dir


def test_lockout_and_password_change(tmp_path):
    acc = A.Accounts(tmp_path)
    acc.register("carol", "eerste-wachtwoord")
    for _ in range(A.MAX_FAILS):
        acc.login("carol", "fout")
    ok, msg = acc.login("carol", "eerste-wachtwoord")
    assert not ok and "Te veel" in msg
    acc._fails.clear()
    assert acc.change_password("carol", "eerste-wachtwoord", "tweede-wachtwoord")[0]
    assert acc.login("carol", "tweede-wachtwoord")[0] and not acc.login("carol", "eerste-wachtwoord")[0]
