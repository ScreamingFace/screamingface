"""The request-scoped accounting collector and its ``ContextVar`` binding (OME-303 U2).

FEATURE: per-observed-attempt usage accounting — the half that counts local send admissions.

INVARIANT (plan §12 stop condition): one observed send is one record, and no observed
send may disappear. Everything else in this file exists to keep that true across
LiteLLM's hidden resend, the gateway's own overload retry, and HTTP redirect chains —
three mechanisms that all look like "the request hook fired again".

INVARIANT: the collector is REQUEST-SCOPED while the LiteLLM handler that feeds it is
APP-LIFETIME and shared by every concurrent caller. The ``ContextVar`` is the only thing
standing between one caller's sends and another caller's records, which is why
``bound_collector`` is a token-restoring context manager and never a bare ``set()``.

AIDEV-NOTE: the collector is deliberately synchronous and allocation-cheap. It is driven
from httpx event hooks on the request path, so anything that can block or raise here
lands inside an observed provider attempt whose billing outcome is unknown.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ...call_context import new_gateway_call_id as _new_gateway_call_id
from ...core.http_status import valid_http_status
from .classify import FAILURE_CODES, outcome_for_status
from .types import (
    CallOutcome,
    CaptureStatus,
    DirectCost,
    PricingContext,
    ProviderAttemptRecord,
    ProviderUsageAccountingEvidence,
)

__all__ = ["RequestAccountingCollector", "new_gateway_call_id"]


def _bounded_utf8(value: object, *, max_bytes: int) -> str | None:
    """Keep a string only when it is valid UTF-8 and fits the contract bound."""
    if not isinstance(value, str):
        return None
    # Call base ``str`` methods directly so a plugin-provided subclass cannot run an
    # overridden truthiness/``encode``/``__str__`` while evidence is rendered.
    normalized = str.__str__(value)
    if not normalized:
        return None
    try:
        encoded = str.encode(normalized, "utf-8")
    except UnicodeEncodeError:
        return None
    if len(encoded) > max_bytes:
        return None
    return normalized


def _safe_failure_code(outcome: CallOutcome, failure_code: str) -> str:
    if failure_code in FAILURE_CODES:
        return failure_code
    return {
        "provider_error": "provider_status_error",
        "transport_error": "transport_error",
        "conversion_error": "response_conversion_failed",
        "succeeded": "no_response_observed",
        "indeterminate": "no_response_observed",
    }[outcome]


def new_gateway_call_id() -> str:
    """Mint a correlation id — re-exported from `aigateway.call_context` (OME-938).

    The implementation moved out of this plugin because correlation is no longer a side effect
    of usage accounting: middleware mints one id per request and this plugin CONSUMES it, so a
    gateway running with `AIGW_TAXONOMY_ENABLED=false` still correlates. The name stays here
    because `plugins/taxonomy/__init__` publishes it and callers import it from there.

    One implementation, not two: the id shape is pinned by `usage_accounting.schema.json`
    (`^call_[0-9a-f]{32}$`) and by response bodies, so a second minter that drifted would break
    a published contract in a way only a schema test would notice.
    """
    return _new_gateway_call_id()


@dataclass
class _PendingSend:
    """One admitted send, mutable while it is still resolving."""

    attempt_id: str
    sequence: int
    dispatch_index: int
    attempt_index: int
    started_at: float
    # Held so the correlation key (``id(request)``) cannot be recycled onto a later
    # object while this send is still open.
    request_ref: Any
    admitted_urls: set[str] = field(default_factory=set)
    redirect_hop_count: int = 0
    resolved: bool = False
    http_status: int | None = None
    latency_ms: int | None = None
    outcome: CallOutcome = "indeterminate"
    failure_code: str | None = None
    raw_evidence: dict[str, Any] | None = None
    evidence: ProviderUsageAccountingEvidence | None = None
    # Set when a redirect response was seen for THIS send, so the next admission is
    # recognised as a hop of the same generation call rather than a new one.
    awaiting_redirect_hop: bool = False
    # The URL the observed redirect actually pointed at, when the observer could resolve
    # it. Folding is gated on the next admission MATCHING this, so that a resend of the
    # original request cannot be absorbed as a hop. ``None`` means "no URL information",
    # which folds — see ``_continues_redirect``.
    expected_redirect_target: str | None = None


@dataclass
class RequestAccountingCollector:
    """Per-request record of every observed provider send.

    ``dispatch_index`` counts gateway/plugin dispatch attempts (an overload retry is a
    new dispatch). ``attempt_index`` counts transport admissions inside one
    dispatch (LiteLLM's hidden resend is a new attempt). Engine needs both to tell the
    two apart from a flat sequence — plan §12 makes conflating them a stop condition.
    """

    provider: str
    requested_model: str | None
    transport: str
    gateway_call_id: str = field(default_factory=lambda: new_gateway_call_id())

    _sends: list[_PendingSend] = field(default_factory=list, init=False)
    _by_request: dict[int, _PendingSend] = field(default_factory=dict, init=False)
    _dispatch_index: int = field(default=0, init=False)
    _sends_in_dispatch: int = field(default=0, init=False)
    _incomplete: bool = field(default=False, init=False)

    # ---- dispatch lifecycle -------------------------------------------------

    def begin_dispatch(self) -> int:
        """Open a new gateway/plugin dispatch attempt and return its one-based index."""
        self._dispatch_index += 1
        self._sends_in_dispatch = 0
        return self._dispatch_index

    @property
    def dispatched(self) -> bool:
        return self._dispatch_index > 0

    def mark_incomplete(self) -> None:
        """Record that some evidence could not be captured.

        Called by the hooks' own failure paths. Once set it never clears: a collector
        that missed something cannot later prove it did not.
        """
        self._incomplete = True

    # ---- transport observation (driven from the httpx hooks) ----------------

    def on_send_admitted(self, request: object) -> None:
        """A send was admitted to the local transport pipeline.

        When the previous send for this dispatch is awaiting a redirect hop AND this
            admission is going to that hop's target, this is that hop: it continues the SAME
            generation record. Otherwise it is a new observed attempt.

        INVARIANT: an admission that is NOT the promised hop is never folded. LiteLLM
        resends the ORIGINAL request when httpx fails to follow a redirect (a malformed
        ``Location`` becomes ``RemoteProtocolError``, which
        ``AsyncHTTPHandler.post`` retries once), and folding that resend would delete a
        real observed send while the request still reported ``capture_status=complete``.
        """
        open_send = self._open_redirecting_send()
        if open_send is not None:
            if self._continues_redirect(open_send, request):
                request_url = getattr(request, "url", None)
                if request_url is not None and str(request_url) in open_send.admitted_urls:
                    # WHY: at this seam a self-redirect is indistinguishable from LiteLLM
                    # resending any earlier URL in the chain on a replacement client. Keep
                    # one economic attempt, but do not claim every admission was represented.
                    self._incomplete = True
                if request_url is not None:
                    open_send.admitted_urls.add(str(request_url))
                open_send.redirect_hop_count += 1
                open_send.awaiting_redirect_hop = False
                open_send.expected_redirect_target = None
                # Re-key so the hop's own response resolves the same record.
                self._by_request[id(request)] = open_send
                open_send.request_ref = request
                return
            # Somewhere else entirely: the promised hop never happened. Disarm the fold,
            # finalize the redirect response as a transport error and record this admission
            # separately below. Both observed admissions remain represented, so this branch
            # does not by itself make capture incomplete.
            open_send.awaiting_redirect_hop = False
            open_send.expected_redirect_target = None
            self._finalize_send_failure(
                open_send, outcome="transport_error", failure_code="transport_error"
            )
        self._finalize_previous_unresolved_send()
        self._sends_in_dispatch += 1
        send = _PendingSend(
            attempt_id=f"attempt_{uuid.uuid4().hex}",
            sequence=len(self._sends) + 1,
            dispatch_index=max(self._dispatch_index, 1),
            attempt_index=self._sends_in_dispatch,
            started_at=time.monotonic(),
            request_ref=request,
        )
        request_url = getattr(request, "url", None)
        if request_url is not None:
            send.admitted_urls.add(str(request_url))
        self._sends.append(send)
        self._by_request[id(request)] = send

    def on_redirect_observed(self, request: object, *, target: str | None = None) -> None:
        """The response for ``request`` was a redirect the transport will follow.

        INVARIANT (§3.4): a redirect chain is ONE generation call. httpx fires the
        request hook once per hop, so without this the hop count would become the
        observed-attempt count and inflate ``observed_new_attempts``.

        ``target`` is the resolved absolute URL the redirect points at, when the observer
        could work it out. Pass it whenever it is known: it is what lets the next
        admission be checked against the hop that was actually promised. Callers with no
        URL information may omit it, and then any next admission folds as before.
        """
        send = self._by_request.get(id(request))
        if send is None or send.resolved:
            return
        send.awaiting_redirect_hop = True
        send.expected_redirect_target = target

    def on_response_completed(
        self,
        request: object,
        *,
        status: object,
        raw_evidence: dict[str, Any] | None,
        body_completed: bool = True,
    ) -> None:
        """A response arrived for ``request``.

        ``latency_ms`` is measured to here, which is why the response hook reads the
        body before calling this: measuring at headers would be time-to-headers wearing
        the name of provider latency.

        INVARIANT (§3.4): when ``body_completed`` is False the body was never read — an
        oversized or unexpectedly streaming response — so ``latency_ms`` stays ``None``
        rather than silently reporting time-to-headers under the name of provider
        latency.
        """
        send = self._by_request.get(id(request))
        if send is None or send.resolved:
            # A callback for a send this collector never admitted. Ignoring it is the
            # only safe answer — inventing a record would fabricate provider work.
            return
        send.resolved = True
        send.awaiting_redirect_hop = False
        send.http_status = valid_http_status(status)
        if body_completed:
            send.latency_ms = max(0, int((time.monotonic() - send.started_at) * 1000))
        else:
            self._incomplete = True
        send.outcome = outcome_for_status(status)
        if send.outcome == "provider_error":
            send.failure_code = "provider_status_error"
        send.raw_evidence = raw_evidence

    def finalize_last_open_failure(self, *, outcome: CallOutcome, failure_code: str) -> bool:
        """Finalize the last admitted send after dispatch escapes with no response hook."""
        if not self._sends or self._sends[-1].resolved:
            return False
        self._finalize_send_failure(self._sends[-1], outcome=outcome, failure_code=failure_code)
        return True

    def mark_last_succeeded_provider_error(self) -> None:
        """Correct an HTTP-200 body that provider-specific validation rejected."""
        if not self._sends or self._sends[-1].outcome != "succeeded":
            return
        self._sends[-1].outcome = "provider_error"
        self._sends[-1].failure_code = "provider_status_error"

    def mark_last_succeeded_indeterminate(self) -> None:
        """Downgrade a completed 2xx followed by an unclassified local failure.

        INVARIANT: only an explicit conversion marker may claim ``conversion_error`` and
        only provider-body validation may claim ``provider_error``. With neither proof,
        retaining ``succeeded`` would overstate the usable outcome, so the attempt becomes
        indeterminate without inventing a failure code.
        """
        if not self._sends or self._sends[-1].outcome != "succeeded":
            return
        self._sends[-1].outcome = "indeterminate"
        self._sends[-1].failure_code = None

    # ---- evidence ------------------------------------------------------------

    def open_records(self) -> tuple[tuple[str, dict[str, Any] | None, bool], ...]:
        """``(attempt_id, raw_evidence, succeeded)`` for every observed send.

        The seam feeds this to the provider's pure mapper. Handing over the raw evidence
        rather than the collector keeps a mapper structurally unable to add, drop or
        reorder records.
        """
        return tuple(
            (send.attempt_id, send.raw_evidence, send.outcome == "succeeded")
            for send in self._sends
        )

    def apply_evidence(self, attempt_id: str, evidence: ProviderUsageAccountingEvidence) -> None:
        """Attach a provider mapper's normalized evidence to one record."""
        for send in self._sends:
            if send.attempt_id != attempt_id:
                continue
            send.evidence = evidence
            return

    def mark_conversion_failed(self, outcome: CallOutcome, failure_code: str) -> None:
        """Downgrade the last succeeded send after local conversion of it failed.

        INVARIANT: the provider already answered — and was very likely billed — so the
        record stays, and only its outcome changes. Dropping it would under-report
        real spend.
        """
        if not self._sends or self._sends[-1].outcome != "succeeded":
            return
        self._sends[-1].outcome = outcome
        self._sends[-1].failure_code = _safe_failure_code(outcome, failure_code)

    # ---- results -------------------------------------------------------------

    def records(self) -> tuple[ProviderAttemptRecord, ...]:
        return tuple(self._record(send) for send in self._sends)

    def _record(self, send: _PendingSend) -> ProviderAttemptRecord:
        evidence = send.evidence
        return ProviderAttemptRecord(
            attempt_id=send.attempt_id,
            sequence=send.sequence,
            dispatch_index=send.dispatch_index,
            attempt_index=send.attempt_index,
            provider=self.provider,
            transport=self.transport,
            outcome=send.outcome,
            requested_model=_bounded_utf8(self.requested_model, max_bytes=512),
            response_model=(
                _bounded_utf8(evidence.response_model, max_bytes=512)
                if evidence is not None
                else None
            ),
            provider_response_id=(
                _bounded_utf8(evidence.provider_response_id, max_bytes=256)
                if evidence is not None
                else None
            ),
            http_status=send.http_status,
            latency_ms=send.latency_ms,
            usage=(
                evidence.usage if evidence is not None else ProviderUsageAccountingEvidence().usage
            ),
            pricing_context=(
                evidence.pricing_context if evidence is not None else PricingContext()
            ),
            direct_cost=(
                evidence.direct_cost if evidence is not None else DirectCost.unavailable()
            ),
            provider_extensions=(evidence.provider_extensions if evidence is not None else ()),
            redirect_hop_count=send.redirect_hop_count,
            failure_code=send.failure_code,
        )

    def status(self) -> CaptureStatus:
        """The request-level accounting status.

        ``accounting_not_supported`` is NOT decided here: it is a property of the
        provider's declared strategy, which the renderer owns. This method answers only
        "given what was observed, how good is this record set".
        """
        if not self.dispatched:
            return "not_applicable"
        if not self._sends:
            # §9.22: dispatched but nothing observed. Never `complete` — that would
            # claim the provider was asked for nothing.
            return "partial"
        if self._incomplete or not all(send.resolved for send in self._sends):
            return "partial"
        return "complete"

    def _open_redirecting_send(self) -> _PendingSend | None:
        """The most recent send that saw a redirect and expects its following hop."""
        if not self._sends:
            return None
        last = self._sends[-1]
        return last if last.awaiting_redirect_hop and not last.resolved else None

    def _finalize_previous_unresolved_send(self) -> None:
        if not self._sends:
            return
        previous = self._sends[-1]
        if previous.resolved:
            return
        self._finalize_send_failure(
            previous, outcome="transport_error", failure_code="transport_error"
        )

    @staticmethod
    def _finalize_send_failure(
        send: _PendingSend, *, outcome: CallOutcome, failure_code: str
    ) -> None:
        send.resolved = True
        send.awaiting_redirect_hop = False
        send.outcome = outcome
        send.failure_code = _safe_failure_code(outcome, failure_code)

    @staticmethod
    def _continues_redirect(open_send: _PendingSend, request: object) -> bool:
        """Whether ``request`` is the hop ``open_send``'s redirect promised.

        Compared as STRINGS so this module stays stdlib-only — it is imported by callers
        that must not pull in the HTTP stack, so URL semantics belong to the observer that
        already has httpx and resolves the target.

        WHY unknown information folds rather than splits: with no target recorded there is
        nothing to contradict, and refusing to fold would break the redirect collapse
        §3.4 requires. The safety asymmetry is deliberate — a target that drifts produces
        an extra VISIBLE record (honest over-reporting), never a vanished send.

        AIDEV-NOTE: a provider that self-redirects (``Location`` equal to the request URL)
        is genuinely indistinguishable from a resend of that same URL at this seam. It
        folds to preserve redirect economics, while the caller marks capture incomplete.
        """
        target = open_send.expected_redirect_target
        if target is None:
            return True
        url = getattr(request, "url", None)
        if url is None:
            return True
        return str(url) == target
