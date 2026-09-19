"""The engine's ONE policy for error text that crosses a public boundary.

Two boundaries publish a failed run's diagnosis to someone outside the engine: the benchmark
result contract (`benchmarks/aggregation.py::public_error`) and the transactional HTTP problem
body (`rest/routes.py::_terminal_response`). Both face the same hazard — the `message` on a
terminal error is `str(exc)` of whatever exception ended the run, which for any provider-facing
adapter is the provider's own text: a response body, a refusal, an auth error quoting the key
that failed. A second, divergent copy of the screen is how one of those boundaries quietly stops
matching the other, so there is one copy, here, and it is a shared leaf both halves may import.

Two tools, with different jobs:

- :func:`public_message` bounds and screens a message. It cannot tell who wrote the text; it
  caps it, flattens it to one line, and withholds it entirely when it looks like an internal
  path, a traceback, or a credential.
- :data:`ENGINE_ERROR_CODES` is the closed set of error codes the engine RESERVES to itself.
  A boundary may treat one of these as evidence that url4 core or the engine's own control plane
  authored the accompanying message — and, precisely because a boundary may, no code lifted off
  an upstream response is allowed to be one of them (`runner/connector.py::_raise_for_status`
  enforces that end).
"""

from __future__ import annotations

import re

__all__ = ["ENGINE_ERROR_CODES", "public_identifier", "public_message"]

# Codes whose message is authored by url4 core or the engine's own control plane ABOUT THE
# CALLER'S OWN EXPRESSION or the engine's own limits, and whose raise sites interpolate no value
# that can have come from a remote source.
#
# INVARIANT: membership requires auditing every raise site of the code AND every class carrying
# it as a default. A CODE IS NOT AN AUTHOR — see the two ways that premise broke below. Adding a
# code also forbids an upstream from ever reporting it
# (`runner/connector.py::_raise_for_status` enforces that end).
#
# Audited 2026-09-17 (OME-941 round 3). REMOVED, each with the raise site that disproved it:
#
#   - `malformed_source`       class default of BOTH `ParseError` (genuinely the caller's
#                              expression) AND `CollectionError`, whose io/layer.py sites embed
#                              the FETCHED BODY: `f"...not an iterable collection: {body[:80]!r}"`
#                              (layer.py:206) and `f"invalid NDJSON line: {line[:80]!r}"` (:243).
#                              One code, two authors — no allowlist entry can be right for it.
#   - `unknown_processor`      dag/processor.py:96 embeds `{resolved!r}`, which is
#                              `(await spawn(value)).strip()` — a MODEL OUTPUT.
#   - `unrenderable`           core/render.py:112 embeds `{text!r}`, the rendered form of an AST
#                              that may carry a fetched value.
#   - `expansion_not_iterable` dag/nodes.py:570 embeds `{exc}` of the CollectionError above.
#
# Deliberately absent from the start:
#   - `resolution_failed`  the I/O layer, and `ResolutionError`'s class default; its message can
#                          embed a remote response or a fetched URL.
#   - `internal_error`     `str()` of an arbitrary exception, by definition unvouched.
#   - `aigateway_*`, `provider_refusal`, `model_*`, `judge_*`, `*_grading_failed`, … — every
#                          provider-adjacent code in the executor and the benchmark adapters.
ENGINE_ERROR_CODES: frozenset[str] = frozenset(
    {
        # ScopeError — names a `$name`/`$N` from the caller's own expression.
        "unbound_reference",
        # CycleError — graph shape only.
        "cycle_detected",
        # io/static.py, peer/server.py — `{identity!r}`, `{node.name!r}`, both caller-supplied.
        "unknown_identity",
        # dag/nodes.py:548 — a duration and a literal, no values.
        "timeout",
        # runner/executor.py:574 — two byte counts, no values.
        "result_too_large",
    }
)


def public_identifier(value: object) -> str | None:
    """Return ``value`` if it is a short, plain identifier, else ``None``."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()[:80]
    return normalized if re.fullmatch(r"[A-Za-z0-9_.:-]+", normalized) else None


def public_message(value: object, *, default: str) -> str:
    """Return a bounded, one-line ``value``, or ``default`` when it must be withheld."""
    if not isinstance(value, str) or not value.strip():
        return default
    normalized = " ".join(value.split())[:200]
    lowered = normalized.casefold()
    internal_markers = (
        "traceback (most recent call last)",
        'file "',
        "/users/",
        "/private/",
        "/tmp/",
        "/var/",
        "/home/",
    )
    return (
        default
        if any(marker in lowered for marker in internal_markers)
        or any(pattern.search(normalized) for pattern in _SENSITIVE_ERROR_PATTERNS)
        else normalized
    )


_SENSITIVE_ERROR_PATTERNS = (
    # Absolute/relative POSIX, drive-letter Windows, and UNC paths. Public
    # diagnostics retain the bounded default instead of trying to redact an
    # unbounded path grammar piecemeal.
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
