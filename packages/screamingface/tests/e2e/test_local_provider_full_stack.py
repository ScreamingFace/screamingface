from __future__ import annotations

import asyncio

import e2e.harness.local_provider_stack as local_stack
import pytest
from e2e.harness.local_provider_stack import LocalProviderBackend, prepare_medxpert_assets
from e2e.harness.stack import replay_stack

import screamingface as sf

_RAW_MODELS = (
    "local/member-a:v1",
    "local/member-b:v1",
    "local/member-c:v1",
    "local/synth:v1",
)
_ROUTES = tuple(model.replace(":", "~") for model in _RAW_MODELS)


def test_backend_rolls_back_model_server_when_gateway_start_fails(
    tmp_path,
    monkeypatch,
) -> None:
    backend = LocalProviderBackend(work_dir=tmp_path, model_ids=_RAW_MODELS)

    def fail_sync(_project) -> None:
        raise RuntimeError("sync failed")

    monkeypatch.setattr(local_stack, "sync_project", fail_sync)

    with pytest.raises(RuntimeError, match="sync failed"):
        asyncio.run(backend.start())
    with pytest.raises(RuntimeError, match="sync failed"):
        asyncio.run(backend.start())

    asyncio.run(backend.stop())


def test_local_provider_discovery_reaches_a_real_fusion_benchmark(tmp_path) -> None:
    assets = prepare_medxpert_assets(tmp_path / "benchmark-assets")
    backend = LocalProviderBackend(work_dir=tmp_path, model_ids=_RAW_MODELS)

    with replay_stack(backend, work_dir=tmp_path, assets_dir=assets) as stack:
        with sf.Client(engine_url=stack.engine_url) as client:
            report = client.evaluate(
                sf.Fanout(_ROUTES[:3]) >> sf.Synthesize(_ROUTES[3]),
                benchmark="medxpert",
                limit=1,
                progress=False,
            )

    candidate = report.candidates.only
    assert candidate.score == 1.0
    assert candidate.coverage == 1.0
    assert candidate.cases[0].status == "scored"
    operations = candidate.cases[0].operations
    assert operations is not None
    assert {operation.operation_id for operation in operations} == {
        "op_model_1",
        "op_model_2",
        "op_model_3",
        "op_synthesis_1",
    }
    assert set(backend.seen_models) == set(_RAW_MODELS)
    assert backend.refusals == ()
