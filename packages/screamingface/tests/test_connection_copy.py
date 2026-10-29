"""OME-1138 close-out L8: the SDK's user-facing copy speaks of Connections, not provider profiles.

Stage D made provider access selector-less (D12) and D20 made Connection the product noun, so no
message may send a user to a "selected provider profile". The retained wire codes and their R3
decoder (`profile_not_found` and friends) are pinned in `test_model_parameter_discovery.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_provider_access_preflight import _MODEL, _AsyncRun, _Engine, _evaluate, _Run

import screamingface as sf
from screamingface._engine.catalog import AsyncModels, Models

_README = Path(__file__).resolve().parents[1] / "README.md"
_HINT = (
    "Open sf.connect() to connect the provider, or ask the operator of your hosted Engine "
    "to connect it in AI Gateway, then retry."
)
_MODEL_NOT_FOUND = {
    "detail": {"code": "model_not_found", "provider": "openrouter", "model": "openrouter/nope"}
}


def _model_not_found(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, json=_MODEL_NOT_FOUND)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_missing_access_hint_names_the_connection_paths(mode: str) -> None:
    # STORY: as a researcher whose provider is not connected, the refusal tells me how to connect
    # it locally and who connects it on a hosted Engine, never to pick a provider profile.
    engine = _Engine({_MODEL: "missing"})
    runs = _Run() if mode == "sync" else _AsyncRun()

    with pytest.raises(sf.ProviderConnectionError) as caught:
        await _evaluate(mode, engine, sf.Model(_MODEL), [], runs)

    assert caught.value.code == "provider_not_connected"
    assert caught.value.hint == _HINT
    assert "profile" not in caught.value.message.lower()
    assert runs.calls == 0


def _sync_get(handler: Callable[[httpx.Request], httpx.Response], model: str) -> None:
    with sf.Client(
        engine_url="https://engine.example", http_transport=httpx.MockTransport(handler)
    ) as client:
        client.models.get(model)


async def _async_get(handler: Callable[[httpx.Request], httpx.Response], model: str) -> None:
    async with sf.AsyncClient(
        engine_url="https://engine.example", http_transport=httpx.MockTransport(handler)
    ) as client:
        await client.models.get(model)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_model_not_found_names_the_gateway_catalogue_without_a_profile(mode: str) -> None:
    # WHY: the gateway answers `model_not_found` from its own catalogue (seeded, admitted and the
    # cached live listing) before it reads any credential, so the message names that catalogue,
    # not a Connection, a selection or the provider itself.
    with pytest.raises(sf.PlanningError) as caught:
        if mode == "sync":
            _sync_get(_model_not_found, "openrouter/nope")
        else:
            await _async_get(_model_not_found, "openrouter/nope")

    assert caught.value.message == "Model 'openrouter/nope' is not in AI Gateway's catalogue"
    assert caught.value.code == "model_not_found"
    assert caught.value.status == 404
    assert caught.value.permanent is True
    assert caught.value.details == _MODEL_NOT_FOUND["detail"]


@pytest.mark.parametrize("get", [Models.get, AsyncModels.get])
def test_model_details_docstrings_describe_the_connection_context(get: Any) -> None:
    doc = get.__doc__ or ""

    assert "Connection-specific" in doc
    assert "profile" not in doc.lower()


@pytest.mark.parametrize("phrase", ["provider profile", "profile-specific"])
def test_readme_never_describes_access_in_profile_terms(phrase: str) -> None:
    # INVARIANT: the README is the published package description (`readme` in pyproject.toml).
    assert phrase not in _README.read_text(encoding="utf-8").lower()
