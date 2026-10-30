"""The ONE screen for provider-authored error text a client may read (OME-1136).

FEATURE (OME-1136): a rejected model call names its cause. Before this, every provider
rejection rendered as the same gateway sentence, so an unsupported `temperature`, an account
gate and an empty credit balance were indistinguishable in the report.
STORY: as a researcher, I read the failed case in `report.json` and see "Unsupported
parameter: 'temperature'" instead of "the upstream provider returned an error".

What it does, in order (owner decision, Linear comment 2026-10-02):
1. READ an allowlist only: the body's `error.message`, and — when that is vacuous — ONE level of
   OpenRouter's `error.metadata.raw` (its `error.message` only). Never `flagged_input`,
   `reasons`, headers, request ids, or any other key.
2. NORMALISE: NFKC, drop control/format/private/surrogate/unassigned characters, one line.
3. REDACT IN PLACE: URLs, emails, key/token shapes, org/project ids, long ids, paths, and long
   quoted spans (request echo) become placeholders.
4. CAP at 140 characters on a word boundary.
5. WITHHOLD the whole text (→ ``None`` → the caller's generic message) when the engine's
   `public_message` would withhold it anyway (Gate 1), or when the call's own credential
   appears in it (Gate 2).

INVARIANT: pure and total — every public function returns ``None`` instead of raising, so a
hostile body can never turn a mapped provider error into an unmapped 500.
INVARIANT: nothing here logs. The relayed text reaches the client only, never a log line
(OME-968's class-name-only posture).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

UPSTREAM_MESSAGE_CAP = 140
"""WHY 140: the longest generic prefix the gateway composes in front of the upstream text is
"The upstream provider reported insufficient credits (402): " — 59 characters — and the
engine's `public_message` caps at 200. 59 + 140 = 199, so the engine never truncates further."""

_MAX_BODY_BYTES = 16 * 1024
_MAX_RAW_CHARS = 8 * 1024
_MAX_CAUSE_DEPTH = 8
_MIN_CREDENTIAL_CHARS = 8

RELAY_CODES = frozenset(
    {"bad_request", "provider_error", "insufficient_credits", "provider_unavailable"}
)
"""WHY not `auth_required` (401): that detail is persisted into the credential's error state
(`record_dispatch_failure`), and auth bodies are where keys get echoed. WHY not `rate_limited`
(429): those messages carry org ids and limits and add little. Owner decision 2026-10-02."""

# INVARIANT: gateway-authored, one per machine code — never provider text. Owned here (not in
# `routes/chat_dispatch.py`) so the central LiteLLM path and the custom-handler plugins render
# the same sentence for the same code (#1233 review).
PROVIDER_ERROR_MESSAGES: Mapping[str, str] = {
    "bad_request": "The upstream provider rejected the request.",
    "auth_required": "The stored provider credential was rejected.",
    "rate_limited": "The upstream provider is rate limiting requests.",
    "provider_unavailable": "The upstream provider is temporarily unavailable.",
    "provider_error": "The upstream provider returned an error.",
    # OME-927: a 402 (out of credits) is not a generic provider fault — the
    # status itself is safe to name (it carries no provider text), so the
    # dedicated message tells the caller they need to top up, without str(exc).
    "insufficient_credits": "The upstream provider reported insufficient credits.",
}

# WHY (#1233 review): the plugin twin of RELAY_CODES — the statuses the central path maps to
# `auth_required` / `rate_limited`, enforced by STATUS because a plugin may label them otherwise
# (Codex reports every failure as `provider_error`).
_WITHHELD_PLUGIN_STATUSES: Mapping[int, str] = {401: "auth_required", 429: "rate_limited"}

# WHY a vacuous set: OpenRouter wraps a downstream failure as "Provider returned error" and
# tucks the real text into `metadata.raw`; litellm's converter substitutes "Error in response
# object" when the body had no message at all. Relaying either says nothing.
_VACUOUS = frozenset({"", "provider returned error", "error in response object"})

_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn"})

