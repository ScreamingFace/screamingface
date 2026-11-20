"""The gateway round trip: one logical model call to the AI gateway, below any tool loop.

FEATURE: OpenAI-compatible chat endpoint (docs/spec/2026-11-17-engine-openai-chat-endpoint,
prd/gateway-transport.md). The existing model endpoint (`world/connector.py`) and the chat
final-step endpoint must talk to the gateway in the same way, so everything one call needs lives
here: identity and time-out headers, capture / replay / normal send, the cache policy and its
read-back, both retry layers and the deadline, the status-to-error mapping, and the cost, usage
and cache-status reports.

INVARIANT: this module never imports `world.connector`. The connector imports this MODULE
(`gateway_transport.x`), never its names, so a test that still patches a moved name on
`connector` fails with an AttributeError instead of patching nothing.

AIDEV-NOTE: `round_trip` is the public entry (one observed, logged call). The other names keep
their leading underscore: they are private to the `world` package, and `connector.py` and
`classification.py` read them as attributes of this module.

AIDEV-NOTE: a name that BOTH modules import (`httpx`, `current_scope`, `record_operation_call`,
`job_env`, `math`, `provider_of`) is one binding in each module. A test that replaces such a
name on `connector` does not reach the code here; patch it on this module.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from screamingface_engine import job_env
from screamingface_engine.benchmarks.case_context import (
    current_capture_case,
    current_case_key,
)
from screamingface_engine.benchmarks.failure_classes import logprobs_unsupported
from screamingface_engine.candidate_scope import in_candidate_invocation
from screamingface_engine.capture_outcomes import (
    CAPTURE_FIELD,
    FROZEN_COPY_HEADER,
    REPLAY_FIELD,
    REPLAY_MISS,
    REPLAY_UNAVAILABLE,
    CaptureOutcome,
    CaptureTally,
    Status,
    call_key_headers,
    current_capture_tally,
    record_capture_outcome,
    replay_chat_path,
    replay_refusal_code,
    request_digest,
)
from screamingface_engine.error_text import ENGINE_RESERVED_CODES
from screamingface_engine.grading_call_scope import grading_call_log_suffix
from screamingface_engine.observations import ModelCall, current_model_call
from screamingface_engine.operation_accounting import (
    OperationAccounting,
    ReplyLogprobs,
    SignalAccounting,
    combine_operation_accounting,
    combine_signal_accounting,
)
from screamingface_engine.operation_calls import record_operation_call
from screamingface_engine.request_scope import RequestScope, RequestScopeError, current_scope
from screamingface_engine.trace_scope import current_traceparent
from screamingface_engine.world import candidate_call_retry
from screamingface_engine.world.accounting import (
    CallAccounting,
    avoided_usd_for_outcome,
    read_aigw,
    retained_operation_accounting,
    signal_accounting_from_aigw,
)
from screamingface_engine.world.attachment_parts import (
    INTENT_ERROR,
    GatewayContentPartRefusal,
    intent_error_for,
)
from screamingface_engine.world.cache import with_cache_policy
from screamingface_engine.world.cache_readback import (
    CacheOutcome,
    read_cache_outcome,
    requires_revalidation,
)
from screamingface_engine.world.capture_proof import replay_failure_code
from screamingface_engine.world.config import provider_of
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.model_response import (
    Choice,
    parse_choice,
    raise_if_unusable,
)
from screamingface_engine.world.reply_logprobs import reply_logprobs
from screamingface_engine.world.reply_origin import record_reply_origin, round_trip_origin
from screamingface_engine.world.streamed_json import streamed_json_body
from url4.core.errors import ResolutionError
from url4.observe import current_log_sink, current_response_sink, current_usage_sink
from url4.streaming.protocol import CachePolicy

# WHY the pre-refactor name, not `__name__` (FX-19): operators filter the runtime log by logger
# name. This code moved from `runner/connector.py` to `world/connector.py` and then here; the
# name keeps every model-call lifecycle line byte-identical to `main`. It is the SAME logger
# object that `world/connector.py` holds.
logger = logging.getLogger("screamingface_engine.runner.connector")

_COMPLETIONS_PATH = "/v1/chat/completions"
_CAPTURE_STATUSES: dict[str, Status] = {
    "stored": "stored",
    "failed": "failed",
    "refused": "refused",
}
"""The statuses the gateway reports. A LOOKUP, so a word outside the vocabulary reads as absent
(`missing`), never as a guess."""
_REPLAYED = CacheOutcome(status="hit", reason=None, key=None, age_s=None)
"""How a replayed answer is accounted: like a cache hit, unretried. It cost nothing — the gateway
sets the body's call cost to 0 — and a replay never pays a provider, so no transport retry of it
can have been billed."""

# Transport-retry policy for the aigateway hop (OME-1016). A transport failure
# (connection reset, read error, timeout) is transient by nature, so the connector
# retries it with exponential backoff + jitter before surfacing a retryable
# ResolutionError. Module-level so tests can zero them; the benchmark's own ``retry=``
# (url4) remains a second layer for HTTP-status failures and for a sustained outage.
_GATEWAY_RESPONSE_MARGIN_S = 5.0
_TRANSPORT_RETRIES = 1  # one retry → two attempts; url4's retry= adds more if needed
# INVARIANT (OME-1220): the transport failures that prove no request byte left the Engine.
# httpcore raises these only while opening the connection (TCP connect, TLS handshake) or while
# waiting for a pooled one; the request is written strictly after. A retry that follows one of
# them does not set the `possibly_billed` fact. Since OME-1687 that fact changes no price — a call
# is priced from its successful request whatever preceded it. Every other failure is ambiguous:
# httpcore swallows a mid-request `WriteError` and surfaces the outcome as a read-side error,
# so only "connect phase vs the rest" separates sent from unsent, never "write vs read".
# AIDEV-NOTE: `_post_attempt`'s own `asyncio.timeout` raises `ReadTimeout` whatever the phase —
# deliberately conservative: it may report a never-sent request as possibly billed, never the
# reverse.
_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_TRANSPORT_BACKOFF_BASE_S = 0.5
_TRANSPORT_BACKOFF_MAX_S = 8.0
_TRANSPORT_BACKOFF_JITTER_S = 0.25

# How long a gateway round trip may sit quiet before the log says so (OME-1126). Long
# enough that ordinary reasoning turns stay silent; short enough that a stalled provider
# endpoint is visible while it stalls rather than only after the run dies. Each later
# beat waits twice as long (capped) so a 20-minute reasoning marathon costs ~5 lines,
# not 20 — the log stays legible while still proving the call is alive.
_IN_FLIGHT_HEARTBEAT_S = 60.0
_IN_FLIGHT_HEARTBEAT_MAX_S = 600.0

# The aigateway code for OpenRouter's refusal of a request whose model has no endpoint for every
# requested parameter (E4b part 3 unit 1, C4b). Only with HTTP 404: a 400 with this code is the
# gateway's own parameter-catalog refusal, which keeps its mapping.
_PARAMETER_REFUSAL_CODE = "unsupported_parameters"


async def _in_flight_heartbeat(model_id: str, started: float) -> None:
    """Announce a still-running round trip until the caller cancels this task."""
    wait = _IN_FLIGHT_HEARTBEAT_S
    while True:
        await asyncio.sleep(wait)
        logger.info(
            "model call in flight model=%s elapsed=%.0fs%s",
            model_id,
            time.monotonic() - started,
            grading_call_log_suffix(),
        )
        wait = min(wait * 2, _IN_FLIGHT_HEARTBEAT_MAX_S)


async def round_trip(
    http_client: httpx.AsyncClient,
    *,
    real_model_id: str,
    headers: dict[str, str],
    body: dict[str, object],
    cache: CachePolicy,
    max_tokens: object | None,
    operation_accounting: list[OperationAccounting | None],
    replay_frozen_copy: str | None = None,
    signal_accounting: list[SignalAccounting] | None = None,
    reply_logprobs: list[ReplyLogprobs | None] | None = None,
) -> Choice:
    # FEATURE: OME-1161 exposes execution facts to optional, node-associated observers.
    async with ModelCall(real_model_id, current_log_sink()) as observation:
        return await _observed_round_trip(
            http_client,
            real_model_id=real_model_id,
            headers=headers,
            body=body,
            cache=cache,
            max_tokens=max_tokens,
            operation_accounting=operation_accounting,
            signal_accounting=signal_accounting,
            observation=observation,
            replay_frozen_copy=replay_frozen_copy,
            reply_logprobs=reply_logprobs,
        )


async def _observed_round_trip(
    http_client: httpx.AsyncClient,
    *,
    real_model_id: str,
    headers: dict[str, str],
    body: dict[str, object],
    cache: CachePolicy,
    max_tokens: object | None,
    operation_accounting: list[OperationAccounting | None],
    observation: ModelCall,
    replay_frozen_copy: str | None,
    signal_accounting: list[SignalAccounting] | None = None,
    reply_logprobs: list[ReplyLogprobs | None] | None = None,
) -> Choice:
    """One gateway round trip with its lifecycle in the log.

    FEATURE: model-call lifecycle observability (OME-1126). One line per round trip's
    terminal outcome and a heartbeat while it is in flight, so the runtime log can tell
    "still thinking" from "dead" — model id, duration, and finish_reason/error code
    ONLY, never prompt or response text (OME-990).
    """
    started = time.monotonic()
    heartbeat = asyncio.create_task(_in_flight_heartbeat(real_model_id, started))
    try:
        resp, outcome = await _recorded_completion(
            http_client,
            headers=headers,
            body=body,
            cache=cache,
            replay_frozen_copy=replay_frozen_copy,
        )
        data = _json_or_raise(resp)
        # FEATURE (spec 2026-10-16-judge-redraw-live-only): tell a watching judge step whether
        # this reply is live or a recording (cache hit, frozen-copy replay); a recording is
        # never redrawn. Recorded only once the gateway answered with a body.
        record_reply_origin(round_trip_origin(outcome, replay_frozen_copy))
        _retain_reply_facts(
            data,
            body,
            outcome,
            real_model_id=real_model_id,
            operation_accounting=operation_accounting,
            signal_accounting=signal_accounting,
            reply_logprobs=reply_logprobs,
        )
        choice = parse_choice(data)
        # INVARIANT: report BEFORE classifying. A refused turn is the case a reviewer most
        # needs to audit, and raising first would lose exactly the event OME-679 exists to
        # capture.
        # INVARIANT: a replayed answer claims NO saving. It is served from the cache's accounting
        # path at $0, but the copy answered; nothing was avoided, and the captured body's `_aigw`
        # may still carry the saved-cost reference of the original run's own cache hit.
        _report_response(
            choice, outcome, None if replay_frozen_copy is not None else data.get("_aigw")
        )
        _raise_if_unusable_with_accounting(
            choice,
            max_tokens=max_tokens,
            accounting=operation_accounting,
            signal_accounting=signal_accounting,
        )
    except (RunnerRequestError, ResolutionError) as exc:
        observation.failed(exc.code)
        logger.warning(
            "model call failed model=%s duration=%.1fs code=%s%s",
            real_model_id,
            time.monotonic() - started,
            exc.code,
            grading_call_log_suffix(),
        )
        raise
    except asyncio.CancelledError:
        # WHY (FX-18): a sync timeout or a dropped caller cancels the call. Without this line the
        # log shows a dispatch and then nothing. It is not a failure of the call, so the
        # observation is not told `failed`; the observer sees the cancellation on scope exit.
        logger.warning(
            "model call cancelled model=%s duration=%.1fs",
            real_model_id,
            time.monotonic() - started,
        )
        raise
    finally:
        # INVARIANT: return or cancellation leaves no operator heartbeat task behind.
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
    logger.info(
        "model call completed model=%s duration=%.1fs finish_reason=%s%s",
        real_model_id,
        time.monotonic() - started,
        choice.finish_reason,
        # WHY the tag (OME-1240): a judge may share the candidate's model id; the
        # grading scope is the only thing that tells their round trips apart.
        grading_call_log_suffix(),
    )
    observation.completed(choice.finish_reason)
    return choice


def _report_response(choice: Choice, cache: CacheOutcome, aigw: object = None) -> None:
    """Report how one model round trip ended — whether the gateway served it from its response
    cache, and what that hit avoided — onto the currently-resolving node's span.

    Null-safe exactly like `_report_usage`: outside a run, or with no observer attached, the
    sink is absent and this is a no-op.

    INVARIANT: reported BESIDE `_report_usage`, for the same call, or the two disagree. A hit
    costs nothing upstream while `_report_usage` bills it as a fresh call, so a span that
    carries the tokens without the outcome states a cost that was never paid — an error in the
    direction that hides savings, and therefore one nobody reports.

    INVARIANT: the saved cost is derived from `aigw` — the accounting of the round trip whose
    outcome `cache` describes — and never from a discarded one. `_fetch_completion` may refuse a
    hit and re-issue the call, returning the SECOND trip's outcome; deriving from that same
    returned pair is what keeps the discarded hit's cost out of the run total (PRD test 17).

    FEATURE: cost of intelligence (OME-1687). A hit whose round trip was RETRIED claims its saving
    like any hit. The leaderboard's reproduction cost is spend plus saving, and in a perfect world
    — every model answering on the first attempt — the hit replaces the original call, whose cost
    the reference holds. A retry is an infrastructure event and changes no price.
    """
    sink = current_response_sink()
    if sink is None:
        return
    saved = avoided_usd_for_outcome(aigw, cache)
    sink(
        finish_reason=choice.finish_reason,
        refusal=choice.refusal,
        cache_status=cache.status,
        cache_reason=cache.reason,
        cache_saved_cost_usd=saved.usd,
        cache_saved_cost_provenance=saved.provenance,
    )


def _token_count(*candidates: object) -> int:
    """The first candidate that is a real non-negative count, else 0.

    `bool` is refused explicitly: it is an `int` subclass, so a stray `True` would count as one
    token. Zero is the last resort because the wire's `TokenUsage` has no way to say "unknown".
    """
    for candidate in candidates:
        if not isinstance(candidate, bool) and isinstance(candidate, int) and candidate >= 0:
            return candidate
    return 0


_MAX_TOKEN_COUNT = 2**53 - 1
"""The gateway's own bound on a token count (`aigateway.core.usage_modalities`)."""


