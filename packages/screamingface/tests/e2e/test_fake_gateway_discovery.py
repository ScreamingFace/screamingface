"""The authored replay backend supports the SDK's pre-dispatch discovery."""

import httpx
import pytest
from harness.fake_gateway import FakeGateway
from test_failures import CANDIDATE_MODEL, _authored_tape

from screamingface._engine.model_parameters import _decode_model_details


def test_taped_model_details_support_access_preflight() -> None:
    fake = FakeGateway(_authored_tape())
    base_url = fake.start_sync()
    try:
        response = httpx.get(f"{base_url}/v1/model-parameters", params={"model": CANDIDATE_MODEL})
        assert response.status_code == 200
        details = _decode_model_details(response.json(), CANDIDATE_MODEL)
        assert details.provider == "openrouter"
        assert details.execution_access == "configured"
        assert details.parameters == {}
        assert fake.refusals == ()
    finally:
        fake.stop_sync()


@pytest.mark.parametrize("query", [{}, {"model": "untaped/model"}])
def test_model_details_refuse_untaped_identities(query: dict[str, str]) -> None:
    fake = FakeGateway(_authored_tape())
    base_url = fake.start_sync()
    try:
        response = httpx.get(f"{base_url}/v1/model-parameters", params=query)
        assert response.status_code == 404
        assert len(fake.refusals) == 1
    finally:
        fake.stop_sync()
