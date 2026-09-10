"""The W3C trace-context shape, as aigateway enforces it (OME-1120).

INVARIANT: this rule must stay identical to `url4.streaming.trace` and to the regex
`packages/screamingface` restates in `tests/e2e/test_correlation_chain.py`. All three services
have to agree on what a valid traceparent is, or an id one accepts is dropped by the next hop
and the correlation silently ends there.

WHY it is copied rather than imported: `apps/aigateway` does not depend on `url4`, and a
distribution dependency for a six-line regex would be the tail wagging the dog. The client made
the same call in `OME-967`. The cost is a rule in three places; the mitigation is that each
copy's rejection table is asserted, so a divergence fails a test rather than being adopted
silently.

SECURITY: the inbound header is CALLER-CONTROLLED. Adopting a malformed or attacker-chosen
value would let a caller pick the correlation key that other requests are grouped under, so
`adopt_or_mint_trace_id` replaces anything that does not parse. Never "clean up" a bad value
into a usable one — mint instead.
"""

from __future__ import annotations

import re
import secrets

TRACE_ID_LEN = 32
SPAN_ID_LEN = 16

_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")
"""Version `00` only, lowercase hex only — both deliberate.

A future version prefix is not forward-compatible-by-guessing: `01` may carry different
fields, and treating it as `00` would parse a value whose meaning we do not know. Uppercase is
rejected because the W3C spec fixes lowercase, and accepting both would make two spellings of
one id that never match as strings.
"""

_ALL_ZERO_TRACE = "0" * TRACE_ID_LEN
_ALL_ZERO_SPAN = "0" * SPAN_ID_LEN


def parse_trace_id(value: str | None) -> str | None:
    """The 32-hex trace id inside a well-formed traceparent, or None.

    The two all-zero rejections are not pedantry: the spec defines them as invalid precisely
    because they are what a broken or lazy implementation emits, and an all-zero id would
    happily group every such request together under one meaningless key.
    """
    if not value:
        return None
    match = _TRACEPARENT_RE.match(value)
    if match is None or match.group(1) == _ALL_ZERO_TRACE or match.group(2) == _ALL_ZERO_SPAN:
        return None
    return match.group(1)


def new_trace_id() -> str:
    """A fresh 128-bit trace id."""
    return secrets.token_hex(TRACE_ID_LEN // 2)


def adopt_or_mint_trace_id(value: str | None) -> str:
    """Join the caller's trace when it is well-formed; otherwise start our own.

    INVARIANT: never returns the input when the input did not parse, and never returns None.
    Returning the input would let a caller choose the key; returning None would leave the
    request anonymous — and an anonymous request in the gateway is exactly the state this
    phase exists to remove.
    """
    return parse_trace_id(value) or new_trace_id()


__all__ = [
    "SPAN_ID_LEN",
    "TRACE_ID_LEN",
    "adopt_or_mint_trace_id",
    "new_trace_id",
    "parse_trace_id",
]