def _image_and_file_tokens(usage: object) -> int | None:
    """The image/file subset of the prompt, as aigateway states it, or `None` for unknown.

    FEATURE: image/file token accounting (OME-1744). aigateway writes it at
    `usage.prompt_tokens_details.image_and_file_tokens` — under `usage`, NOT under `_aigw` — so this
    reads `usage` even when `_aigw` is authoritative for every other class.

    INVARIANT: anything that is not a bounded non-negative int is unknown (`None`), never 0 — unlike
    `_token_count`, whose zero fallback predates any wire spelling of "unknown". A known 0 passes
    through: the provider broke the input down and it held no media.
    """
    details = usage.get("prompt_tokens_details") if isinstance(usage, dict) else None
    value = details.get("image_and_file_tokens") if isinstance(details, dict) else None
    # WHY `type(...) is int`: bool is an int subclass, and `True` is not a token count.
    if type(value) is not int or not 0 <= value <= _MAX_TOKEN_COUNT:
        return None
    return value


def _report_served_from_cache(model: str, call: CallAccounting | None) -> None:
    """Report a cache hit: zero tokens consumed, and priced at zero.

    WHY zero rather than the numbers the response carries: a hit replays a STORED response, whose
    body still contains the original call's `usage`. aigateway says so explicitly — it labels the
    cache reference `incurred_in_current_request: false` and publishes no attempts — and
    `accounting.usd_from_aigw` already honours that boundary by refusing to price the reference.
    Counting the same reference's tokens as freshly consumed treats one piece of evidence two
    opposite ways, and inflates every consumption figure a cache-heavy run reports.

    WHY explicit zeros rather than `None`: `None` means "the gateway did not report it". Here the
    gateway reported something definite — nothing was consumed — and a run total must be able to
    add that in rather than treat it as a gap.

    INVARIANT: a hit stays `Decimal("0")` and never `None`, retried or not. Zero is a real claim
    about a real saving; a dash would hide it. `usd_from_aigw` derives it from the SAME hit, so
    the two agree.

    FEATURE: cost of intelligence (OME-1687). A transport retry before the hit changes nothing
    here. The price is the successful request's, and a hit's successful request cost nothing.
    AIDEV-NOTE: this reverses OME-1220, which made a retried hit (and miss) unpriced to protect
    the actual spend. The owner chose the model price instead (2026-10-20). `CacheOutcome.retried`
    is still recorded; no price reads it.

    AIDEV-NOTE: hit-ness is decided by the caller from the published `CacheOutcome` (the response
    headers), NOT from `_aigw`. That is deliberate — an older gateway emits the header and no
    accounting block at all, and it keeps these token counts consistent with the `cache_status`
    published beside them on the same span.
    """
    sink = current_usage_sink()
    if sink is None:
        return
    sink(
        provider=call.provider if call is not None and call.provider else provider_of(model),
        model=model,
        input_tokens=0,
        output_tokens=0,
        response_model=call.response_model if call is not None else None,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        cost_usd=_hit_cost(call),
        # WHY unknown and not the zero its siblings get (owner decision, OME-1744): the stored
        # body's breakdown is the ORIGINAL call's, so a hit makes no claim about this class.
        image_and_file_tokens=None,
    )


