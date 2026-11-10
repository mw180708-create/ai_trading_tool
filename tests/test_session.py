import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_tool.accounts import Accounts  # noqa: E402
from webapp import session_cookie as C  # noqa: E402
from webapp import state as S  # noqa: E402


def _setup(tmp_path, monkeypatch):
    acc = Accounts(tmp_path / "cache", local_root=tmp_path / "local")
    acc.register("fien", "eerste-wachtwoord")
    monkeypatch.setattr(S, "accounts", lambda: acc)
    monkeypatch.setattr(C, "_key", lambda: b"k" * 32)
    return acc


def test_cookie_roundtrip_and_tampering(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    tok = C.issue("fien")
    assert C.verify(tok) == "fien"
    body, sig = tok.rsplit(".", 1)
    assert C.verify(body + "." + "0" * len(sig)) is None          # vervalste handtekening
    import base64, json
    fake = base64.urlsafe_b64encode(json.dumps({"u": "admin", "e": int(time.time()) + 999}).encode()).decode().rstrip("=")
    assert C.verify(fake + "." + sig) is None                       # andere gebruiker, oude handtekening
    assert C.verify(None) is None and C.verify("onzin") is None


def test_cookie_expires_and_dies_on_password_change(tmp_path, monkeypatch):
    acc = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(C, "MAX_AGE", -10)
    assert C.verify(C.issue("fien")) is None                        # verlopen
    monkeypatch.setattr(C, "MAX_AGE", 3600)
    tok = C.issue("fien")
    acc.change_password("fien", "eerste-wachtwoord", "tweede-wachtwoord")
    assert C.verify(tok) is None                                    # wachtwoord gewijzigd -> sessie ongeldig
    assert C.verify(C.issue("fien")) == "fien"
