"""The route-level arrangement the direct-OpenAI cache suites share.

WHY a module rather than a copy per suite: three cohesive suites drive the SAME app, the
same in-memory store and the same dispatch double — the ordinary miss/store/replay lane
and its refusals, the key-material proofs (profile defaults in, identity out), and the
ambient modifier end to end. They are only comparable while they arrange the world
identically; three copies of a recording store would drift.

INVARIANT: the store double records READS as well as rows. "Did not store" and "never
looked" are different failures, and a bypass must do neither — only the read log can tell
a bypass apart from a miss that stored nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal, cast
from unittest.mock import patch

from fastapi.testclient import TestClient

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.request_cache import RequestCacheWrite

CHAT_PATH = "/v1/chat/completions"
KEY = "sk-openai-synthetic-route-cache-key-1234"

# A model the bootstrap catalog publishes, and one that is route-valid but absent from
# it. The whole point of these suites is that the cache cannot tell them apart.
PUBLISHED = "openai/gpt-5.6-sol"
UNLISTED = "openai/gpt-4o-2024-11-20"

WriteStatus = Literal["stored", "race_lost", "not_stored"]


@dataclass
class ValidValidationService:
    async def validate(self, _plugin, _provider: str, _api_key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID,
            stage=ApiKeyValidationStage.READINESS,
            probe_model="openai/gpt-5-nano",
        )


class Store:
    """The frozen store contract in memory, recording every read and write.

    WHY the reads are recorded and not just the rows: "did not store" and "never
    looked" are different failures. A bypass must do NEITHER, and only the read log
    can tell a bypass apart from a miss that stored nothing.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.reads: list[str] = []
        self.writes: list[RequestCacheWrite] = []

    def cache_available(self) -> bool:
        return True

    async def get(self, key_hash: str) -> dict[str, Any] | None:
        self.reads.append(key_hash)
        return self.rows.get(key_hash)

    async def set_if_absent(self, entry: RequestCacheWrite) -> WriteStatus:
        self.writes.append(entry)
        if entry.key_hash in self.rows:
            return "race_lost"
        self.rows[entry.key_hash] = entry.response
        return "stored"


class Dispatch:
    """Records every body that actually reached the provider, and answers uniquely."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def __call__(self, body):
        # An INSTANCE patched over the method is not a descriptor, so it is called with
        # the body alone — no ``self`` from the plugin.
        self.bodies.append(json.loads(json.dumps(body, default=str)))
        payload = {
            "id": f"resp-{len(self.bodies)}",
            "choices": [
                {
                    "message": {"content": f"ANSWER-{len(self.bodies)}"},
                    "finish_reason": "stop",
                }
            ],
        }
        return SimpleNamespace(model_dump=lambda: payload)


def install(client: TestClient, store: Store) -> Store:
    cast(Any, client.app).state.request_cache_store = store
    return store


def dispatching(client: TestClient, dispatch: Any):
    """Patch ``chat_completion`` on the exact plugin INSTANCE the app dispatches through.

    AIDEV-NOTE: resolving the plugin from the registry, rather than patching
    ``OpenAIProviderPlugin.chat_completion`` on the class, is what makes these tests say
    what they mean — the object under test is the one the route will actually call, not
    every instance that happens to share its class.

    It also stays immune to a hazard this directory has already hit once: the registry
    holds a single module-level ``PLUGIN`` singleton, and
    ``monkeypatch.setattr(plugin, "chat_completion", ...)`` on it does NOT undo cleanly —
    pytest reads the old value with ``getattr`` (which resolves through the class) and
    restores it with ``setattr``, permanently installing the original bound method as an
    instance attribute that shadows any later class-level patch. That leak has since been
    fixed at its source (``test_openai_persistence`` now uses scoped ``patch.object`` and
    asserts ``"chat_completion" not in vars(plugin)`` afterwards), so this helper no
    longer works around anything — but ``patch.object`` is still the right tool, because
    it inspects ``__dict__`` and removes exactly what it added.
    """
    plugin = cast(Any, client.app).state.providers.get("openai")
    return patch.object(plugin, "chat_completion", new=dispatch)


def seed_profile(
    client: TestClient, *, name: str = "default", defaults: dict[str, Any] | None = None
) -> None:
    """Give the caller a dispatchable direct-OpenAI profile, optionally with defaults."""
    cast(Any, client.app).state.api_key_validation_service = ValidValidationService()
    payload: dict[str, Any] = {"api_key": KEY}
    if defaults is not None:
        payload["defaults"] = defaults
    created = client.put(f"/v1/auth/openai/profiles/{name}/api-key", json=payload)
    assert created.status_code == 200, created.text


def body(
    *, model: str = PUBLISHED, question: str = "how many primes below one hundred?", **extra
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": question}],
    }
    body.update(extra)
    return body


def post(client: TestClient, body: dict[str, Any], *, profile: str | None = None):
    headers = {"X-Profile": profile} if profile is not None else {}
    return client.post(CHAT_PATH, json=body, headers=headers)


def system_contents(body: dict[str, Any]) -> list[str]:
    return [m["content"] for m in body.get("messages", []) if m.get("role") == "system"]


def listed_models(client: TestClient) -> set[str]:
    listing = client.get("/v1/models")
    assert listing.status_code == 200, listing.text
    return {row["id"] for row in listing.json()["data"]}