def _hit_cost(call: CallAccounting | None) -> Decimal:
    """A hit's price: the gateway's own figure, or an explicit zero when it reported no
    accounting at all. Never `None` — see the invariant above."""
    return call.cost_usd if call is not None and call.cost_usd is not None else Decimal(0)


def _report_usage(
    model: str, usage: dict | None, aigw: object = None, cache: CacheOutcome | None = None
) -> None:
    """Report one gateway round trip's token and cost evidence onto the calling node's span.

    FEATURE: per-run cost reporting (OME-849). Prefers aigateway's `_aigw` accounting, which states
    the provider and the served model authoritatively and carries the cache/reasoning token classes
    plus a provider-authored cost. Falls back to the provider's own `usage` object when no
    accounting is present — the pre-`_aigw` behaviour, which an older gateway still produces.

    INVARIANT: reported per ROUND TRIP, not per turn. A tool loop is several gateway calls against
    one span and each carries its own accounting, so the span accumulates them (see
    `executor._RunState._fold_usage`).

    INVARIANT (OME-868): a published `cache_status` of `hit` and a non-zero token count are a
    CONTRADICTION, and this is the seam that keeps them consistent. A hit is served from the
    gateway's store, so the provider consumed nothing this request — see
    `_report_served_from_cache`.

    WHY a reported 0 is not a measured zero (OME-1770): when neither `_aigw` nor `usage` states a
    count, `_token_count` falls back to 0, because the wire's `TokenUsage` cannot say "unknown". A
    configured endpoint may omit `usage`, so its 0 tokens mean "not stated", never "nothing spent".
    A truthful unknown is the later accounting integration's job, not this seam's.
    """
    sink = current_usage_sink()
    if sink is None:
        return
    call = read_aigw(aigw)
    if call is None and usage is None:
        return
    if cache is not None and cache.status == "hit":
        _report_served_from_cache(model, call)
        return
    reported = usage or {}
    sink(
        # INVARIANT: `_aigw` is authoritative for the provider. `provider_of` is the shared catalog
        # rule — an unprefixed id is Anthropic's — and it is the ONLY source when a cache hit means
        # there are no attempts to read a provider off. Never re-derive that rule locally.
        provider=call.provider if call is not None and call.provider else provider_of(model),
        model=model,
        # A cache hit carries no attempts, so its token counts come from the cached provider body.
        input_tokens=_token_count(
            call.input_tokens if call is not None else None, reported.get("prompt_tokens")
        ),
        output_tokens=_token_count(
            call.output_tokens if call is not None else None, reported.get("completion_tokens")
        ),
        response_model=call.response_model if call is not None else None,
        cache_read_tokens=call.cache_read_tokens if call is not None else None,
        cache_creation_tokens=call.cache_creation_tokens if call is not None else None,
        reasoning_tokens=call.reasoning_tokens if call is not None else None,
        # FEATURE: cost of intelligence (OME-1687). The price is the successful request's, so a
        # transport retry before it changes nothing. `None` when there is no `_aigw` to read, when
        # the successful request's own cost is unknown (R3), and for an older gateway's non-complete
        # status (`usd_from_aigw`).
        cost_usd=None if call is None else call.cost_usd,
        image_and_file_tokens=_image_and_file_tokens(reported),
    )