# INVARIANT (ReDoS): every rule that may start inside a long run is LENGTH-BOUNDED (DNS label
# ≤ 63, ≤ 32 labels, scheme ≤ 32) or starts at a run boundary of its OWN class (email), so each
# start costs bounded work and a 16 KiB run of `1.` / `a.` / `x` stays linear. WHY no host
# lookbehind: one wider than the start class let a leading `.` shield the host
# (`.internal.example/admin`) — a redaction bypass.
# INVARIANT: applied in THIS order. URLs go before emails and paths, or `https://a/b` would
# leave a `[path]` behind its scheme; key shapes go before the long-id rule, so a known key is
# named `[redacted]` rather than `[id]`.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b[a-z][a-z0-9+.-]{0,31}://\S+"), "[url]"),
    (re.compile(r"(?i)\bwww\.\S+"), "[url]"),
    # WHY (#1233 review): a provider-internal host needs no scheme — `internal.example/admin`,
    # `api.corp:8443/v2`. A dotted name with an alphabetic TLD followed by `/` or `:<port>` is
    # treated as a URL; a bare dotted name (`gpt-4.1`, `file.json`) without either is not.
    (
        re.compile(r"(?i)\b(?:[a-z0-9-]{1,63}\.){1,32}[a-z]{2,63}\.?(?::\d+)?[/\\]\S*"),
        "[url]",
    ),
    (re.compile(r"(?i)\b(?:[a-z0-9-]{1,63}\.){1,32}[a-z]{2,63}\.?:\d+\b"), "[url]"),
    # WHY (#1233 second review): IP literals and localhost are internal by definition, with or
    # without a port/path — bracketed (`[fd00::1]:8443`) and bare (`fd00::1`, `10.0.0.1/admin`).
    (re.compile(r"\[[0-9A-Fa-f.]{0,4}:[0-9A-Fa-f:.]{1,45}\](?::\d+)?(?:/\S*)?"), "[url]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:/\S*)?"), "[url]"),
    # WHY (parser differential): HTTP clients also accept short (`10.1`) and hex (`0x0a.0.0.1`,
    # `0x7f000001`) IPv4 forms. Only redacted before a port or a `/`-letter path, so ratios and
    # versions (`3.5/5`, `1.2`) still relay.
    (
        re.compile(
            r"(?i)\b(?:0x[0-9a-f]{1,8}|(?:0x[0-9a-f]{1,8}|\d{1,10})"
            r"(?:\.(?:0x[0-9a-f]{1,8}|\d{1,10})){1,3})"
            r"(?=:\d|[/\\][a-z])(?::\d+)?(?:[/\\]\S*)?"
        ),
        "[url]",
    ),
    (
        re.compile(
            r"(?i)(?<![\w:.])(?=[0-9a-f:]{0,39}::|(?:[0-9a-f]{1,4}:){7})(?=:*[0-9a-f])"
            r"[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?:/\d+)?(?![\w:])"
        ),
        "[url]",
    ),
    (re.compile(r"(?i)\blocalhost(?::\d+)?(?:/\S*)?"), "[url]"),
    # WHY a run-boundary lookbehind here (not a bound): the lookbehind class IS the local-part
    # class, so the match starts exactly at the run start — linear, and no prefix is left.
    (re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]{1,63}(?:\.[\w-]{1,63}){1,127}"), "[email]"),
    (re.compile(r"(?i)\bbearer\s+\S+"), "[redacted]"),
    (re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+"), "[redacted]"),
    (re.compile(r"\bsk-[\w-]{8,}"), "[redacted]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted]"),
    (re.compile(r"\bAIza[\w-]{35}"), "[redacted]"),
    (re.compile(r"\bgh[pousr]_\w{20,}"), "[redacted]"),
    (re.compile(r"\bxox[abprs]-\S+"), "[redacted]"),
    (re.compile(r"\b(?:org|proj)-[A-Za-z0-9]{8,}"), "[account]"),
    (re.compile(r"\b[A-Za-z0-9]{32,}\b"), "[id]"),
    # WHY `=` and `:` (#1233 review): `endpoint=/v1/internal/admin`, `path:/srv/app` are paths.
    (re.compile(r"(?:^|(?<=[\s'\"(=:]))\.{0,2}/\S+"), "[path]"),
    # WHY (#1233 second review): Windows drive and UNC paths, after the same delimiters.
    (re.compile(r"(?:^|(?<=[\s'\"(=:]))(?:[A-Za-z]:\\|\\\\)\S+"), "[path]"),
    (re.compile(r"'[^']{41,}'|\"[^\"]{41,}\"|`[^`]{41,}`"), "'[…]'"),
)

