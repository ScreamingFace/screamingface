"""The outbound OpenRouter chat dispatch.

FEATURE: a non-streaming OpenRouter completion whose failures are sanitized before
anything reaches the caller.

Split out of ``plugin.py`` (OME-1026 adversarial B6) because this is the one impure
edge of the plugin — it imports LiteLLM, inspects process-global state, and maps
provider failures — while the plugin class around it is a thin port adapter. The
plugin's ``chat_completion`` delegates here and adds nothing.
"""

from __future__ import annotations

from typing import Any, cast

from .dispatch_errors import (
    _embedded_error_exception,
    _response_conversion_exception,
    _unsafe_litellm_state_error,
)
from .litellm_controls import _has_unsafe_litellm_global_state
from .provenance import converter_error_status, is_http200_body_error
from .response_errors import _find_embedded_error


async def dispatch_openrouter_chat(body: dict[str, Any]) -> Any:
    """Dispatch ``body`` through LiteLLM and return the dumped payload."""
    import litellm

    # INVARIANT: process-global LiteLLM routing and callbacks must never
    # receive or redirect an account-scoped OpenRouter credential.
    if _has_unsafe_litellm_global_state(litellm, body.get("model")):
        raise _unsafe_litellm_state_error()

    dispatch_body = dict(body)
    # AIDEV-NOTE (OME-303 §4.2): this field is IGNORED whenever the gateway injects
    # its own client — LiteLLM uses the client it was given, and that client's TLS
    # was fixed when it was built. For an accounted request the active TLS guarantee
    # is ``core.usage_accounting.hooks.AccountingAsyncHTTPHandler``, which pins
    # verification on its primary AND on the replacement client litellm builds
    # during its hidden retry. This line still governs the un-accounted path.
    dispatch_body["ssl_verify"] = True
    dispatch_body["caching"] = False
    dispatch_body["cache"] = {"no-cache": True, "no-store": True}
    # OME-303 §4.3: pin the gateway-owned OUTER retry cardinality so the accounting
    # contract's observed-attempt count cannot be changed by a process-global default.
    dispatch_body["num_retries"] = 0
    dispatch_body["max_retries"] = 0

    # cast: acompletion's static type is a ModelResponse|CustomStreamWrapper
    # union, but D5 guarantees non-streaming here (stream rejected at the
    # route before dispatch), so model_dump is always present.
    try:
        response = cast("Any", await litellm.acompletion(**dispatch_body))
    except Exception as exc:
        # WHY (FINDING A): litellm 1.87.0 RAISES while converting a nominal
        # HTTP-200 body that carries a meaningful top-level error — it never
        # returns a payload for _find_embedded_error to scan below. Such an
        # error came from an already-returned, potentially billed upstream call, so
        # route it through the SAME sanitizer as a scanned embedded error:
        # non-retryable, status sanitized, raw provider text discarded.
        # INVARIANT: a genuine transport failure is re-raised unchanged so
        # the shared overload-retry loop (core.retry) still applies to it.
        if is_http200_body_error(exc):
            raise _embedded_error_exception(converter_error_status(exc)) from exc
        raise
    try:
        payload: Any = response.model_dump() if hasattr(response, "model_dump") else response
    except Exception:
        raise _response_conversion_exception() from None
    if isinstance(payload, dict):
        found, status = _find_embedded_error(payload)
        if found:
            # A 401 here flows through the route's dispatch-failure path
            # and marks only the selected connection (D9 local).
            raise _embedded_error_exception(status)
    # Return the dumped dict so native usage/cost/generation metadata
    # reaches the caller byte-for-byte (D10 — URL4 per-leaf telemetry).
    return payload