def _report_unpriced_call(provider: str, model: str) -> None:
    """Report one dispatched Gateway call whose cost the Engine cannot know.

    FEATURE: hosted BYOM, Unit 3 (spec E8 as amended, OME-1795). A classification answer carries
    no price, and a call that reports nothing is simply absent from the run total, so a run that
    also made a priced chat call would publish a priced total without it. This one record latches
    the total unpriced (`executor._RunState._fold_usage`).

    INVARIANT: aggregate honesty only, not Taxonomy accounting: no price and no token measurement.
    WHY the two zero counts: the sink requires them and the wire's `TokenUsage` cannot say
    "unknown" (OME-1770, as in `_report_usage`), so they are not measured values. The optional
    token classes are left unset.
    """
    sink = current_usage_sink()
    if sink is None:
        return
    sink(
        provider=provider,
        model=model,
        input_tokens=0,
        output_tokens=0,
        cost_usd=None,
        image_and_file_tokens=None,
    )


async def _post_completion(
    http_client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    body: dict,
    path: str = _COMPLETIONS_PATH,
    probe: _CaptureProbe | None = None,
) -> tuple[httpx.Response, bool]:
    """Use one bounded retry policy for transport failures and explicit queue expiry.

    Other HTTP errors are retried by `_post_answered` for a Candidate call (OME-1872), and
    otherwise remain owned by the caller's declared URL4 retry policy.
    The caller deadline bounds each attempt and must fit a full attempt before retry.
    The bool marks a retry that followed a failure which may have reached the gateway, and so
    may have been billed. A known queue refusal never dispatched and does not set it; neither
    does a connect-phase failure (`_NEVER_SENT`). AIDEV-NOTE (OME-1687): it is a recorded fact
    only — no price reads it, because the price is the successful request's.
    Independently, a capture ``probe`` learns every lost reply as it happens: capture ordering is
    ambiguous after a retry that followed a request which may have been sent. A connect-phase
    failure (`_NEVER_SENT`) is not a lost reply: no request byte left the Engine, so the gateway
    stored nothing for that try (OME-1775 R3).
    """
    deadline = _current_deadline()
    configured = _transport_budget(http_client, headers)
    last: httpx.TransportError | None = None
    possibly_billed = False
    for attempt in range(_TRANSPORT_RETRIES + 1):
        timeout = _attempt_timeout(deadline, configured, last)
        try:
            response = await _post_attempt(
                http_client, headers, body, deadline, configured, timeout, path=path
            )
        except httpx.TransportError as exc:
            last = exc
            if probe is not None and not isinstance(exc, _NEVER_SENT):
                # Told now, not at the answer: a call whose every attempt fails never gets one.
                # WHY: a connect-phase failure sent nothing, so it is no lost reply (OME-1775 R3).
                probe.lost_reply()
            possibly_billed = possibly_billed or not isinstance(exc, _NEVER_SENT)
            if isinstance(exc, httpx.TimeoutException) and _deadline_bound(timeout, configured):
                raise _deadline_exceeded(exc) from exc
            if attempt < _TRANSPORT_RETRIES:
                await _retry_transport(attempt, deadline, configured, exc)
            continue
        if _queue_timeout(response) and attempt < _TRANSPORT_RETRIES:
            if await _retry_queue(response, attempt, deadline, configured):
                continue
        return response, possibly_billed
    assert last is not None
    raise ResolutionError(
        f"aigateway request failed at the transport layer: {_transport_detail(last)}",
        code="aigateway_transport_error",
        permanent=False,
    ) from last


def _transport_budget(client: httpx.AsyncClient, headers: dict[str, str]) -> float | None:
    if "x-aigw-execution-timeout-s" not in headers:
        return client.timeout.read
    return (
        float(headers["x-aigw-execution-timeout-s"])
        + float(headers["x-aigw-queue-timeout-s"])
        + _GATEWAY_RESPONSE_MARGIN_S
    )


async def _post_attempt(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    body: dict,
    deadline: float | None,
    configured: float | None,
    timeout: float | None,
    *,
    path: str = _COMPLETIONS_PATH,
) -> httpx.Response:
    attempt_headers = dict(headers)
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _deadline_exceeded(None)
        attempt_headers["x-aigw-remaining-timeout-s"] = str(remaining)
    limit = configured if timeout is None else timeout
    # Queueing extends the read allowance, not connection/pool/write limits.
    transport_timeout = httpx.Timeout(client.timeout)
    transport_timeout.read = limit
    # FEATURE (OME-1545 review blocker 1): a body carrying a run's file is streamed from the one
    # shared ``data:`` URI, byte-identical to ``json=``, so concurrent calls never each hold a JSON
    # copy of it; any other body keeps ``json=`` exactly.
    streamed = streamed_json_body(body)
    try:
        # Also bound transports without HTTPX timeout enforcement and trickling replies.
        async with asyncio.timeout(limit):
            if streamed is not None:
                return await client.post(
                    path,
                    headers={**attempt_headers, **streamed[0]},
                    content=streamed[1],
                    timeout=transport_timeout,
                )
            return await client.post(
                path,
                headers=attempt_headers,
                json=body,
                timeout=transport_timeout,
            )
    except TimeoutError as exc:
        raise httpx.ReadTimeout("Gateway transport budget expired") from exc


async def _retry_transport(
    attempt: int, deadline: float | None, configured: float | None, exc: httpx.TransportError
) -> None:
    delay = _transport_backoff(attempt)
    if deadline is not None and not _retry_fits(deadline, delay, configured):
        raise _deadline_exceeded(exc) from exc
    await _wait_to_retry(attempt, delay)
    if deadline is not None and not _retry_fits(deadline, 0, configured):
        raise _deadline_exceeded(exc) from exc


async def _retry_queue(
    response: httpx.Response, attempt: int, deadline: float | None, configured: float | None
) -> bool:
    delay = _queue_retry_delay(response, attempt)
    if deadline is not None and not _retry_fits(deadline, delay, configured):
        return False
    await _wait_to_retry(attempt, delay)
    # A delayed wakeup must not turn a full-budget retry into a partial attempt.
    # Preserve the known queue refusal when a retry no longer fits.
    return deadline is None or _retry_fits(deadline, 0, configured)


async def _wait_to_retry(attempt: int, delay: float) -> None:
    observation = current_model_call()
    if observation is not None:
        observation.retry(attempt=attempt + 2, delay_seconds=delay)
    await asyncio.sleep(delay)


def _queue_timeout(response: httpx.Response) -> bool:
    if response.status_code != 503:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("detail"), dict)
        and payload["detail"].get("code") == "provider_queue_timeout"
    )


def _queue_retry_delay(response: httpx.Response, attempt: int) -> float:
    # The Gateway emits delta-seconds. Invalid, nonfinite or negative values use
    # the existing backoff; valid values share its cap and cannot create a hot loop.
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        seconds = float("nan")
    if not math.isfinite(seconds) or seconds < 0:
        return _transport_backoff(attempt)
    return min(_TRANSPORT_BACKOFF_MAX_S, max(_TRANSPORT_BACKOFF_BASE_S, seconds))


def _current_deadline() -> float | None:
    """The bound request's deadline, or None when no request budget applies.

    WHY an unbound read means "no deadline" and does not raise: `_post_completion` worked with no
    scope bound before FX-1, and a missing deadline must keep it byte-identical. The loud AC5
    refusal stays where it matters — `_ModelEndpoint` reads the caller's identity through
    `current_scope()`, which still raises when nothing is bound.
    """
    try:
        return current_scope().deadline
    except RequestScopeError:
        return None