# FEATURE (owner decision 2026-10-16, #1233 security passes): the fail-closed BACKSTOP behind
# `_REDACTIONS`. Redaction is a denylist and three review rounds each found a host form it missed;
# if an address-shaped token SURVIVES redaction, the whole text is withheld (generic sentence).
# INVARIANT: every pattern is linear (bounded or single-start) and runs on the uncapped text.
_ADDRESS_RESIDUE: tuple[re.Pattern[str], ...] = (
    # A bare hostname: dotted, hyphen/alnum labels, alphabetic TLD. `_` is excluded on purpose —
    # hostnames cannot carry it, JSON paths and parameters (`response_format.type`) do.
    re.compile(r"(?i)(?<![\w.-])(?:[a-z0-9-]{1,63}\.){1,32}[a-z]{2,63}(?![\w-])"),
    # Percent-encoding (`%2F`) and IPv6 zone ids (`%eth0`); a bare `100%` before a space relays.
    re.compile(r"%[0-9A-Za-z]"),
    # IPv6 residue — `::` next to a hex digit; a bare `::` (C++ scope operator) is not one.
    re.compile(r"(?i)[0-9a-f]::|::[0-9a-f]"),
    # WHY (#1233 review at 39e0c0452): the path rule stops at whitespace, so a Windows path with
    # a space (`C:\Users\Jane Doe\secret`) leaves a backslash suffix. Any surviving backslash
    # withholds — with or without an extension.
    re.compile(r"\\"),
    re.compile("[\u3002]"),  # ideographic full stop — an IDNA dot NFKC does not fold
    re.compile(r"\w@"),  # an email/userinfo fragment left behind
)


def _address_survives(text: str) -> bool:
    return any(pattern.search(text) for pattern in _ADDRESS_RESIDUE)


