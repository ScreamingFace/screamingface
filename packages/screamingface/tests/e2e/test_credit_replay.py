"""Authored failure replay explicitly models credit metadata, never live balances."""

import httpx
import pytest
from harness.fake_gateway import FakeGateway
from test_failures import _authored_tape
from test_failures import failure_stack as failure_stack

from screamingface.credit import _decode


@pytest.mark.parametrize("suffix", ["", "/key"])
def test_taped_provider_has_unknown_credit_without_off_surface_requests(suffix):
    fake = FakeGateway(_authored_tape())
    origin = fake.start_sync()
    try:
        response = httpx.get(origin + "/v1/credits/openrouter" + suffix + "?refresh=false")
        assert response.status_code == 200
        value = _decode(response, "openrouter")
        assert value.account.status == value.key.status == "unavailable"
        assert value.account.amount_usd is value.key.amount_usd is None
        assert value.key.reason == "not_connected"
        assert fake.refusals == ()
    finally:
        fake.stop_sync()


def test_untaped_credit_provider_is_still_refused():
    fake = FakeGateway(_authored_tape())
    origin = fake.start_sync()
    try:
        assert httpx.get(origin + "/v1/credits/untaped?refresh=false").status_code == 404
        assert len(fake.refusals) == 1
    finally:
        fake.stop_sync()


@pytest.mark.e2e
@pytest.mark.parametrize("credit_reply", ["zero", "failed"])
def test_credit_notice_preserves_failure_report_and_reads_once(
    failure_stack, monkeypatch, credit_reply
):
    import json
    from datetime import UTC, datetime

    from harness.fake_gateway import _Handler
    from test_failures import _rehearse

    baseline = _rehearse(failure_stack, "rate_limit_429")
    original = _Handler._reply
    reads = []

    def reply(handler, status, body, media_type, *, close=False):
        from urllib.parse import urlsplit

        if urlsplit(handler.path).path == "/v1/credits/openrouter":
            reads.append(handler.path)
            if credit_reply == "failed":
                status, body = 503, b'{"detail":"unavailable"}'
            else:
                document = json.loads(body)
                document["connection_token"] = "a" * 64
                document["key"] = {
                    "status": "available",
                    "amount_usd": "0",
                    "as_of": datetime.now(UTC).isoformat(),
                    "reason": None,
                }
                body = json.dumps(document).encode()
        return original(handler, status, body, media_type, close=close)

    monkeypatch.setattr(_Handler, "_reply", reply)
    actual = _rehearse(failure_stack, "rate_limit_429")
    assert reads == ["/v1/credits/openrouter?refresh=false"]
    assert actual.status == baseline.status
    assert [(f.stage, f.code, f.retryable, f.message) for f in actual.failures] == [
        (f.stage, f.code, f.retryable, f.message) for f in baseline.failures
    ]