def _attempt_timeout(
    deadline: float | None, configured: float | None, last: httpx.TransportError | None
) -> float | None:
    """The next attempt's timeout: None (the client's own) with no deadline, else the time left
    capped by ``configured``.

    Raises:
        ResolutionError: ``aigateway_deadline_exceeded`` when no time is left for an attempt.
    """
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _deadline_exceeded(last)
    return remaining if configured is None else min(configured, remaining)


def _deadline_bound(timeout: float | None, configured: float | None) -> bool:
    """Whether an attempt ran under the time-left bound rather than the configured timeout."""
    return timeout is not None and (configured is None or timeout < configured)


def _deadline_exceeded(cause: httpx.TransportError | None) -> ResolutionError:
    """The transient refusal for a request whose budget ran out upstream (§2.2b)."""
    detail = _transport_detail(cause) if cause is not None else "no time left for an attempt"
    return ResolutionError(
        f"aigateway request ran out of the request budget: {detail}",
        code="aigateway_deadline_exceeded",
        permanent=False,
    )


def _retry_fits(deadline: float, delay: float, configured: float | None) -> bool:
    """Whether the backoff plus one full attempt still ends before ``deadline``.

    WHY the CONFIGURED timeout and not the time left: an attempt capped to the time left is the
    attempt the wrapper would cut off — billed and useless (NT-H1). With no configured read
    timeout, only the backoff itself has to fit.
    """
    return deadline - time.monotonic() >= delay + (configured or 0.0)


def _transport_backoff(attempt: int) -> float:
    """Exponential backoff plus jitter for the next transport retry.

    ``attempt`` is the zero-based index of the attempt that just failed, so the first
    retry waits ``base``, the second ``2*base``, capped at ``backoff_max_s``; jitter
    de-synchronises concurrent siblings that failed together.
    """
    delay = min(_TRANSPORT_BACKOFF_BASE_S * 2**attempt, _TRANSPORT_BACKOFF_MAX_S)
    return delay + random.uniform(0.0, _TRANSPORT_BACKOFF_JITTER_S)


def _transport_detail(exc: httpx.TransportError) -> str:
    """A stable one-line description of a transport failure, even when ``str()`` is empty.

    ``httpx.ReadError('')`` stringifies to an empty string; the class name alone is
    still actionable, and a non-empty message keeps ``_error_payload`` from falling
    back to ``repr(exc)``.
    """
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


async def _fetch_completion(
    http_client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    body: dict,
    cache: CachePolicy,
    probe: _CaptureProbe | None = None,
) -> tuple[httpx.Response, CacheOutcome]:
    """One chat-completions round trip under this run's cache policy, plus what the gateway
    reported about the cache — re-issued without the cache when the answer cannot be served.

    The re-issue is D11's honouring half (spec §3.5). A caller that stated `max-age` gets an
    answer it can trust: a hit whose age the gateway cannot establish is refused rather than
    served, since the corpus is global and never expires, so "how old is this" has no bound at
    all. It costs one extra round trip and a discarded body, and ONLY on a hit — a miss or a
    bypass was generated just now and satisfies every bound already (`requires_revalidation`).

    INVARIANT: the discarded response is read for its headers and nothing else. Its usage is
    never reported, or the turn would be billed twice — the exact error class this read-back
    exists to prevent.

    Returns:
        The response to consume, and the cache outcome of the round trip that produced IT — not
        of the one that was discarded, whose only remaining trace is that it happened.
    """
    resp, retried = await _post_answered(
        http_client,
        headers=headers,
        # `policy_to_body_field` yields an EMPTY dict for a run that participates, so an ordinary
        # run's body is byte-identical to the one this connector has always sent — which is also
        # the smallest surface exposed to the gateway's closed cache grammar, where one
        # unrecognised key silently costs every hit (spec §1.0).
        # FEATURE (OME-1458): merged INTO an Attempt's `cache` object, never over it, so
        # Attempt 2+ keeps its number; for every other call this is exactly the old merge.
        body=with_cache_policy(body, cache),
        probe=probe,
    )
    _raise_for_status(resp, logprobs_requested=_asks_logprobs(body))
    outcome = read_cache_outcome(resp.headers, retried=retried)
    if not requires_revalidation(cache, outcome):
        return resp, outcome
    # An explicit opt-out, built here rather than derived from `cache`: the run's own policy
    # PARTICIPATES (a bound is not a refusal), and the re-issue must state the one thing the
    # closed grammar understands — `use-cache: false` — and nothing else.
    resp, reissue_retried = await _post_answered(
        http_client,
        headers=headers,
        body=with_cache_policy(body, CachePolicy(participate=False)),
        probe=probe,
    )
    _raise_for_status(resp, logprobs_requested=_asks_logprobs(body))
    # WHY carry the first round trip's flag: it records that a possibly billed attempt was lost
    # before the re-issue. A recorded fact only — no price reads it (OME-1687).
    return resp, read_cache_outcome(resp.headers, retried=retried or reissue_retried)


async def _post_answered(
    http_client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    body: dict,
    probe: _CaptureProbe | None,
) -> tuple[httpx.Response, bool]:
    """Post one chat request; a Candidate call the gateway failed for a moment is asked again.

    FEATURE (OME-1872): the rule and its waits live in `candidate_call_retry`. Stages:

    1. Post the request (`_post_completion` already retries a lost connection and a gateway
       queue timeout once), and show the capture probe the answer.
    2. A judge or any other non-Candidate call, a 2xx, a permanent refusal, or a spent budget of
       `CANDIDATE_CALL_RETRIES` returns the answer as it is; the caller raises a failure.
    3. Otherwise wait (`retry_wait`) and post the SAME headers and body again. A retry whose wait
       plus one full try would outlast the request deadline is not started, checked before the
       wait and again after it.

    AIDEV-NOTE: the wait runs inside the run's fair-share I/O permit (`FairShareIOLayer` holds it
    around the whole model call), so a rate-limited Candidate keeps its permits while it waits, up
    to 120 s. Accepted as backpressure: the connector does not hold the gate, and a slow reasoning
    call holds its permit just as long.

    INVARIANT: every try is the same request with the same call-key headers, below the capture
    occurrence, so the gateway cache keys it the same and a frozen copy stores all tries at one
    key, where replay serves the 200 (or the last error). A replay never comes here.

    Returns the last answer and whether a retry followed a try that may have been billed: a lost
    reply (`_post_completion`) or a 5xx (`may_have_billed`). A recorded fact only (OME-1687).
    """
    retries: int = candidate_call_retry.CANDIDATE_CALL_RETRIES if in_candidate_invocation() else 0
    possibly_billed: bool = False
    retry_number: int = 0
    while True:
        # Stage 1 — one try.
        resp, billed = await _post_completion(http_client, headers=headers, body=body, probe=probe)
        if probe is not None:
            probe.read(resp)
        possibly_billed = possibly_billed or billed
        # Stage 2 — the answer stands.
        if retry_number == retries or not candidate_call_retry.is_temporary(resp.status_code):
            return resp, possibly_billed
        # Stage 3 — wait, then ask again, when the try still fits the deadline.
        retry_number += 1
        delay: float = candidate_call_retry.retry_wait(
            retry_number, resp.headers.get("Retry-After")
        )
        deadline: float | None = _current_deadline()
        if deadline is not None and not _retry_fits(
            deadline, delay, _transport_budget(http_client, headers)
        ):
            return resp, possibly_billed
        possibly_billed = possibly_billed or candidate_call_retry.may_have_billed(
            resp.status_code, queue_refusal=_queue_timeout(resp)
        )
        logger.warning(
            "candidate model call temporary gateway failure status=%s; retry %d of %d in %.1fs",
            resp.status_code,
            retry_number,
            retries,
            delay,
        )
        # WHY retry_number - 1: `_wait_to_retry` names the try that follows as attempt + 2.
        await _wait_to_retry(retry_number - 1, delay)
        # A late wakeup must not start a try cut short by the deadline: billed and useless (NT-H1),
        # the same re-check `_retry_transport` and `_retry_queue` make.
        if deadline is not None and not _retry_fits(
            deadline, 0, _transport_budget(http_client, headers)
        ):
            return resp, possibly_billed