# INVARIANT (Gate 1): a VERBATIM port of the engine's `error_text.public_message` withhold
# predicate (`apps/screamingface-engine/src/screamingface_engine/error_text.py`). The apps do
# not import each other, so parity is pinned by one shared fixture run through both
# (`tests/fixtures/provider_error_relay/public_message_parity.json`). Without this gate, a
# message the engine withholds silently becomes the engine's generic default in the report.
_ENGINE_INTERNAL_MARKERS = (
    "traceback (most recent call last)",
    'file "',
    "/users/",
    "/private/",
    "/tmp/",
    "/var/",
    "/home/",
)
_ENGINE_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(?:^|[\s'\"(])(?:/|\.{1,2}/)[^\s'\")]+"),
    re.compile(r"(?i)(?:^|[\s'\"(])[a-z]:\\[^\s'\")]+"),
    re.compile(r"(?i)(?:^|[\s'\"(])\\\\[^\\\s]+\\[^\s'\")]+"),
    re.compile(
        r"(?i)(?:^|[^A-Za-z0-9])(?:[A-Za-z0-9]+[_-])*"
        r"(?:authorization|password|passwd|pwd|secret|token|cookie|api[_-]?key|"
        r"access[_-]?key)\s*[:=]"
    ),
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_CREDENTIAL_HEADER = re.compile(r"(?i)auth|key|token|secret|cookie")


def engine_would_withhold(text: str) -> bool:
    """True when the engine's `public_message` would replace ``text`` with its default."""
    if not text.strip():
        return True
    normalized = " ".join(text.split())[:200]
    lowered = normalized.casefold()
    return any(marker in lowered for marker in _ENGINE_INTERNAL_MARKERS) or any(
        pattern.search(normalized) for pattern in _ENGINE_SENSITIVE_PATTERNS
    )


def credential_values(body: Mapping[str, Any]) -> tuple[str, ...]:
    """The dispatch credential values sealed into a provider body (Gate 2's forbidden set).

    WHY from the body: `apply_authorization` seals a Bearer into `api_key` and every other
    provider header into `extra_headers`; the body is the one place the plugin and the route
    both hold. Only credential-named headers count — a benign header value (a title, a
    referer) would otherwise withhold every message that happens to mention it.
    """
    try:
        return tuple(
            value.strip()
            for value in sealed_values(body)
            if len(value.strip()) >= _MIN_CREDENTIAL_CHARS
        )
    except Exception:
        return ()


def sealed_values(body: Mapping[str, Any]) -> list[str]:
    """Every credential value sealed into ``body``, as sealed and of any length.

    Raises whatever an unreadable body raises: `credential_values` turns that into no values,
    and the shared cache's guard into a refusal to store.
    """
    found: list[str] = []
    api_key = body.get("api_key")
    if isinstance(api_key, str):
        found.append(api_key)
    headers = body.get("extra_headers")
    if isinstance(headers, Mapping):
        for name, value in headers.items():
            if isinstance(name, str) and isinstance(value, str) and _CREDENTIAL_HEADER.search(name):
                found.append(value)
                if value.lower().startswith("bearer "):
                    found.append(value.split(" ", 1)[1])
    return found


def _contains_credential(text: str, forbidden: Iterable[str]) -> bool:
    return any(value and value in text for value in forbidden)


def _normalise(text: str) -> str:
    kept: list[str] = []
    for char in unicodedata.normalize("NFKC", text):
        category = unicodedata.category(char)
        if char.isspace() or category in {"Zl", "Zp"}:
            kept.append(" ")
        elif category not in _DROPPED_CATEGORIES:
            kept.append(char)
    return " ".join("".join(kept).split())


def _redact(text: str) -> str:
    for pattern, placeholder in _REDACTIONS:
        text = pattern.sub(placeholder, text)
    return text


def _cap(text: str) -> str:
    if len(text) <= UPSTREAM_MESSAGE_CAP:
        return text
    cut = text[: UPSTREAM_MESSAGE_CAP - 1]
    space = cut.rfind(" ")
    # WHY the half-cap floor: one 100-character token would otherwise truncate to almost nothing.
    if space >= UPSTREAM_MESSAGE_CAP // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def sanitize_upstream_text(text: object, *, forbidden: Iterable[str] = ()) -> str | None:
    """Normalise, redact in place and cap ``text``; ``None`` when it must be withheld.

    INVARIANT: sanitize FIRST, truncate second — truncating first could split a key and leave
    half of it unmatched by every redaction rule.
    """
    try:
        if not isinstance(text, str):
            return None
        forbidden = tuple(forbidden)
        # Gate 2, on the raw text: the call's own credential, in any shape.
        if _contains_credential(text, forbidden):
            return None
        redacted = _redact(_normalise(text))
        if _address_survives(redacted):
            return None
        result = _cap(redacted)
        if not result or _contains_credential(result, forbidden) or engine_would_withhold(result):
            return None
        return result
    except Exception:
        return None


def _vacuous(value: object) -> bool:
    return not isinstance(value, str) or value.strip().casefold() in _VACUOUS


def _raw_inner_message(metadata: Mapping[str, Any]) -> str | None:
    raw = metadata.get("raw")
    if not isinstance(raw, str) or len(raw) > _MAX_RAW_CHARS:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    inner = parsed.get("error") if isinstance(parsed, dict) else None
    message = inner.get("message") if isinstance(inner, dict) else None
    # INVARIANT: ONE level only — an inner `metadata.raw` is never followed.
    return None if _vacuous(message) else message


def message_from_error_object(error: object) -> str | None:
    """The allowlisted text of one provider `error` object, un-sanitized.

    Reads `message`; when vacuous, one level of `metadata.raw`. Nothing else.
    WHY no `metadata.provider_name` suffix (the design draft proposed one): the owner decision
    allowlists `error.message` + one level of `metadata.raw` only, and prior tests pin
    `provider_name` as never echoed (e.g. `test_openrouter_no_eligible_endpoint.py`).
    """
    if not isinstance(error, Mapping):
        return None
    message = error.get("message")
    metadata = error.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    if _vacuous(message):
        message = _raw_inner_message(metadata)
    return message if isinstance(message, str) else None


def _nested_error(payload: object) -> object:
    """The `error` object of a RAW wire body; ``None`` when it does not nest one.

    INVARIANT (#1233 second review): a raw body's text is read ONLY from `error`. A top-level
    `message` is an unknown shape and yields ``None`` — the caller keeps its generic sentence.
    """
    error = payload.get("error") if isinstance(payload, Mapping) else None
    return error if isinstance(error, Mapping) else None


def _sdk_error_object(body: Mapping[str, Any]) -> object:
    # WHY the fallback: the OpenAI SDK's `exc.body` is ALREADY the inner error object. It is
    # allowed for this structured carrier only, never for a raw wire body.
    error = body.get("error")
    return error if isinstance(error, Mapping) else body


def _json_payload(content: object) -> object:
    if isinstance(content, str):
        content = content.encode("utf-8", errors="replace")
    if not isinstance(content, bytes) or not content or len(content) > _MAX_BODY_BYTES:
        return None
    try:
        return json.loads(content)
    except ValueError:
        return None


def _response_payload(response: object) -> object:
    if not isinstance(response, httpx.Response):
        return None
    try:
        content = response.content
    except httpx.ResponseNotRead:
        return None
    return _json_payload(content)


def error_message_from_body(content: object) -> str | None:
    """The allowlisted message of a provider error body, un-sanitized; else ``None``.

    FEATURE (OME-1136, #1233 review): the Codex and Gemini handlers used to append up to 500
    bytes of the RAW body, so an HTML error page (names, ids, internal URLs) reached the client.
    INVARIANT: only a bounded JSON OBJECT is read, and only its nested `error.message` (one level
    of `metadata.raw`); HTML, arrays, invalid JSON, a top-level `message` and unknown shapes yield
    ``None`` and the caller keeps its generic sentence. Total — never raises.
    """
    try:
        payload = _json_payload(content)
        if not isinstance(payload, Mapping):
            return None
        return message_from_error_object(_nested_error(payload))
    except Exception:
        return None


def error_message_from_response(response: object) -> str | None:
    """`error_message_from_body` of an `httpx.Response`; ``None`` for anything else or unread."""
    try:
        if not isinstance(response, httpx.Response):
            return None
        return error_message_from_body(response.content)
    except Exception:
        return None


def _cause_chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(seen) < _MAX_CAUSE_DEPTH:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _exception_error_object(exc: BaseException) -> object:
    """The provider's error object, from the exception's structured carriers only.

    WHY the cause chain: litellm 1.87's OpenRouter exceptions carry a SYNTHETIC empty
    `response`; the wire body survives only on the chained `httpx.HTTPStatusError` (measured
    against real `litellm.acompletion`, see the OME-1136 ledger).
    INVARIANT: never regex-parse `str(exc)` / `exc.message` — that is litellm's wrapper text
    and the known leak vector.
    """
    for link in _cause_chain(exc):
        payload = _response_payload(getattr(link, "response", None))
        if payload is not None:
            return _nested_error(payload)
        body = getattr(link, "body", None)
        if isinstance(body, Mapping):
            return _sdk_error_object(body)
    return None


def relayable_upstream_message(exc: BaseException, *, forbidden: Iterable[str] = ()) -> str | None:
    """The sanitized provider explanation carried by ``exc``, or ``None`` (→ generic message)."""
    try:
        text = message_from_error_object(_exception_error_object(exc))
        return sanitize_upstream_text(text, forbidden=forbidden)
    except Exception:
        return None


def relayed_detail(
    detail: dict[str, Any], *, status: int | None, upstream_message: str | None
) -> dict[str, Any]:
    """``detail`` plus the ADDITIVE relay fields, or ``detail`` itself when nothing relays.

    INVARIANT: the fallback is the very same object — byte-identical to the pre-OME-1136 body,
    no new keys. The taxonomy (`code`) is never touched; OME-302 owns that.
    """
    code = detail.get("code")
    base = detail.get("message")
    if (
        upstream_message is None
        or status is None
        or code not in RELAY_CODES
        or not isinstance(base, str)
    ):
        return detail
    return {
        **detail,
        "message": f"{base.rstrip('.')} ({status}): {upstream_message}",
        "upstream_status": status,
        "upstream_message": upstream_message,
    }


PLUGIN_FALLBACK_MESSAGE = PROVIDER_ERROR_MESSAGES["provider_error"]


def plugin_error_message(message: object, *, status: object, forbidden: Iterable[str] = ()) -> str:
    """A custom-handler plugin's `CustomLLMError.message`, screened (OME-1136 decision 3).

    WHY: the plugins relayed that message verbatim. It now goes through the same screen as the
    gateway relay; a withheld text becomes the gateway's generic `provider_error` sentence.
    INVARIANT (#1233 review): a 401 or 429 never relays provider text — owner decision
    2026-10-02, as RELAY_CODES on the central path — it renders the gateway sentence instead.
    """
    withheld = _WITHHELD_PLUGIN_STATUSES.get(status) if isinstance(status, int) else None
    if withheld is not None:
        return PROVIDER_ERROR_MESSAGES[withheld]
    return sanitize_upstream_text(message, forbidden=forbidden) or PLUGIN_FALLBACK_MESSAGE
