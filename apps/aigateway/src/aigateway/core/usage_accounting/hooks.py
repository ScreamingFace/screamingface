"""The shared, app-lifetime LiteLLM transport observer (OME-303 U3).

FEATURE: per-observed-attempt usage accounting — the half that WATCHES local send admissions.

WHY one app-lifetime handler and not one per request (plan §4.1): a request-scoped
handler would throw away connection pooling on every call, and LiteLLM's own default
would otherwise pick a shared session the gateway cannot observe. One gateway-owned
handler keeps app-lifetime pooling, the default aiohttp transport, and production proxy
and redirect behaviour, while giving us a hook seam.

INVARIANT (plan §12 stop condition): the hooks are TOTAL. They resolve the caller's
collector from a ``ContextVar`` and can only ever mark it incomplete. An accounting bug
must never fail a provider response that has already been billed, and must never raise
an exception LiteLLM would treat as retryable — ``AsyncHTTPHandler.post()`` resends on
``ConnectError``/``RemoteProtocolError``, so a hook raising one would cause a SECOND
real observed provider attempt whose billing outcome is unknown.

INVARIANT (plan §4.2, verified against installed litellm 1.95.0): the hidden retry at
``http_handler.py:638`` calls ``self.create_client(timeout=…, event_hooks=…)`` and
passes NO ``ssl_verify``. The replacement client would therefore re-resolve TLS from
globals rather than inheriting this handler's setting. ``create_client`` is overridden
below so primary and replacement clients are verified identically — this is the ONLY
place that can be true for both.

AIDEV-NOTE: OpenRouter's ``dispatch_body["ssl_verify"] = True`` is IGNORED once a client
is injected — LiteLLM uses the client it was given. The TLS guarantee for an accounted
request lives here, in ``AccountingAsyncHTTPHandler``, not in that dispatch field.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from .signals import AccountingSignalTarget, active_collector

logger = logging.getLogger(__name__)

__all__ = ["AccountingAsyncHTTPHandler", "build_accounting_handler"]

# Reading an SSE body in a hook would consume the stream the caller is meant to receive.
# Streaming bypasses accounting before dispatch, so this is defence in depth against a
# provider that answers an accounted non-streaming request with an event stream.
_EVENT_STREAM = "text/event-stream"


MAX_RAW_EVIDENCE_BYTES = 256 * 1024


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        # INVARIANT: parser callbacks are accounting code. Their failures must reach
        # _bounded_json as ordinary invalid evidence, never escape the response hook.
        raise ValueError(f"invalid JSON number: {value}") from exc
    if not parsed.is_finite():
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


_ACCOUNTING_SENSITIVE_KEYS = frozenset(
    {
        "usage",
        "cost",
        "cost_details",
        "is_byok",
        "server_tool_use",
        "server_tool_use_details",
        "prompt_tokens",
        "input_tokens",
        "completion_tokens",
        "total_tokens",
        "output_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
        "error",
        "metadata",
        "error_type",
        "code",
        "openrouter_metadata",
        "pipeline",
        "attempts",
        "status",
        "cost_usd",
        "choices",
        "output",
        "content",
        "cache_creation",
        "service_tier",
    }
)


def _bounded_json_with_duplicates(
    payload: bytes,
) -> tuple[dict[str, Any] | None, frozenset[str]]:
    """Parse bounded JSON and return every repeated object-key name."""
    if len(payload) > MAX_RAW_EVIDENCE_BYTES:
        return None, frozenset({"*"})
    duplicate_keys: set[str] = set()

    def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, value in pairs:
            if key in parsed:
                duplicate_keys.add(key)
            parsed[key] = value
        return parsed

    try:
        parsed = json.loads(
            payload,
            parse_constant=_reject_non_finite,
            parse_float=_parse_decimal,
            object_pairs_hook=_object,
        )
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None, frozenset()
    return (parsed if isinstance(parsed, dict) else None), frozenset(duplicate_keys)


def _duplicate_can_change_accounting(key: str) -> bool:
    normalized = key.lower()
    return (
        key in _ACCOUNTING_SENSITIVE_KEYS
        or normalized.endswith(("_tokens", "_requests", "_details"))
        or any(word in normalized for word in ("cost", "price", "charge", "billing", "fee"))
    )


def _declared_body_exceeds_limit(value: str) -> bool:
    """Compare a decimal Content-Length without constructing an unbounded integer."""
    normalized = value.lstrip("0") or "0"
    limit = str(MAX_RAW_EVIDENCE_BYTES)
    return len(normalized) > len(limit) or (len(normalized) == len(limit) and normalized > limit)


def _mark_incomplete(collector: AccountingSignalTarget | None) -> None:
    """Best-effort "we missed something", which itself may never raise."""
    if collector is None:
        return
    try:
        collector.mark_incomplete()
    except BaseException:  # pragma: no cover - defence in depth
        logger.warning("usage accounting could not mark its collector incomplete")


def _bounded_json(payload: bytes) -> dict[str, Any] | None:
    """A bounded, object-shaped parse of a provider body, or ``None``.

    Only a JSON object is accepted, and only under the size cap: this value is held for
    the life of the request and handed to a provider mapper, so it is bounded before it
    is parsed rather than after.
    """
    parsed, duplicates = _bounded_json_with_duplicates(payload)
    return parsed if not duplicates else None


async def _read_body(response: httpx.Response) -> tuple[dict[str, Any] | None, bool, bool]:
    """``(raw_evidence, body_completed, evidence_complete)`` for a response.

    WHY reading here is safe and correct: the handler is injected ONLY for accounted
    non-streaming requests; streaming bypasses accounting before dispatch. Every response
    this hook sees is therefore non-streaming, and httpx would read it moments later
    anyway (``Client.send`` calls ``aread()`` when ``stream=False``). Reading it now is
    what makes ``latency_ms`` a completed-body measurement instead of time-to-headers,
    and it yields the RAW provider body that §3.5 requires mappers to prefer over
    LiteLLM's zero-filled ``Usage``.
    """
    if _EVENT_STREAM in response.headers.get("content-type", ""):
        return None, False, False
    declared = response.headers.get("content-length")
    if declared is not None and declared.isdigit() and _declared_body_exceeds_limit(declared):
        # Refuse before reading, not after: the cap is a memory bound, and a bound
        # enforced only once the bytes are already resident is not a bound.
        return None, False, False
    await response.aread()
    raw_evidence, duplicate_keys = _bounded_json_with_duplicates(response.content)
    if any(_duplicate_can_change_accounting(key) for key in duplicate_keys):
        raw_evidence = None
    return raw_evidence, True, not duplicate_keys


def _redirect_target(request: httpx.Request, response: httpx.Response) -> str | None:
    """The absolute URL this redirect will be followed to, or ``None`` if it cannot be.

    WHY this mirrors httpx's own ``Client._redirect_url`` step for step (verified against
    installed httpx 0.28.1): the collector folds the next admission only when it matches
    this string, so resolving it differently from the transport would split a legitimate
    redirect into two records. The response hook runs BEFORE ``_build_redirect_request``,
    so ``response.next_request`` is not yet set and there is nothing to read it from.

    ``None`` means httpx will not follow this ``Location`` either — it raises instead —
    so no hop is coming and the caller must not arm the fold.

    AIDEV-NOTE: both except arms are reachable and neither covers the other.
    ``httpx.InvalidURL`` derives from ``Exception``, NOT ``ValueError`` (non-printable
    ASCII in the URL raises it), while ``idna``'s ``IDNAError``/``InvalidCodepoint`` — a
    malformed punycode host such as ``http://xn--/`` — are ``ValueError`` subclasses that
    escape httpx's own ``except InvalidURL`` guard entirely.
    """
    try:
        url = httpx.URL(response.headers["Location"])
        # Absolute-form Location with no host (encode/httpx#771).
        if url.scheme and not url.host:
            url = url.copy_with(host=request.url.host)
        # Relative Location, as RFC 7231 allows.
        if url.is_relative_url:
            url = request.url.join(url)
        # Inherited fragment (RFC 7231 7.1.2).
        if request.url.fragment and not url.fragment:
            url = url.copy_with(fragment=request.url.fragment)
    except (httpx.InvalidURL, ValueError):
        return None
    return str(url)


async def _on_request(request: httpx.Request) -> None:
    """Record one local send-pipeline admission."""
    collector = active_collector()
    if collector is None:
        return
    try:
        collector.on_send_admitted(request)
    except asyncio.CancelledError:
        raise
    except BaseException:
        logger.warning("usage accounting request hook failed; marking the collector partial")
        _mark_incomplete(collector)


async def _on_response(response: httpx.Response) -> None:
    """Resolve the admission this response belongs to."""
    collector = active_collector()
    if collector is None:
        return
    try:
        request = response.request
        if response.has_redirect_location:
            # A redirect chain is ONE generation call. httpx fires the request hook
            # again for the next hop (``_client.py`` redirect loop), so the hop is
            # folded into this record instead of becoming a second observed attempt.
            target = _redirect_target(request, response)
            if target is None:
                # An unfollowable Location. httpx raises ``RemoteProtocolError`` here,
                # which ``AsyncHTTPHandler.post`` resends once — so the next admission is
                # a SECOND real observed attempt, not a hop. Leaving the fold unarmed is
                # what lets it become its own record.
                _mark_incomplete(collector)
                return
            collector.on_redirect_observed(request, target=target)
            return
    except asyncio.CancelledError:
        raise
    except BaseException:
        logger.warning("usage accounting response hook failed; marking the collector partial")
        _mark_incomplete(collector)
        return

    try:
        raw_evidence, body_completed, evidence_complete = await _read_body(response)
    except asyncio.CancelledError:
        # INVARIANT: cancellation is NOT an accounting failure — it is the caller going
        # away. Swallowing it here would let httpx continue a response/body path the
        # client no longer wants, turning an accounting hook into work after cancellation.
        # It is also not a type LiteLLM retries, so re-raising cannot cause a resend.
        raise
    except BaseException:
        # INVARIANT: accounting is an observer. Its own errors are swallowed below, but
        # a provider/transport failure raised while reading the body is the caller's
        # original failure path; hiding it turns a real timeout into ``StreamConsumed``.
        logger.warning("usage accounting body read failed; preserving provider error")
        _mark_incomplete(collector)
        raise

    try:
        collector.on_response_completed(
            request,
            status=response.status_code,
            raw_evidence=raw_evidence,
            body_completed=body_completed,
            evidence_complete=evidence_complete,
        )
    except asyncio.CancelledError:
        raise
    except BaseException:
        logger.warning("usage accounting response hook failed; marking the collector partial")
        _mark_incomplete(collector)


def accounting_event_hooks() -> dict[str, list[Callable[..., Any]]]:
    """The hook pair installed on every client this handler owns."""
    return {"request": [_on_request], "response": [_on_response]}


class AccountingAsyncHTTPHandler(AsyncHTTPHandler):
    """A LiteLLM async handler whose clients report every send to the active collector.

    INVARIANT: TLS verification is pinned on the primary client AND on any replacement
    client LiteLLM builds during its hidden retry — see the module docstring.

    INVARIANT: nothing about the transport is otherwise overridden. No forced
    ``httpx.AsyncHTTPTransport``, no HTTP/1 pin, no ``follow_redirects=False``. The base
    class's default aiohttp transport, proxy handling and redirect behaviour are exactly
    what production already uses; changing any of them is a plan §12 stop condition.
    """

    def __init__(
        self,
        *,
        ssl_verify: bool | str = True,
        timeout: float | httpx.Timeout | None = None,
    ) -> None:
        # Set BEFORE super().__init__: the base constructor calls self.create_client(),
        # which is overridden below and reads this attribute.
        self._pinned_ssl_verify = ssl_verify
        self._pinned_event_hooks = accounting_event_hooks()
        super().__init__(
            timeout=timeout,
            event_hooks=self._pinned_event_hooks,
            ssl_verify=ssl_verify,
        )

    def create_client(
        self,
        timeout: float | httpx.Timeout | None,
        event_hooks: Mapping[str, list[Callable[..., Any]]] | None,
        ssl_verify: Any = None,
        shared_session: Any = None,
    ) -> httpx.AsyncClient:
        """Build a client that always carries this gateway's TLS setting and hooks.

        LiteLLM's retry path calls this with neither ``ssl_verify`` nor a guarantee about
        ``event_hooks``; supplying both here is what makes the replacement client
        indistinguishable from the primary one for security and for accounting.
        """
        return super().create_client(
            timeout=timeout,
            event_hooks=event_hooks if event_hooks else self._pinned_event_hooks,
            ssl_verify=self._pinned_ssl_verify if ssl_verify is None else ssl_verify,
            shared_session=shared_session,
        )


def build_accounting_handler() -> AccountingAsyncHTTPHandler:
    """Construct the app-lifetime handler. Closed in the lifespan shutdown path."""
    return AccountingAsyncHTTPHandler(ssl_verify=True)
