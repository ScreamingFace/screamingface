"""Key readiness for one configured endpoint: a bounded synthetic chat request.

# INVARIANT: the probe goes to the instance's own origin and validation target with exactly the
# supplied key; only a well-formed success is VALID, and only at READINESS, so the shared service's
# publication rule is satisfied by a real round trip and nothing less.
"""

from __future__ import annotations

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

from .completion import decode_completion
from .definitions import EndpointDefinition
from .request import chat_request

_READINESS = ApiKeyValidationStage.READINESS
# WHY no `max_tokens` and no `stream`: the probe is exactly the request an ordinary chat sends when
# the caller sets no optional field. A capped probe would publish a key for an endpoint that
# refuses the uncapped request chat sends by default; the session's size and time budget bound it.
_PING = [{"role": "user", "content": "ping"}]
_FAILURE_STATES = {
    401: ApiKeyValidationState.INVALID,
    402: ApiKeyValidationState.NO_QUOTA,
    # WHY not INVALID: a 403 can be model-specific; it must not condemn the whole key.
    403: ApiKeyValidationState.PERMISSION_DENIED,
    429: ApiKeyValidationState.RATE_LIMITED,
}


def _classify(response: BoundedJsonResponse, probe_model: str) -> ApiKeyValidationResult:
    if response.status_code == 200:
        ok = decode_completion(response.content_type, response.body) is not None
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
        async with ValidationHttpSession(transport=self._transport) as session:
            try:
                response = await session.request_json(
                    "POST",
                    definition.origin + target.request_path,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json_body=chat_request(target, _PING),
                )
            except ApiKeyValidationTransportError:
                return ApiKeyValidationResult(
                    ApiKeyValidationState.UNAVAILABLE, stage=_READINESS, probe_model=probe_model
                )
        return _classify(response, probe_model)