@dataclass(slots=True)
class _CaptureProbe:
    """What the last gateway response of one logical chat call said about its capture.

    Filled BEFORE `_raise_for_status`, so an error response still says what the gateway stored.
    `lost_reply` is called by `_post_completion` at each lost transport reply that may have reached
    the gateway (not a connect-phase failure, OME-1775 R3), even when no response follows. One per
    call: the run's tally is shared by concurrent calls, a field on it would race.
    """

    responded: bool = False
    header: str | None = None
    retried: bool = False
    last_ok: bool = False
    """The last response read was 2xx, so the gateway holds a 200 at this key."""
    read_ok: bool = False
    """Some response read was 2xx, so the gateway holds a 200 at this key — the model may not have
    used it. WHY not a response count (OME-1872): a Candidate call retried after a 429 reads
    several error responses, and a copy holding only errors serves the last one, which reproduces
    the failure; only a stored 200 can be served in place of the answer the model used."""

    def read(self, resp: httpx.Response) -> None:
        self.responded = True
        self.header = resp.headers.get(CAPTURE_FIELD)
        self.last_ok = resp.is_success
        self.read_ok = self.read_ok or resp.is_success

    def lost_reply(self) -> None:
        self.retried = True

    def status(self, *, answered: bool = False) -> Status:
        """What the gateway said, or `ambiguous` when the copy may serve an answer the model never
        used.

        FEATURE: OME-1307 (design §5.2 item 7). A call whose transport attempt was retried may have
        been processed — and stored — before its reply was lost, AHEAD of the answer the model used
        in capture order, which a replay would serve.

        FEATURE: OME-1775 (R2). A `max-age` re-issue that RETURNED has a 2xx last response, and that
        is the entry a replay serves: the gateway stores before it responds (a higher `seq`) and
        strips `cache` from the key digest, so `find` serves the highest-`seq` 200. A re-issue that
        did not return stays `ambiguous`, because `find` would prefer the unused first 200.

        ``answered`` says whether the call returned, so the model used its last response.
        INVARIANT: a call that did NOT return after it read a 2xx is `ambiguous`: the copy holds a
        200 the model never used (a re-issue that failed before it was sent, or a call cancelled
        during its re-issue). The default is the strict one.
        """
        if self.retried or (not answered and self.read_ok):
            return "ambiguous"
        return _CAPTURE_STATUSES.get((self.header or "").strip().lower(), "missing")


def _capture_target() -> tuple[CaptureTally, str] | None:
    """The run's tally and the frozen copy it captures into, read once, or ``None`` when it captures
    nothing — a normal run, a replay, or a capture run whose copy failed to open."""
    tally = current_capture_tally()
    if tally is None or tally.mode != "capture" or tally.frozen_copy_id is None:
        return None
    return tally, tally.frozen_copy_id


async def _recorded_completion(
    http_client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    body: dict,
    cache: CachePolicy,
    replay_frozen_copy: str | None,
) -> tuple[httpx.Response, CacheOutcome]:
    """One gateway round trip in the run's frozen-copy mode.

    FEATURE: OME-1307. A replay run is served by the copy and never by the normal route. A capture
    run names its copy and records, once per consumed response, what the gateway says it stored
    (`X-AIGW-Capture`); a call that raises records an error unless a response or a lost transport
    reply said more (D1).
    A normal run passes straight through, byte-identical to a world without the copy.
    """
    if replay_frozen_copy is not None:
        return await _fetch_replay(
            http_client, headers=headers, body=body, copy_id=replay_frozen_copy
        )
    target = _capture_target()
    if target is None:
        return await _fetch_completion(http_client, headers=headers, body=body, cache=cache)
    tally, copy_id = target
    digest = request_digest(body)
    # Q27 (design §5.4): the call takes its occurrence ONCE, when it is first sent. Every transport
    # attempt of the call sends the same key, and the value is never given back, so a call that
    # stores nothing keeps its place and replay never reads an entry twice.
    case_id, case_key = current_capture_case()
    occurrence = tally.next_occurrence(case_key, "chat", digest)
    key_headers = {FROZEN_COPY_HEADER: copy_id, **call_key_headers(case_key, occurrence)}
    probe = _CaptureProbe()
    try:
        resp, outcome = await _fetch_completion(
            http_client,
            headers={**headers, **key_headers},
            body=body,
            cache=cache,
            probe=probe,
        )
    except BaseException as exc:
        # A cancelled call left no answer the copy can serve (D1); an error response says itself.
        # A lost transport reply, or a 2xx the call never used, may be served all the same, so it
        # stays `ambiguous`, which no later call forgives (D2), cancelled or not.
        cancelled = isinstance(exc, asyncio.CancelledError)
        said = probe.retried or probe.last_ok or (probe.responded and not cancelled)
        record_capture_outcome(
            CaptureOutcome(
                "chat",
                probe.status(answered=False) if said else "error",
                digest,
                case_id=case_id,
                case_key=case_key,
                occurrence=occurrence,
                answered=False,
            )
        )
        raise
    record_capture_outcome(
        CaptureOutcome(
            "chat",
            probe.status(answered=True),
            digest,
            case_id=case_id,
            case_key=case_key,
            occurrence=occurrence,
            answered=True,
            replay_failure=replay_failure_code(resp),
        )
    )
    return resp, outcome


