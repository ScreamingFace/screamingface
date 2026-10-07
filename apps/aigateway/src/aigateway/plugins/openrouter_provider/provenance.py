"""LiteLLM-1.87.0 error provenance for the OpenRouter adapter (OME-428).

# WHY: LiteLLM 1.87.0 does NOT return a ``ModelResponse`` when a nominal HTTP-200
# body carries a meaningful top-level ``error`` — it RAISES while *converting*
# the body (``RateLimitError``/``ServiceUnavailableError``/``APIError``/
# ``AuthenticationError``/``BadRequestError``, keyed by status). That error came
# from an already-returned, potentially billed upstream call, so it is non-retryable
# exactly like an error found by scanning a returned payload — yet the plugin's
# post-return ``_find_embedded_error`` scanner never sees it because no payload
# is returned. A genuine transport failure raises the SAME outer LiteLLM type
# with the SAME outer status, so classification by type/status alone is unsafe.
# This module isolates the LiteLLM-internal signals that positively distinguish
# a converter-origin raise from a real transport failure.
#
# INVARIANT: these are LiteLLM 1.87.0 internals, not a public contract. The shape
# is pinned by tests/unit/openrouter/test_openrouter_toplevel_conversion_retry.py
# ::test_litellm_1_87_converter_raise_provenance_shape — a future LiteLLM that
# changes it fails that test LOUDLY rather than silently mis-routing errors.
# FAILS CLOSED (blocker F): the classifier has exactly three outcomes and only a
# PROVEN transport overload is retryable; a proven converter/body error AND an
# unprovable (ambiguous) error are both non-retryable and sanitized, so a future
# LiteLLM shape can never be silently retried into an amplified upstream call.
"""

from __future__ import annotations

import enum

import httpx

from aigateway.core.http_status import valid_http_error_status

# WHY (blocker D): litellm 1.87.0's converter defaults to HTTP 422 when a body
# error carries no derivable status. 422 is therefore a "no status" sentinel
# here, not a provider status — and it is not a documented OpenRouter error
# code — so a converter-context 422 (a status-less body OR an explicit code=422,
# indistinguishable at this boundary) folds to None -> the caller renders 502.
_NO_STATUS_SENTINEL = 422

_CONVERTER_OUTER_TYPES = frozenset(
    {
        "APIError",
        "AuthenticationError",
        "BadRequestError",
        "InternalServerError",
        "NotFoundError",
        "PermissionDeniedError",
        "RateLimitError",
        "ServiceUnavailableError",
        "Timeout",
    }
)


class ErrorProvenance(enum.Enum):
    """How a LiteLLM exception originated — the retry decision reads this."""

    TRANSPORT = "transport"  # proven real non-2xx wire failure -> retryable
    BODY = "body"  # proven converter-origin (HTTP-200 body) -> non-retryable
    AMBIGUOUS = "ambiguous"  # unprovable -> fail closed -> non-retryable


def _cause_chain(exc: BaseException) -> list[BaseException]:
    """The ``__cause__``/``__context__`` chain, excluding ``exc`` itself.

    Cycle-safe: an ``id``-seen set bounds a self-referential chain.
    """
    chain: list[BaseException] = []
    seen: set[int] = set()
    current = exc.__cause__ or exc.__context__
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def classify_provenance(exc: BaseException) -> ErrorProvenance:
    """Classify ``exc`` into exactly one of the three provenance outcomes.

    - TRANSPORT — the cause chain contains an ``httpx.HTTPError``.
    - BODY — a LiteLLM API error has the pinned single, exact bare-Exception
      converter context with ``status_code`` and ``message`` attributes.
    - AMBIGUOUS — every other shape, including headers without an httpx chain;
      unprovable, so the caller treats it as a non-retryable body error.
    """
    chain = _cause_chain(exc)
    if any(isinstance(link, httpx.HTTPError) for link in chain):
        return ErrorProvenance.TRANSPORT
    if (
        type(exc).__module__ == "litellm.exceptions"
        and type(exc).__name__ in _CONVERTER_OUTER_TYPES
        and len(chain) == 1
        and type(chain[0]) is Exception
        and {"status_code", "message"}.issubset(vars(chain[0]))
    ):
        return ErrorProvenance.BODY
    return ErrorProvenance.AMBIGUOUS


def is_http200_body_error(exc: BaseException) -> bool:
    """True when ``exc`` must be treated as a non-retryable converter/body error.

    True for BODY and AMBIGUOUS, False only for a PROVEN TRANSPORT failure —
    i.e. the fail-closed policy stated in the module docstring: unprovable
    provenance is non-retryable.
    """
    return classify_provenance(exc) is not ErrorProvenance.TRANSPORT


def _context_status(exc: BaseException) -> int | None:
    """The first validated HTTP error status on the converter-context chain.

    # WHY (blocker D): reads the chained (converter-context) exception's status,
    # NOT ``exc``'s outer status — a status-less body and an explicit code=400
    # share the SAME outer BadRequestError(400), but the context distinguishes
    # them (status-less -> 422 sentinel, explicit-400 -> 400).
    """
    if classify_provenance(exc) is not ErrorProvenance.BODY:
        return None
    return valid_http_error_status(vars(_cause_chain(exc)[0]).get("status_code"))


def converter_error_status(exc: BaseException) -> int | None:
    """A validated client-facing status for a converter-origin exception, else
    ``None`` (the caller maps ``None`` to a safe 502).

    Reads the converter-CONTEXT status and folds the 422 "no derivable status"
    sentinel to ``None`` (blocker D). Distinguishable explicit statuses
    (400/402/429/500/503) are preserved; a malformed/absent status degrades to
    502 rather than crashing or emitting an invalid status.
    """
    status = _context_status(exc)
    if status == _NO_STATUS_SENTINEL:
        return None
    return status


def converter_error_message(exc: BaseException) -> str | None:
    """The provider `error.message` litellm copied onto a converter-origin context, else ``None``.

    OME-1136: litellm 1.87's converter keeps ONLY `str(error["message"])` (default "Error in
    response object") on the chained bare Exception — `metadata.raw` does not survive it. The
    text is un-sanitized; the caller renders it only through `core.provider_error_text`.
    """
    if classify_provenance(exc) is not ErrorProvenance.BODY:
        return None
    message = vars(_cause_chain(exc)[0]).get("message")
    return message if isinstance(message, str) else None
