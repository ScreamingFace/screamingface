"""PLUMBING tests for the OME-961 replay harness — synthetic fixture, NOT a board golden.

What these prove, against the real stack with ZERO provider keys anywhere:

1. the OME-951/952 admin upload seeds the cache from a snapshot fixture,
2. recorded exchanges — candidate-shaped AND judge-shaped, through the one
   ``/v1/chat/completions`` seam (parent R5's harness half) — replay verbatim (plus
   the gateway's reserved ``_aigw`` accounting namespace) before any credential is
   resolved,
3. a request that is NOT on the tape dies loudly (``404 profile_not_found``) with no
   provider dispatch: spend impossible by construction (parent R2),
4. the real engine boots against the replay gateway and serves the SDK the way a
   notebook reaches it (the transport half of parent R1).

The fixture is AUTHORED (``provenance.authored=true``, board "synthetic") — it proves
the pipes carry water, it does not certify any benchmark outcome. Board goldens live in
``test_boards.py`` and only ever run against real recorded snapshots.
"""

from __future__ import annotations

import json

import httpx
import pytest
from harness.stack import EngineProcess
from harness.tape import LoadedTape

pytestmark = pytest.mark.e2e


def test_the_snapshot_seeds_the_cache_through_the_admin_route(
    synthetic_gateway: str, synthetic_tape: LoadedTape
) -> None:
    # The upload job already ran to `complete` inside the fixture boot (anything else
    # raises SnapshotLoadFailed there); this pins the observable outcome: the rows are
    # live and the store is serving.
    info = httpx.get(f"{synthetic_gateway}/v1/admin/cache/info", timeout=10.0).json()

    assert info["serving"] is True
    assert info["row_count"] >= len(synthetic_tape.exchanges())


def test_recorded_exchanges_replay_verbatim_with_zero_provider_keys(
    synthetic_gateway: str, synthetic_tape: LoadedTape
) -> None:
    # Candidate and judge exchanges replay through the SAME seam — the tape has one of
    # each, and the loop treats them identically because the gateway does.
    #
    # Wire contract (measured, not assumed): the gateway serves the STORED payload
    # verbatim plus its reserved `_aigw` accounting namespace on top (a cache hit is
    # accounted with zero new attempts — taxonomy `attach_hit_metadata`). Byte-identity
    # proper is a STORE property, pinned by aigateway's own Postgres round-trip test;
    # here the provider fields must be structurally identical to the recording.
    assert synthetic_tape.provenance.authored is True  # plumbing tape, never a recording
    for exchange in synthetic_tape.exchanges():
        response = httpx.post(
            f"{synthetic_gateway}{exchange.request.path}",
            json=exchange.request.body,
            timeout=30.0,
        )

        assert response.status_code == exchange.response.status, response.text
        assert response.headers["X-AIGW-Cache"] == "hit"
        served = response.json()
        accounting = served.pop("_aigw", None)
        assert accounting is not None, "a hit must carry the gateway's accounting block"
        assert served == json.loads(exchange.response.body), (
            "the recorded provider payload must reach the caller unmodified "
            "(only the reserved _aigw namespace may be added)"
        )


def test_a_cache_miss_is_a_loud_error_and_never_reaches_a_provider(
    synthetic_gateway: str,
) -> None:
    # INVARIANT (parent R2): no provider key exists in the gateway's environment, so
    # the miss path MUST die at credential resolution — loudly, before any dispatch.
    response = httpx.post(
        f"{synthetic_gateway}/v1/chat/completions",
        json={
            "model": "openrouter/openai/gpt-5.5",
            "messages": [{"role": "user", "content": "this call was never recorded"}],
        },
        timeout=30.0,
    )

    assert response.status_code == 404, response.text
    # `profile_not_found` is raised by credential resolution — i.e. AFTER the cache
    # missed and BEFORE any dispatch. Its very shape is the proof: a dispatched call
    # would have failed as a provider auth error, and a hit would have been 200.
    # (Measured: the gateway's error path carries no X-AIGW-Cache header.)
    assert response.json()["detail"]["code"] == "profile_not_found"
    assert response.headers.get("X-AIGW-Cache") != "hit"


def test_the_engine_boots_against_the_replay_gateway_and_serves_the_sdk(
    synthetic_gateway: str, tmp_path
) -> None:
    """The notebook-shaped transport chain: SDK → engine → (replay) gateway.

    No benchmark assets are mounted, so no boards install — deliberately: this test
    proves the stack wiring the SDK path needs (catalog + benchmark routes answer),
    while board execution stays with ``test_boards.py`` and real recorded fixtures.

    Gating note: the ``synthetic_gateway`` fixture already skipped us when the e2e
    stack (env gate + docker) is unavailable.
    """
    import screamingface as sf

    engine = EngineProcess(work_dir=tmp_path)
    try:
        engine_url = engine.start(synthetic_gateway)

        # The SDK reaches the engine exactly as a notebook does.
        with sf.Client(engine_url=engine_url) as client:
            models = client.models.list()
        assert any(model.id.startswith("openrouter/") for model in models), (
            "the engine's catalog should project the gateway's seeded openrouter "
            "models with zero keys configured"
        )

        # The benchmark surface answers (empty without assets — that is the contract).
        catalogue = httpx.get(f"{engine_url}/v1/benchmarks", timeout=10.0)
        assert catalogue.status_code == 200, catalogue.text
        assert json.loads(catalogue.text) is not None
    finally:
        engine.stop()