async def _fetch_replay(
    http_client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    body: dict,
    copy_id: str,
) -> tuple[httpx.Response, CacheOutcome]:
    """One chat round trip of a REPLAY run: the copy's answer to this request (design §5.3).

    No cache field and no `max-age` re-issue: a second round trip is not a thing a replay does. The
    occurrence is taken like a capture call's (design §5.4), so the same logical call reads the same
    entry the capture stored.
    """
    digest = request_digest(body)
    tally = current_capture_tally()
    # INVARIANT (design §5.4): a replay call counts its occurrence in the run's tally, which the
    # run path binds. Without one, every call would send occurrence 0, so the call fails loudly.
    if tally is None:
        raise RuntimeError("a frozen-copy replay call needs the run's capture tally bound")
    case_key = current_case_key()
    occurrence = tally.next_occurrence(case_key, "chat", digest)
    try:
        resp, _retried = await _post_completion(
            http_client,
            headers={**headers, **call_key_headers(case_key, occurrence)},
            body=body,
            path=replay_chat_path(copy_id),
        )
    except ResolutionError as exc:
        # Design §5.3 item 2a: every transport attempt failed, and the copy served nothing. A retry
        # would read the next occurrence (§5.4), so the failure is permanent, with no retry.
        raise _replay_unavailable() from exc
    refusal = _replay_refusal(resp)
    if refusal is not None:
        raise refusal
    # Design §5.3 item 2a: a non-2xx answer without the replay header is the gateway's own failure,
    # not a captured one, so the copy did not serve it and the failure is permanent.
    if not resp.is_success and REPLAY_FIELD not in resp.headers:
        raise _replay_unavailable()
    # Any other failure status is the captured original error (it carries X-AIGW-Replay), raised as
    # the original run raised it.
    _raise_for_status(resp, logprobs_requested=_asks_logprobs(body))
    return resp, _REPLAYED


def _replay_unavailable() -> ResolutionError:
    """The engine's own permanent failure for a replay the copy did not serve (design §5.3 2a)."""
    return ResolutionError(
        "the frozen copy is not available for replay", code=REPLAY_UNAVAILABLE, permanent=True
    )


def _replay_refusal(resp: httpx.Response) -> ResolutionError | None:
    """The engine's own failure for a replay the copy cannot answer, or ``None``.

    INVARIANT (OME-941): the codes are reserved, so the message is the engine's own fixed text and
    never the gateway's — which is also why this runs BEFORE `_raise_for_status`, which would
    refuse to carry a reserved code.
    """
    try:
        payload = resp.json()
    except ValueError:
        return None
    code = replay_refusal_code(resp.status_code, payload)
    if code == REPLAY_MISS:
        message = "the frozen copy holds no answer for this call of the replay"
    elif code == REPLAY_UNAVAILABLE:
        message = "the frozen copy is not available for replay"
    else:
        return None
    return ResolutionError(message, code=code, permanent=True)


def _retain_accounting(
    data: Mapping[str, Any],
    cache: CacheOutcome,
    real_model_id: str,
    operation_accounting: list[OperationAccounting | None],
    signal_accounting: list[SignalAccounting] | None,
) -> None:
    """Keep one consumed response's retained accounting and, when asked, its signal accounting."""
    usage = data.get("usage")
    operation_accounting.append(
        _retained_operation_accounting(
            request_model=real_model_id,
            usage=usage if isinstance(usage, dict) else None,
            aigw=data.get("_aigw"),
            cache=cache,
        )
    )
    if signal_accounting is not None:
        signal_accounting.append(_signal_accounting(data.get("_aigw"), cache))


def _retained_operation_accounting(
    *,
    request_model: str,
    usage: Mapping[str, object] | None,
    aigw: object,
    cache: CacheOutcome,
) -> OperationAccounting | None:
    """Fail-open projection of untrusted Gateway accounting onto the strict retained contract."""

    try:
        return retained_operation_accounting(
            request_model=request_model,
            usage=usage,
            aigw=aigw,
            cache=cache,
        )
    except Exception as exc:
        # INVARIANT: accounting is optional bookkeeping over an already-consumed response. No
        # malformed accounting field may replace a successful answer/refusal with a run failure,
        # and diagnostics disclose only the phase plus exception type — never Gateway payloads.
        logger.warning("operation accounting unavailable after %s", type(exc).__name__)
        return None


def _signal_accounting(aigw: object, cache: CacheOutcome) -> SignalAccounting:
    """Fail-open: the ORIGINAL call's numbers for combine signals, or all None."""

    try:
        return signal_accounting_from_aigw(aigw, cache)
    except Exception as exc:
        # INVARIANT: same as `_retained_operation_accounting` -- optional bookkeeping over an
        # already-consumed response, and the log names the exception type only.
        logger.warning("signal accounting unavailable after %s", type(exc).__name__)
        return SignalAccounting()


def _asks_logprobs(body: Mapping[str, object]) -> bool:
    """Whether the call asked for token log-probabilities: ``logprobs`` is exactly ``true``."""
    return body.get("logprobs") is True


def _retain_reply_facts(
    data: Mapping[str, Any],
    body: dict[str, object],
    outcome: CacheOutcome,
    *,
    real_model_id: str,
    operation_accounting: list[OperationAccounting | None],
    signal_accounting: list[SignalAccounting] | None,
    reply_logprobs: list[ReplyLogprobs | None] | None,
) -> None:
    """Report the usage of one answered round trip and keep its accounting and log-probabilities."""
    _report_usage(real_model_id, data.get("usage"), data.get("_aigw"), outcome)
    _retain_accounting(data, outcome, real_model_id, operation_accounting, signal_accounting)
    _retain_reply_logprobs(data, body, reply_logprobs)


def _retain_reply_logprobs(
    data: Mapping[str, Any],
    body: Mapping[str, object],
    rounds: list[ReplyLogprobs | None] | None,
) -> None:
    """Keep one consumed response's reply log-probability numbers, when the caller collects them."""
    if rounds is not None:
        rounds.append(_reply_logprobs(data, body))


def _reply_logprobs(data: Mapping[str, Any], body: Mapping[str, object]) -> ReplyLogprobs | None:
    """Fail-open: the reply's log-probability numbers when the call asked for them, else None.

    WHY only when asked: a call without `logprobs: true` keeps its exact cost and behavior (LC-D4).
    """
    if not _asks_logprobs(body):
        return None
    top_k = body.get("top_logprobs")
    try:
        return reply_logprobs(
            data, top_k if isinstance(top_k, int) and not isinstance(top_k, bool) else None
        )
    except Exception as exc:
        # INVARIANT: same as `_signal_accounting` -- optional bookkeeping over an already-consumed
        # response, and the log names the exception type only (never token text, OME-990).
        logger.warning("reply logprobs unavailable after %s", type(exc).__name__)
        return None


def _raise_if_unusable_with_accounting(
    choice: Choice,
    *,
    max_tokens: object,
    accounting: list[OperationAccounting | None],
    signal_accounting: Sequence[SignalAccounting] | None = None,
) -> None:
    """Classify one response while retaining a consumed provider refusal."""

    try:
        raise_if_unusable(choice, max_tokens=max_tokens)
    except RunnerRequestError as exc:
        if exc.code == "provider_refusal":
            # INVARIANT: a refusal remains a terminal Candidate outcome. Record its consumed
            # accounting before the typed failure exits; the invocation adapter then retains it.
            record_operation_call(
                "",
                choice.finish_reason,
                combine_operation_accounting(accounting),
                None if signal_accounting is None else combine_signal_accounting(signal_accounting),
            )
        raise


