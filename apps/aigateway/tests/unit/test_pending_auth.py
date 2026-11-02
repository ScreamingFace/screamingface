import time

from aigateway.core.pending_auth import PendingAuthEntry, PendingAuthTable

ENTRY = PendingAuthEntry(
    account_id="account-1",
    provider="anthropic",
    profile_name="work",
    code_verifier="v",
    redirect_uri="http://localhost:9105/callback",
    connection_id="connection-1",
)


def test_pending_table_round_trip() -> None:
    table = PendingAuthTable(ttl_seconds=600)
    table.put("state-1", ENTRY)
    entry = table.pop("state-1")
    assert entry is not None
    assert entry.account_id == "account-1"
    assert entry.provider == "anthropic"
    assert entry.profile_name == "work"
    assert entry.connection_id == "connection-1"
    assert entry.code_verifier == "v"
    assert entry.redirect_uri == "http://localhost:9105/callback"


def test_pop_consumes_entry() -> None:
    table = PendingAuthTable(ttl_seconds=600)
    table.put("state-1", ENTRY)
    table.pop("state-1")
    assert table.pop("state-1") is None  # second pop is a miss


def test_expired_entry_is_swept(monkeypatch) -> None:
    fake = {"now": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: fake["now"])
    table = PendingAuthTable(ttl_seconds=10)
    table.put("state-1", ENTRY)
    fake["now"] = 1100.0  # 100s later
    assert table.pop("state-1") is None


def test_unknown_state_returns_none() -> None:
    table = PendingAuthTable(ttl_seconds=600)
    assert table.pop("nonexistent") is None
