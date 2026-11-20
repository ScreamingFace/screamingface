"""Opt-in verification against a real Engine: the evaluation is one Run the Engine drives
(E5 P2 spec D1), registered, followed and read back."""

from __future__ import annotations

import os
from contextlib import closing

import pytest
from _run_engine import CollectingSink

from screamingface._engine.transport import Url4CloudTransport
from screamingface._evaluation.model import _compiled_candidate, _compiled_operation

_ENGINE_URL = os.environ.get("SCREAMINGFACE_URL4_CLOUD_INTEGRATION_URL")
_URL4 = os.environ.get(
    "SCREAMINGFACE_URL4_CLOUD_INTEGRATION_URL4",
    "('transport smoke')!'return the input'",
)

pytestmark = pytest.mark.skipif(
    _ENGINE_URL is None,
    reason="set SCREAMINGFACE_URL4_CLOUD_INTEGRATION_URL to test a real url4-cloud runner",
)


def test_real_url4_cloud_runner_completes_the_confirmed_transport_lifecycle() -> None:
    assert _ENGINE_URL is not None
    candidate = _compiled_candidate(
        name="transport-smoke",
        kind="model",
        models=("transport/static-input",),
        url4=_URL4,
        operations=(
            _compiled_operation(
                id="op_transport_smoke",
                kind="model",
                label="transport smoke",
                depends_on=(),
            ),
        ),
    )

    sink = CollectingSink()
    with closing(Url4CloudTransport(_ENGINE_URL)) as transport:
        run_id = transport.register_run(None, (candidate,))
        transport.follow_run(run_id, (candidate,), sink)
    outcome = sink.outcomes[0]

    assert not isinstance(outcome, Exception), outcome
    assert outcome.result_body is not None
    assert outcome.result_body.strip()
