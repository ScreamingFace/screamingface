"""OME-1127: distinguish zero-byte replies from complete malformed content."""

import httpx
import pytest

from screamingface_engine.runner.connector import _json_or_raise
from url4.core.errors import ResolutionError


@pytest.mark.parametrize("status", [200, 204])
def test_empty_success_is_retryable_without_claiming_a_network_cause(status: int) -> None:
    with pytest.raises(ResolutionError) as caught:
        _json_or_raise(httpx.Response(status, content=b""))
    assert caught.value.code == "aigateway_empty_response"
    assert caught.value.permanent is False
    assert "empty response body" in str(caught.value)
    assert "intercept" not in str(caught.value)


@pytest.mark.parametrize("body", [b"<html>login</html>", b" ", b'{"choices": ['])
def test_nonempty_invalid_json_remains_a_permanent_gateway_fault(body: bytes) -> None:
    # INVARIANT: JSON parse failure alone cannot establish interrupted HTTP delivery.
    with pytest.raises(ResolutionError) as caught:
        _json_or_raise(httpx.Response(200, content=body))
    assert caught.value.code == "aigateway_bad_response"
    assert caught.value.permanent is True
