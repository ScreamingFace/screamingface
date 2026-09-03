"""OME-305 — the async half of the global cache stage for POST /v1/chat/completions.

FEATURE: one globally shared exact-request cache. The route consults this stage after
the caller's profile defaults are merged body-wins and before auth-mode or provider
credential resolution.

STORY: as a benchmark operator I re-run a suite from a second account and the
identical calls come back from the first run's stored responses, with no provider
dispatch and no credential access.

INVARIANT: the cache is never an availability dependency (plan §5.4).

INVARIANT: no prompt, response body, plaintext, ciphertext or credential appears in
any log line here. Only a 12-character key prefix, the provider, the model and a
status word from a closed vocabulary.

AIDEV-NOTE: the PURE half — which requests are eligible and what their key is —
lives in ``core.request_cache.global_plan`` and is deliberately free of ``Request``,
``app.state`` and I/O. Keep it that way: that split is what lets the ticket's
identity-invariance and projection-purity properties be tested without a
connection, a credential blob or a database.

"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from fastapi import Request, Response

from ..core.cache_ports import CACHE_UNAVAILABLE_REASON, PUBLISHED_CACHE_REASONS, CacheBypass
from ..core.plugin_base import ProviderPluginBase
from ..core.request_cache import CacheUnavailable, RequestCacheWrite
from ..core.request_cache.global_controls import GlobalCacheControls
from ..core.request_cache.global_keys import GlobalCacheKeyResult
from ..core.request_cache.global_plan import BYPASS_DISABLED, build_global_cache_plan

logger = logging.getLogger(__name__)

CACHE_HEADER: Final = "X-AIGW-Cache"
REASON_HEADER: Final = "X-AIGW-Cache-Reason"
WRITE_HEADER: Final = "X-AIGW-Cache-Write"
KEY_HEADER: Final = "X-AIGW-Cache-Key"

# WHY a 12-character prefix and not the whole hash (decision 5, CORRECTED by decision
# 38): truncation does NOT remove the ability to confirm that two callers sent the
# identical request, and the earlier rationale claiming it did was wrong. Twelve hex
# characters are 48 bits, so sharing a prefix means sharing the whole key for any
# realistic corpus — the prefix identifies a request just as well as the digest does.
#
# Request-equality confirmation is INHERENT to a shared global cache and is an
# accepted trade-off of the approved design, not something this constant defends
# against: ``X-AIGW-Cache: hit`` on a caller's first-ever send of a body already
# reveals that somebody sent that exact body before, and this header is emitted on a
# MISS as well, so a caller can record the key now and watch for it later regardless
# of its length.
#
# What truncation actually buys, and the only claims that should be made for it: a
# bounded, uniform amount of header and log text, and not handing the caller the row's
# literal primary key — a value that is directly usable as a lookup rather than merely
# correlatable. An operator can still match a log line to a response, which is the
# whole purpose.
#
# AIDEV-NOTE: do NOT restore the "cross-tenant fingerprint" rationale. It overstated
# the defence, and a reader who believes it may conclude the cache conceals request
# equality between accounts. It does not, by design — see DEPLOYMENT.md.
KEY_PREFIX_LENGTH: Final = 12

# The reason reported when a reason somehow falls outside the published vocabulary.
# See ``_publishable``.
_UNCLASSIFIED: Final = CACHE_UNAVAILABLE_REASON

CacheStatus = Literal["hit", "miss", "bypass"]
WriteStatus = Literal["stored", "race_lost", "not_stored"]


@dataclass(frozen=True)
class GlobalCacheOutcome:
    """What the pre-credential stage decided, and everything the route needs after.

    INVARIANT: ``response`` is non-None only for a ``hit``, and ``key`` is non-None
    only when the request is eligible — so a caller cannot accidentally write back
    under a key the plan refused.
    """

    status: CacheStatus
    reason: str
    response: dict[str, Any] | None = None
    key: GlobalCacheKeyResult | None = None

    @property
    def is_hit(self) -> bool:
        return self.status == "hit"

    @property
    def should_store(self) -> bool:
        """A miss on an eligible request is the only case that fills the cache.

        INVARIANT: a bypass never writes. That matters most for
        ``cache_unavailable``: the store just failed to READ, and writing to it
        would be both futile and a second chance to fail.
        """
        return self.status == "miss" and self.key is not None


def _publishable(reason: str) -> str:
    """Clamp a reason to the published vocabulary before it reaches a header.

    WHY clamped rather than asserted: this runs on the request path, where an
    assertion would either be stripped under ``-O`` or turn a cosmetic problem into
    a failed request. The real enforcement is a test — every reason any layer can
    emit is proven to be a member — so this branch is unreachable in practice and
    exists so that an unpublished string can never be the thing an operator reads.
    """
    if reason in PUBLISHED_CACHE_REASONS:
        return reason
    logger.warning("cache reason outside the published vocabulary was clamped")
    return _UNCLASSIFIED


def _closed_gate_reason(settings: Any) -> str:
    return BYPASS_DISABLED if not settings.request_cache_enabled else CACHE_UNAVAILABLE_REASON


def defaults_unreadable_bypass() -> GlobalCacheOutcome:
    """The outcome for "we could not read the defaults that belong in the key" (§57).

    WHY it reuses ``cache_unavailable`` rather than adding a value: the published
    vocabulary is read by URL4, and this is the same class of event every other member
    of that value already names — a store the gateway depends on did not answer, so the
    cache stood down. An operator's next action is identical.

    INVARIANT: a bypass, never a miss. A miss would send the route on to WRITE a row
    under a key built from a body whose defaults are missing — turning a failed read
    into a permanently poisoned entry, since current rows never expire.
    """
    return GlobalCacheOutcome(status="bypass", reason=CACHE_UNAVAILABLE_REASON)


async def look_up_global_cache(
    request: Request,
    *,
    body: dict[str, Any],
    plugin: ProviderPluginBase,
    controls: GlobalCacheControls,
) -> GlobalCacheOutcome:
    """Decide eligibility and, when eligible, try to serve this request from cache.

    ``body`` must already have passed JSON shape validation, the gateway ingress
    strip, the provider's own dispatch-control strip, cache-control removal and the
    caller's profile-defaults merge (OME-305 §57 — the key covers the EFFECTIVE
    request). It must NOT yet have a resolved auth mode or a credential.

    INVARIANT: totally non-raising. Every outcome is a status plus a published
    reason.
    """
    store = request.app.state.request_cache_store
    try:
        enabled = bool(store.cache_available())
    except Exception:
        # A gate that cannot answer is a gate that is closed. Never a request failure.
        logger.warning("cache availability check failed; treating the cache as unavailable")
        return GlobalCacheOutcome(status="bypass", reason=CACHE_UNAVAILABLE_REASON)

    decision = build_global_cache_plan(
        body=body, plugin=plugin, controls=controls, cache_enabled=enabled
    )
    if isinstance(decision, CacheBypass):
        reason = _publishable(decision.reason)
        if reason == BYPASS_DISABLED:
            reason = _closed_gate_reason(request.app.state.settings)
        return GlobalCacheOutcome(status="bypass", reason=reason)

    key = decision
    try:
        cached = await store.get(key.key_hash)
    except CacheUnavailable:
        # INVARIANT: a read failure is a BYPASS, never a miss. Reporting a miss would
        # send the route on to write into a store that has just failed to read.
        logger.warning(
            "global cache unavailable on read provider=%s model=%r key=%s…",
            key.provider,
            key.model,
            key.key_hash[:KEY_PREFIX_LENGTH],
        )
        return GlobalCacheOutcome(status="bypass", reason=CACHE_UNAVAILABLE_REASON)
    except Exception:
        # Defence in depth: the store contract says only ``CacheUnavailable``, but an
        # unexpected escape must still not fail a request the provider can serve.
        logger.warning("unexpected global cache read failure; bypassing")
        return GlobalCacheOutcome(status="bypass", reason=CACHE_UNAVAILABLE_REASON)

    if cached is None:
        return GlobalCacheOutcome(status="miss", reason="", key=key)
    logger.info(
        "global cache hit provider=%s model=%r key=%s…",
        key.provider,
        key.model,
        key.key_hash[:KEY_PREFIX_LENGTH],
    )
    return GlobalCacheOutcome(status="hit", reason="", response=cached, key=key)


def _is_a_whole_answer(result: dict[str, Any]) -> bool:
    """Whether a provider response is complete enough to become the permanent answer.

    INVARIANT (owner's ruling on plan U5's "partial responses"): a cache row has
    ``expires_at = NULL``, so a truncated or half-built completion stored once is
    served to every later caller of that body forever. This is why completeness is
    a guard and not a nicety.

    The test is STRUCTURAL — the three shapes that say "this is not a finished
    completion" — and deliberately not semantic. Refusing on content would mean
    judging answers, which this stage has no business doing:

    * no ``choices``, or an empty list — nothing was produced at all;
    * ANY choice carrying no ``message`` — a delta or a shell, not an answer;
    * ANY choice whose ``finish_reason`` is null OR absent — the provider never
      declared that answer ended, which is what a stream cut mid-flight leaves.

    WHY EVERY choice and not just ``choices[0]``: ``n`` is KEYED for every cacheable
    provider, so an ``n=2`` body has its own key and is replayed only to another
    ``n=2`` request — which is precisely what makes a half-finished pair permanent
    rather than harmless. Judging the first choice alone stored it. Position must not
    change the verdict: the same shape is refused wherever it appears.

    Absence and explicit ``null`` are treated identically on purpose: both mean the
    same thing, and distinguishing them would only reward a provider for spelling
    an unfinished answer one way rather than the other.

    WHY ``finish_reason: "length"`` IS stored even though its text is cut off: the
    truncation is the CORRECT answer to the request that was sent. The caller set
    ``max_tokens``; a later caller sending the identical body — same ``max_tokens``
    included — wants that same truncated answer, and re-dispatching would only buy
    an identical truncation at full price.

    AIDEV-NOTE: THE PRECEDING PARAGRAPH IS A DEPENDENCY, NOT AN ASIDE. Storing
    ``"length"`` is sound ONLY because ``max_tokens`` is KEYED (owner decision B).
    Give ``max_tokens`` ``cache_behavior="bypass"`` and two callers with different
    ceilings collapse onto one key, so whoever asked for 4000 tokens is served the
    answer that stopped at 20 — a WRONG-HIT class, not a missed opportunity. Any
    change that un-keys ``max_tokens`` must revisit this function in the same commit.
    """
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    return all(
        isinstance(choice, dict)
        and isinstance(choice.get("message"), dict)
        and choice.get("finish_reason") is not None
        for choice in choices
    )


async def store_global_response(
    request: Request, *, outcome: GlobalCacheOutcome, result: Any
) -> WriteStatus:
    """Fill the global entry after a successful dispatch. Never raises.

    INVARIANT (plan §5.3): first successful insert wins. A racing miss reports
    ``race_lost`` and the winner's response stays — a second dispatch's answer never
    overwrites the first, because two callers must be able to trust that one key
    means one stored response.

    INVARIANT: every refusal to fill is reported as ``not_stored`` and the caller's
    response is returned untouched. There is no failure mode here that costs an
    answer — only ones that cost an entry.

    WHY ``result`` is typed ``Any`` rather than ``dict``: this function remains total at
    its boundary even though the chat route now rejects non-object provider results before
    reaching it. Other or future callers cannot turn a malformed value into a global row.
    """
    key = outcome.key
    if key is None:  # pragma: no cover - guarded by should_store at the call site
        return "not_stored"
    if not isinstance(result, dict):
        # Malformed responses are never stored (plan §5.2). The chat route rejects these;
        # retain the guard as defense in depth for any future caller.
        logger.warning("provider response was not a JSON object; not stored")
        return "not_stored"
    if not _is_a_whole_answer(result):
        # Shape only, never content: that a response lacked a finish_reason is a
        # structural fact, whereas any excerpt of it would be response plaintext.
        logger.info(
            "global cache fill skipped: incomplete response provider=%s model=%r key=%s…",
            key.provider,
            key.model,
            key.key_hash[:KEY_PREFIX_LENGTH],
        )
        return "not_stored"
    try:
        size_bytes = len(
            json.dumps(
                result,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
    except (TypeError, ValueError):
        # A response the gateway cannot serialize cannot be stored; the caller still
        # gets it. No body content is logged.
        logger.warning("provider response was not serializable; not stored")
        return "not_stored"
    # WHY the cap is enforced HERE and not left to the store (plan U5 — oversized
    # responses stay ineligible): rows currently have ``expires_at = NULL``, so an oversized entry
    # is permanent. This is the only bound on how much one response can occupy, and it is a WRITE
    # outcome rather than a bypass because the size is unknowable until after
    # the provider has already answered.
    max_bytes = request.app.state.settings.request_cache_max_response_bytes
    if size_bytes > max_bytes:
        # Size only, never content: the byte count of an oversized response is a
        # capacity fact, whereas any excerpt of it would be response plaintext.
        logger.info(
            "global cache fill skipped: response too large provider=%s model=%r key=%s… bytes=%d",
            key.provider,
            key.model,
            key.key_hash[:KEY_PREFIX_LENGTH],
            size_bytes,
        )
        return "not_stored"
    try:
        written = await request.app.state.request_cache_store.set_if_absent(
            RequestCacheWrite(
                key_hash=key.key_hash,
                # INVARIANT (ruling 35): ``prompt_hash`` IS the full-call key
                # hash, never a prompt-only digest — see ``global_keys``.
                prompt_hash=key.prompt_hash,
                provider=key.provider,
                model=key.model,
                response=result,
                response_size_bytes=size_bytes,
            )
        )
    except Exception:
        # A write failure after a successful dispatch must still return that response
        # (plan §8 #16). The caller is unaffected; only the fill is lost.
        logger.warning(
            "global cache write failed provider=%s model=%r key=%s…",
            key.provider,
            key.model,
            key.key_hash[:KEY_PREFIX_LENGTH],
        )
        return "not_stored"
    logger.info(
        "global cache fill %s provider=%s model=%r key=%s… bytes=%d",
        written,
        key.provider,
        key.model,
        key.key_hash[:KEY_PREFIX_LENGTH],
        size_bytes,
    )
    return written


def global_cache_headers(
    outcome: GlobalCacheOutcome, *, write_status: WriteStatus | None = None
) -> dict[str, str]:
    """The closed provenance header set for this request, as a plain mapping.

    INVARIANT: the header set is CLOSED and carries no identity — no account, no
    profile, no credential name. ``X-AIGW-Cache-Write`` appears on a miss only,
    because "what did the write do" is meaningless for a hit or a bypass.

    WHY a mapping and not just a mutator: the streaming path returns a FRESH
    ``StreamingResponse``, and FastAPI does not merge the injected ``Response``
    object's headers into a response the handler returns itself. Building the set
    once here is what keeps the streaming bypass headers from drifting into a
    second, hand-spelled vocabulary.
    """
    headers = {
        CACHE_HEADER: outcome.status,
        REASON_HEADER: _publishable(outcome.reason) if outcome.reason else "",
    }
    if outcome.key is not None:
        headers[KEY_HEADER] = outcome.key.key_hash[:KEY_PREFIX_LENGTH]
    if write_status is not None:
        headers[WRITE_HEADER] = write_status
    return headers


def set_global_cache_headers(
    response: Response,
    outcome: GlobalCacheOutcome,
    *,
    write_status: WriteStatus | None = None,
) -> None:
    """Publish ``global_cache_headers`` onto a response the framework will send."""
    response.headers.update(global_cache_headers(outcome, write_status=write_status))