def _headers(scope: RequestScope) -> dict[str, str]:
    """The outgoing aigateway headers: verified identity plus the trace this world owns.

    WHY no `Authorization`: aigateway runs `cloudflare_headers` when deployed and `disabled`
    locally. Neither mode reads a bearer token, and a deployed caller cannot obtain one, so the
    run carries none at all.

    FEATURE (OME-1119): `traceparent` is gateway-owned: the run's own trace must win over anything
    that arrived in the identity mapping. Absent (no bound run) the key is OMITTED rather than sent
    empty: a well-formed header carrying a zero or invented id would parse everywhere, join nothing,
    and look correct in every log it reached.

    INVARIANT (F2): identity and seed come from the REQUEST SCOPE, never from `self`, so
    a shared world renders each caller's own values (AC2).

    INVARIANT (FX-64): the trace comes ONLY from `trace_scope`. The run path binds it inside the
    driving task (`Url4Executor`); a sync producer binds it from the validated inbound header
    (`request_scope.trace_from_headers`). One carrier, so no path can prefer a second copy.
    """
    headers = job_env.identity_for_forwarding(scope.identity_headers)
    traceparent = current_traceparent()
    if traceparent is not None:
        headers["traceparent"] = traceparent
    return headers


def _json_or_raise(resp: httpx.Response) -> dict:
    """Decode a 2xx body, naming the failure when it is not JSON at all.

    A fronting access proxy (CF Access) answers with an HTML login page under a 200, which
    `resp.json()` would surface as a bare JSONDecodeError — an unnamed `internal_error` in the
    run's terminal frame instead of something an operator can act on.
    """
    try:
        return resp.json()
    except ValueError as exc:
        # WHY: an empty completed reply supplies no evidence of malformed content or
        # interception. Permit a later retry without replaying a paid call here.
        if not resp.content:
            raise ResolutionError(
                "model request returned an empty response body; the request may be retried",
                code="aigateway_empty_response",
                permanent=False,
            ) from exc
        raise ResolutionError(
            "aigateway returned a non-JSON response body — a proxy or access gateway in front "
            "of aigateway is intercepting the request",
            code="aigateway_bad_response",
            permanent=True,
        ) from exc


class _GatewayRefusal(ResolutionError):
    """A non-2xx aigateway answer, with its status and the plain-text `detail` it carried."""

    def __init__(
        self, message: str, *, code: str, permanent: bool, status: int, detail: str | None
    ) -> None:
        super().__init__(message, code=code, permanent=permanent)
        self.status = status
        self.detail = detail

    def refuses_provider(self, provider: str) -> bool:
        """Whether this is the Gateway's refusal of `provider` as unknown to the caller."""
        return self.status == 400 and self.detail == f"unknown provider: {provider}"


def _upstream_code(detail: dict[str, Any], code: str) -> str:
    """The gateway detail's own `code`, unless it names an engine-reserved one (OME-941)."""
    upstream_code = detail.get("code")
    if isinstance(upstream_code, str) and upstream_code not in ENGINE_RESERVED_CODES:
        return upstream_code
    return code


def _refusal_detail(
    resp: httpx.Response,
) -> tuple[str, str, str | None, GatewayContentPartRefusal | None]:
    """The `code`, `message`, plain-text `detail` and translated refusal of a 4xx/5xx answer.

    A `detail` object gives the code (never one in `ENGINE_RESERVED_CODES`), the message and,
    for the gateway's one translated code (spec #1450 §4), the `intent_error` it maps to; a
    `detail` string is kept as the plain text. Anything else keeps the status-based defaults.
    """
    code = f"aigateway_http_{resp.status_code}"
    message = f"aigateway request failed with status {resp.status_code}"
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    refusal = None
    text: str | None = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            code, message = _upstream_code(detail, code), detail.get("message", message)
            refusal = intent_error_for(detail)
        elif isinstance(detail, str):
            text = detail
    return code, message, text, refusal


def _raise_for_status(resp: httpx.Response, *, logprobs_requested: bool = False) -> None:
    """Turn a non-2xx (or redirected) aigateway response into a `ResolutionError`.

    A redirect is treated as an interception by a fronting proxy, not a real aigateway response.
    For a 4xx/5xx, the error `code`/`message` prefer the response's own `detail` payload when
    present; `permanent` is `False` only for 429 and 5xx, so those (and only those) are
    eligible for retry upstream.

    INVARIANT (OME-941): `detail.code` is UPSTREAM input and may never name a code in
    `ENGINE_RESERVED_CODES`. Public boundaries — the HTTP problem body, the benchmark result
    contract — read those codes as evidence that the engine itself authored the accompanying
    message, and the message here is upstream text. So an upstream (or a proxy in front of
    aigateway, which this module already treats as an assumed threat) that answers
    `{"detail": {"code": "malformed_source", …}}` keeps the engine-authored
    `aigateway_http_<status>` code instead, and its text stays unvouched. Every other upstream
    code still passes through unchanged — that vocabulary is what the failure report reads.

    FEATURE (E4b part 3, C4): a call that asked for token log-probabilities (`logprobs_requested`)
    and that the gateway refused with HTTP 404 `unsupported_parameters` fails as
    `logprobs_unsupported`, with fixed engine text and never the upstream text. Only the 404 maps.
    WHY here and not in `_observed_round_trip`: the rule needs the HTTP status, and only this
    function sees it; each caller holds the request body.
    """
    if 300 <= resp.status_code < 400:
        raise ResolutionError(
            f"aigateway returned an unexpected redirect (status {resp.status_code}) — a proxy "
            "or access gateway in front of aigateway is intercepting the request",
            code="aigateway_bad_response",
            permanent=True,
        )
    if resp.status_code < 400:
        return
    code, message, text, refusal = _refusal_detail(resp)
    if logprobs_requested and resp.status_code == 404 and code == _PARAMETER_REFUSAL_CODE:
        raise logprobs_unsupported()
    permanent = not (resp.status_code == 429 or 500 <= resp.status_code < 600)
    if refusal is not None:
        # Spec #1450 §4: the ONE translated gateway code; permanence kept, `info` as the cause.
        raise _GatewayRefusal(
            message,
            code=INTENT_ERROR,
            permanent=permanent,
            status=resp.status_code,
            detail=text,
        ) from refusal
    raise _GatewayRefusal(
        message, code=code, permanent=permanent, status=resp.status_code, detail=text
    )


def timeout_headers(execution_timeout_s: float, queue_timeout_s: float) -> dict[str, str]:
    """The two time-out budgets the gateway reads from each request.

    WHY plain numbers and not the config object: this module must not import `world.connector`,
    where `AigatewayConfig` lives. `_transport_budget` reads the same two headers back.
    """
    return {
        "x-aigw-execution-timeout-s": str(execution_timeout_s),
        "x-aigw-queue-timeout-s": str(queue_timeout_s),
    }


__all__ = ["round_trip", "timeout_headers"]
