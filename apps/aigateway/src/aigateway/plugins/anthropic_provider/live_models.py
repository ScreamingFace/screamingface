"""OME-1026 — live discovery of the Anthropic model catalog (credentialed, OPT-IN).

FEATURE: automatic model discovery — a profile's model listing shows the Claude models
THAT ACCOUNT can actually use NOW, discovered from ``GET https://api.anthropic.com/v1/models``
with the account's own stored key, instead of only the compiled seed aliases frozen at release
time. A newly released model appears without a gateway release; a retired alias disappears
instead of 404-ing at dispatch.

INVARIANT (PROFILE-SCOPED credential): Anthropic's catalog is credentialed-only (401 without
``x-api-key``), and the credential is always the CALLER's own already-stored profile key,
supplied as an allowlisted header context built by that profile's ``CredentialStrategy``.
This module never reads a stored key, never sees a ``SecretStr`` setting, and never learns
which account it is fetching for. The resulting snapshot describes ONE account's
entitlements, so it is cached only under that profile's private identity — never in the
shared ``ModelCatalog`` and never in ``GET /v1/models``.

INVARIANT (header hardening): only the allowlisted auth header names below reach the wire,
and only at the single allowlisted origin, checked before the connection opens. A caller
cannot smuggle an extra header through the auth context.

INVARIANT (fail-closed, all-or-nothing): this envelope carries NO ``total_count`` — unlike
OpenRouter's, completeness cannot be reconciled by counting. Completeness therefore means the
walk TERMINATED (``has_more=false``) with monotone cursor progress under every cap, and any
malformed page, row, or cursor fails the WHOLE refresh. Nothing partial is ever cached as
fresh; the cache keeps serving the last good snapshot, and compiled seeds are the cold
fallback.

INVARIANT (D7 publication): aliases AND date-stamped snapshots publish unfolded as separate
dispatchable ids in upstream order, deduplicated on first occurrence. Both forms dispatch,
snapshots allow exact pinning, and Anthropic exposes no authoritative alias-to-snapshot
relation — so no folding is inferred here.

INVARIANT: live data changes what is LISTED, never what is dispatchable. Admission, chat
dispatch, and the ``anthropic:static`` parameter evidence in ``discovery.py`` are untouched.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlencode

from aigateway.core.model_capabilities import canonical_model_id
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    fetch_discovery_json,
)
from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry

from .settings import AnthropicPluginSettings

# The owning plugin's ``custom_llm_provider``: the canonical-id prefix AND the litellm
# transport prefix, which is why a discovered id dispatches exactly like a compiled seed.
_PROVIDER = "anthropic"

MODELS_LIST_URL = "https://api.anthropic.com/v1/models"
# INVARIANT: the ONE origin this module may dial, checked by the envelope BEFORE the
# connection opens — which is what makes it safe for the dial to carry a credential.
ALLOWED_ORIGINS = frozenset({"https://api.anthropic.com"})

# WHY the documented maximum: the whole Anthropic catalog is a few dozen models, so one
# page is the cheapest complete walk. Smaller pages would only multiply dials against a
# paid, rate-limited upstream.
_PAGE_LIMIT = 1000
# WHY 8 pages of 1000: eight is already ~400x the real catalog size, so needing a ninth
# means a looping or runaway cursor chain, not a bigger catalog.
_MAX_PAGES = 8
_MAX_CATALOG_MODELS = 2_000
# INVARIANT: single-flight dedupes the DIAL, not the wait — every concurrent lister queues
# behind ONE refresh, so the whole chain needs one aggregate wall-clock deadline on top of
# the per-page envelope timeout.
_AGGREGATE_TIMEOUT_S = 10.0

# INVARIANT: identity + cache policy declared BEFORE any fetch (§5.3), so the catalog can
# trust or expire a stored snapshot without dialing. The key names the SOURCE and carries NO
# credential material. Under the profile-scoped design the PRIVATE cache composes this key
# with the owning ``(account_id, provider, profile_name)`` identity — a credential must never
# appear in a cache key, so ownership data does the scoping and this supplies only policy.
ANTHROPIC_MODELS_DISCOVERY_SOURCE = ModelDiscoverySource(
    key="anthropic:models:list",
    revision="anthropic:models:list-v1",
    ttl_s=300.0,
    stale_ttl_s=3600.0,
    failure_ttl_s=30.0,
)

# INVARIANT (D7): ONE charset serves BOTH publishable ids and pagination cursors. It excludes
# ``/`` (would corrupt the ``anthropic/<id>`` canonical namespace), ``:`` and ``~``
# (gateway-reserved variant/alias syntax), and every URL metacharacter BY CONSTRUCTION —
# which is what makes a cursor safe to embed in the next request's query.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_ID_LENGTH = 256

# The only row ``type`` this gateway publishes. A row typed anything else is structurally
# valid but not a dispatchable model, so publishing it would produce an id that 404s.
_MODEL_ROW_TYPE = "model"


def _is_safe_token(value: str) -> bool:
    """Whether an upstream id or cursor is safe to publish / embed in a URL.

    # WHY ``fullmatch`` and never ``match``: with ``match``, the trailing ``$`` still
    # accepts a value ending in a newline (``"abc\\n"``), which would smuggle whitespace
    # into a model id or a request line. ``fullmatch`` requires the WHOLE string.
    """
    return len(value) <= _MAX_ID_LENGTH and _SAFE_ID_RE.fullmatch(value) is not None


def parse_catalog_page(payload: Any) -> tuple[tuple[str, ...], bool, str | None]:
    """One catalog page -> (model-candidate ids in page order, has_more, next cursor).

    STRICT by construction: the envelope must be a dict with a ``data`` list and a real
    boolean ``has_more``; every row must be an object with a string ``id``; and when
    ``has_more`` is true, ``last_id`` must be a safe-shaped string. Anything else raises
    ``malformed_json`` for the WHOLE page.

    Row type policy (D7) — four outcomes, all deliberate:

    - ``type`` absent, or ``type == "model"`` → a model candidate;
    - a present STRING type other than ``model`` → structurally valid, excluded from
      publication (validated first, so it still proves the page is trustworthy);
    - a present NON-STRING type → malformed; the row schema is not what we believe, so no
      row on this page can be trusted, including the ones that look fine.

    Unknown envelope and row fields are ignored: only ``id`` and ``type`` are ever read, so
    an additive upstream change cannot take the listing down.
    """
    if not isinstance(payload, dict):
        raise DiscoveryError("malformed_json")
    data = payload.get("data")
    if not isinstance(data, list):
        raise DiscoveryError("malformed_json")

    ids: list[str] = []
    for row in data:
        if not isinstance(row, dict):
            raise DiscoveryError("malformed_json")
        model_id = row.get("id")
        if not isinstance(model_id, str):
            raise DiscoveryError("malformed_json")
        if "type" in row:
            row_type = row["type"]
            if not isinstance(row_type, str):
                raise DiscoveryError("malformed_json")
            if row_type != _MODEL_ROW_TYPE:
                continue
        ids.append(model_id)

    has_more = payload.get("has_more")
    # INVARIANT: a REAL bool. ``bool`` is an int subclass, so ``isinstance`` already rejects
    # ``has_more: 1``; the point of testing it by type rather than truthiness is that
    # ``"false"`` is a truthy string and would otherwise walk forever.
    if not isinstance(has_more, bool):
        raise DiscoveryError("malformed_json")
    if not has_more:
        # INVARIANT (CC-11): the cursor is dropped STRUCTURALLY on the terminal page. The
        # envelope populates ``last_id`` on every page including the last, so returning it
        # would let a future walk edit continue past the documented end of the catalog.
        return tuple(ids), False, None

    cursor = payload.get("last_id")
    if not isinstance(cursor, str) or not _is_safe_token(cursor):
        raise DiscoveryError("malformed_json")
    return tuple(ids), True, cursor


def _page_url(cursor: str | None) -> str:
    """The pinned page query, with any cursor properly encoded.

    # WHY a real encoder rather than an f-string: ``cursor`` is upstream-controlled. It has
    # already been charset-validated by ``parse_catalog_page`` (so no encoding is even
    # needed in practice), but building request material out of remote input with string
    # concatenation is the habit that produces injection bugs — belt and braces.
    """
    query = {"limit": str(_PAGE_LIMIT)}
    if cursor is not None:
        query["after_id"] = cursor
    return f"{MODELS_LIST_URL}?{urlencode(query)}"


# INVARIANT (header hardening): the ONLY auth header names this module will put on the
# wire. The auth context is built by a credential strategy, but a strategy is provider
# config and this list is the module's own last word — so a future strategy (or a
# mis-wired one) cannot smuggle a cookie, a proxy header, or a second credential into a
# credentialed dial. Compared case-insensitively: HTTP field names are case-insensitive,
# so an allowlist that only matched lowercase would be trivially bypassed by spelling.
_ALLOWED_AUTH_HEADERS = frozenset({"x-api-key", "authorization"})


def _discovery_headers(auth_headers: Mapping[str, str], api_version: str) -> dict[str, str]:
    """The exact headers for a credentialed catalog dial: allowlisted auth + version.

    # WHY filter rather than trust: ``auth_headers`` crosses a port boundary. Filtering
    # here means the set of header names that can reach Anthropic is a property of THIS
    # module, readable in one place, instead of a property of whatever built the mapping.
    """
    allowed = {
        name: value for name, value in auth_headers.items() if name.lower() in _ALLOWED_AUTH_HEADERS
    }
    if not allowed:
        # Fail closed with a sanitized reason. Dialing a credentialed catalog with no
        # credential would spend a request to learn 401, and the honest answer — "this
        # profile produced no usable auth header" — is already known here.
        raise DiscoveryError("missing_credential")
    # ``anthropic-version`` last: it is gateway-owned protocol framing, so it must not be
    # overridable by whatever the auth context happened to carry.
    return {**allowed, "anthropic-version": api_version}


async def fetch_live_model_ids(
    *,
    client: DiscoveryHttpClient,
    limits: DiscoveryLimits | None = None,
    auth_headers: Mapping[str, str],
    api_version: str,
) -> tuple[str, ...]:
    """Every publishable-candidate model id in the catalog, or a sanitized ``DiscoveryError``.

    Walks ``has_more``/``last_id`` under ONE aggregate deadline. All-or-nothing: a failure on
    any page discards everything, so the caller's cache can never store a partial catalog as
    fresh.

    ``auth_headers`` are already-built provider auth headers (from the owning profile's
    ``CredentialStrategy``); this function never reads or decrypts a stored credential and
    never learns whose key it is holding.

    # AIDEV-NOTE (credential exposure, measured not assumed): the filtered mapping below is
    # a live local of this frame for the whole walk and is re-bound as a parameter in
    # ``fetch_discovery_json`` and in the adapter. So IF a locals-capturing error reporter
    # were ever added (sentry-sdk, for one, captures frame locals by default), it would see
    # the plaintext there. None is installed today and nothing in ``src/`` renders locals;
    # ``ModelCatalog``/``ProfileModelCatalog`` also sanitize an escaping exception to its
    # type name. THAT is what keeps this bounded — not any parameter's static type.
    """
    bounds = limits if limits is not None else DiscoveryLimits()
    headers = _discovery_headers(auth_headers, api_version)
    # INVARIANT (D7): first occurrence wins and upstream order survives — dict keys preserve
    # insertion order, so this dedupes without sorting or folding anything.
    collected: dict[str, None] = {}
    # INVARIANT (CC-12): the SET of every cursor seen, not just the previous one. Tracking
    # only the previous cursor lets a period-2 cycle (a -> b -> a) spin to the page cap.
    # The set is bounded by _MAX_PAGES, so it cannot itself grow without limit.
    seen_cursors: set[str] = set()
    try:
        async with asyncio.timeout(_AGGREGATE_TIMEOUT_S):
            cursor: str | None = None
            pages = 0
            while True:
                # INVARIANT: the cap refuses BEFORE dialing page N+1, so a runaway chain
                # costs at most _MAX_PAGES dials on a request-path refresh.
                if pages >= _MAX_PAGES:
                    raise DiscoveryError("model_catalog_truncated")
                pages += 1
                payload = await fetch_discovery_json(
                    _page_url(cursor),
                    allowed_origins=ALLOWED_ORIGINS,
                    client=client,
                    limits=bounds,
                    headers=headers,
                )
                ids, has_more, next_cursor = parse_catalog_page(payload)
                for model_id in ids:
                    collected.setdefault(model_id, None)
                if len(collected) > _MAX_CATALOG_MODELS:
                    raise DiscoveryError("model_catalog_too_large")
                if not has_more:
                    break
                if next_cursor is None:
                    # ``parse_catalog_page`` guarantees a cursor whenever has_more is true,
                    # so this is unreachable through it today. It is a RAISE and not an
                    # ``assert`` on purpose: asserts vanish under ``-O``, and a future
                    # loosening of the parser must fail this refresh closed rather than
                    # silently restart the walk from page one and publish a short catalog.
                    raise DiscoveryError("malformed_json")
                if next_cursor in seen_cursors:
                    # No progress: upstream is repeating a cursor, so the remaining pages
                    # are unreachable and this read is incomplete — not merely slow.
                    raise DiscoveryError("model_catalog_truncated")
                seen_cursors.add(next_cursor)
                cursor = next_cursor
    except TimeoutError:
        # sanitized to the same token the per-page envelope uses: callers need ONE
        # failure vocabulary, not two.
        raise DiscoveryError("timeout") from None

    if not collected:
        # INVARIANT: an empty catalog is indistinguishable from a broken read, so it must
        # never be cached as a fresh, legitimately-empty listing that evicts a good one.
        raise DiscoveryError("model_catalog_empty")
    return tuple(collected)


def publishable_model_ids(ids: Iterable[str]) -> tuple[str, ...]:
    """The safe-shaped, order-preserving subset of walked catalog ids.

    INVARIANT: a publication FILTER, not the census. Its job is to drop shapes this gateway
    cannot publish (see ``_SAFE_ID_RE``); whether the READ was complete is judged by the
    walk's own guards. Zero survivors still fail closed, because an empty listing must not
    be cached as fresh and evict a good snapshot over nothing but an upstream shape change.

    # WHY no separate publish cap: ``fetch_live_model_ids`` already refuses a catalog over
    # ``_MAX_CATALOG_MODELS``, and a filter cannot grow its input.
    """
    published = tuple(model_id for model_id in ids if _is_safe_token(model_id))
    if not published:
        raise DiscoveryError("model_catalog_empty")
    return published


def _explicit_operator_entries(settings: AnthropicPluginSettings) -> tuple[ModelEntry, ...]:
    """Operator-configured entries, or none when ``models`` is the compiled default.

    # WHY ``model_fields_set``: pydantic records a field there only when a value arrived
    # from the constructor or the environment — a ``default_factory`` fill does not
    # register. That is the exact line between "the operator asked for these models"
    # (survive every healthy snapshot) and "compiled fallback seeds" (replaced entirely by
    # a healthy snapshot, so a retired alias actually disappears).
    """
    if "models" not in settings.model_fields_set:
        return ()
    return tuple(settings.models)


def live_listing_entries(
    settings: AnthropicPluginSettings, model_ids: tuple[str, ...]
) -> tuple[ModelEntry, ...]:
    """The finished healthy-snapshot listing: operator entries first, then discovered ids.

    INVARIANT (D8): the PROVIDER owns this merge. Core receives finished rows and never
    learns which entries were seeds, so seed provenance cannot leak into route logic.

    INVARIANT (D7): discovered ids keep upstream order, unfolded and unsorted — aliases and
    date-stamped snapshots are both published, both dispatch, and neither is derived from
    the other.

    # WHY the canonical id is the dedupe key for BOTH sides: an operator may configure
    # ``anthropic/claude-opus-5`` while upstream returns ``claude-opus-5``. Those denote ONE
    # gateway id, so comparing raw ``model_name`` would publish a duplicate row.
    """
    operator = _explicit_operator_entries(settings)
    seen = {
        canonical_model_id(custom_llm_provider=_PROVIDER, model_name=entry.model_name)
        for entry in operator
    }
    discovered: list[ModelEntry] = []
    for model_id in model_ids:
        canonical = canonical_model_id(custom_llm_provider=_PROVIDER, model_name=model_id)
        if canonical in seen:
            continue
        seen.add(canonical)
        discovered.append(
            ModelEntry(model_name=model_id, litellm_params={"model": f"{_PROVIDER}/{model_id}"})
        )
    return operator + tuple(discovered)
