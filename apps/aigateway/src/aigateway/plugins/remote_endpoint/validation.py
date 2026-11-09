"""Key readiness for one configured endpoint: one bounded synthetic request of its target's task.

# INVARIANT: the probe goes to the instance's own origin and validation target with exactly the
# supplied key; only a well-formed success is VALID, and only at READINESS, so the shared service's
# publication rule is satisfied by a real round trip and nothing less.
# FEATURE: hosted BYOM Unit 3 — a classifier validation target is probed with one classification,
# read by the same decoder dispatch uses; the status table is the chat probe's.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

import httpx

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.api_key_validation_http import (
    ApiKeyValidationTransportError,
    BoundedJsonResponse,
    ValidationHttpSession,
)

from .classification import classification_request, decode_scores
from .completion import decode_completion
from .definitions import ChatTarget, ClassificationTarget, EndpointDefinition
from .request import chat_request

_READINESS = ApiKeyValidationStage.READINESS
# WHY no `max_tokens` and no `stream`: the probe is exactly the request an ordinary chat sends when
# the caller sets no optional field. A capped probe would publish a key for an endpoint that
# refuses the uncapped request chat sends by default; the session's size and time budget bound it.
_PING = [{"role": "user", "content": "ping"}]
# WHY the same word: a fixed synthetic text, so a probe carries no caller data.
_PING_TEXT = "ping"
_FAILURE_STATES = {
    401: ApiKeyValidationState.INVALID,
    402: ApiKeyValidationState.NO_QUOTA,
    # WHY not INVALID: a 403 can be model-specific; it must not condemn the whole key.
    403: ApiKeyValidationState.PERMISSION_DENIED,
    429: ApiKeyValidationState.RATE_LIMITED,
}


def _probe(
    target: ChatTarget | ClassificationTarget,
) -> tuple[dict[str, Any], Callable[[str | None, bytes], object | None]]:
    """The probe request of the target's task, and the decoder dispatch reads its answer with."""
    if isinstance(target, ClassificationTarget):
        return classification_request(_PING_TEXT), partial(
            decode_scores, envelope=target.response_envelope
        )
    return chat_request(target, _PING), decode_completion


def _classify(
    response: BoundedJsonResponse,
    probe_model: str,
    decode: Callable[[str | None, bytes], object | None],
) -> ApiKeyValidationResult:
    if response.status_code == 200:
        ok = decode(response.content_type, response.body) is not None
        state = ApiKeyValidationState.VALID if ok else ApiKeyValidationState.UNAVAILABLE
        return ApiKeyValidationResult(state=state, stage=_READINESS, probe_model=probe_model)
    state = _FAILURE_STATES.get(response.status_code, ApiKeyValidationState.UNAVAILABLE)
    retry_after = (
        response.retry_after_seconds if state is ApiKeyValidationState.RATE_LIMITED else None
    )
    return ApiKeyValidationResult(
        state=state, stage=_READINESS, retry_after_seconds=retry_after, probe_model=probe_model
    )


class RemoteEndpointReadiness:
    def __init__(
        self, definition: EndpointDefinition, *, transport: httpx.AsyncBaseTransport | None
    ) -> None:
        self._definition = definition
        self._transport = transport

    async def validate(self, api_key: str) -> ApiKeyValidationResult:
        definition = self._definition
        target = definition.target(definition.validation_target)
        if target is None:
            return ApiKeyValidationResult(ApiKeyValidationState.MISCONFIGURED)
        probe_model = definition.model_id(target)
        request, decode = _probe(target)
        async with ValidationHttpSession(transport=self._transport) as session:
            try:
                response = await session.request_json(
                    "POST",
                    definition.origin + target.request_path,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json_body=request,
                )
            except ApiKeyValidationTransportError:
                return ApiKeyValidationResult(
                    ApiKeyValidationState.UNAVAILABLE, stage=_READINESS, probe_model=probe_model
                )
        return _classify(response, probe_model, decode)
