"""OME-1775: a non-frozen source may recover while the cancelled model is absent."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from test_frozen_copy_failed_case import _CAPTURE, _REPLAY, CopyGateway, _assets, _run

from screamingface_engine.world import factory
from screamingface_engine.world.config import WorldConfig
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node


@pytest.mark.asyncio
async def test_recovering_data_source_with_optional_cancelled_model_stays_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: use the real executor, cancellation and replay lookup. Only the data source
    # and provider are stand-ins; no live service or paid model call participates.
    _assets(tmp_path, cases=1)
    model_started = asyncio.Event()
    recovered = False

    async def data() -> str:
        if not recovered:
            await model_started.wait()
            raise ResolutionError(
                "temporary data failure", code="resolution_failed", permanent=False
            )
        return "B"

    def mounts(node: Url4Node, config: WorldConfig) -> None:
        node.data("/flaky", data)

    monkeypatch.setattr(factory, "register_read_side_mounts", mounts)

    async def answer(_model: str, _failing: bool) -> httpx.Response:
        model_started.set()
        await asyncio.Event().wait()
        raise AssertionError("the required data failure must cancel this optional model")

    gateway = CopyGateway(answer)
    candidate = "(required: /flaky, optional: /prov/slow($input)!'answer';optional)!'$required'"
    captured, capture = await _run(gateway, _CAPTURE, candidate, ("prov/slow",), tmp_path, cases=1)
    assert gateway.cancelled == ["prov/slow"]
    assert captured["cases"][0]["status"] == "failed"
    assert captured["score"] is None

    recovered = True
    replayed, _ = await _run(gateway, _REPLAY, candidate, ("prov/slow",), tmp_path, cases=1)
    assert replayed["cases"][0]["status"] == "scored"
    assert replayed["score"] == 1.0
    # WHY: a replay miss can be discarded by ;optional. The unfrozen source determines whether
    # the case scores, so the failed capture case is not evidence that the copy is complete.
    assert capture["capture.status"] == "partial"
    assert capture["capture.partial.error"] == 1
