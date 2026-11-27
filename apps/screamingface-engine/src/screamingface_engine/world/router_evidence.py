"""Reading a Router classifier's output into C6 evidence (contracts C4/C5, Unit 5.2).

FEATURE: Router Recipe extension. DECIDE reads three kinds of classifier output: an llm reply
(untrusted model text), the E4c KEYWORDS result for a regex source (Engine-authored JSON), and a
url4 ``collect`` error row for a call that failed. This module turns each into the policy's
evidence or a bounded failure; it makes no call and reads no state.

INVARIANT: a model reply is untrusted. It can select declared labels only, never raises, and
leaves at most 32 unknown tokens of at most 64 characters each.
INVARIANT: a failure keeps a bounded code and its permanence only; a row's message is dropped,
and a Router code never comes from a row (C11: a body cannot claim an ADMIT refusal).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeGuard

from screamingface_engine.benchmarks.failure_classes import (
    UPSTREAM_FALLBACK_CODE,
    benchmark_contract_error,
)
from screamingface_engine.combine.ports import selector_tokens
from screamingface_engine.error_text import ROUTER_CODES
from screamingface_engine.router_vocabulary import (
    CODE,
    MAX_UNKNOWN_CHARS,
    MAX_UNKNOWN_LABELS,
    strict_json,
)
from screamingface_engine.world.routing_policy import SelectorEvidence

_ROW_KEYS = frozenset({"kind", "message", "code", "retryable"})
_KEYWORDS_SUMMARY = "summary"


@dataclass(frozen=True, slots=True)
class RowFailure:
    """What a url4 ``collect`` error row says about a failed call: its code and permanence."""

    code: str
    permanent: bool


def read_llm_reply(reply: str, labels: Sequence[str], *, multi: bool) -> SelectorEvidence:
    """The declared labels an LLMClassifier reply names, in reply order, and its unknown tokens.

    E4c's tokenization, trimming, case-insensitive match, single-token read and reply bound
    (`combine.ports.selector_tokens`). Unlike E4c's Gate parser, recognized labels keep their
    first occurrence in the reply, and every distinct unknown token is kept, cut at 64
    characters; more than 32 is ``unparsed``.
    """
    tokens = selector_tokens(reply)
    if not tokens:
        return SelectorEvidence("llm", (), (), "unparsed")
    folded: dict[str, list[str]] = {}
    for label in labels:
        folded.setdefault(label.lower(), []).append(label)
    recognized: list[str] = []
    unknown: list[str] = []
    for token in tokens if multi else tokens[:1]:
        # WHY every label of one folding: C2 labels are case-sensitive, so a token names each
        # declared label it matches regardless of case; SDK labels are lowercase, as in E4c.
        named = folded.get(token.lower())
        found = named if named is not None else [token[:MAX_UNKNOWN_CHARS]]
        bucket = recognized if named is not None else unknown
        bucket.extend(item for item in found if item not in bucket)
    if len(unknown) > MAX_UNKNOWN_LABELS:
        return SelectorEvidence("llm", (), (), "unparsed")
    parse = "unrecognized" if unknown else "ok"
    return SelectorEvidence("llm", tuple(recognized), tuple(unknown), parse)


def read_keywords(text: str, labels: Sequence[str], *, multi: bool) -> SelectorEvidence:
    """A regex source's labels from the E4c KEYWORDS result, in KEYWORDS order.

    Raises:
        ResolutionError: `benchmark_contract_error`; the result is Engine-authored, so a
            malformed one is a defect, not a classifier outcome.
    """
    try:
        result = json.loads(text)
    except ValueError:
        result = None
    selectors = (
        [value for key, value in result.items() if key != _KEYWORDS_SUMMARY]
        if isinstance(result, dict)
        else []
    )
    found = (
        selectors[0].get("labels")
        if len(selectors) == 1 and isinstance(selectors[0], dict)
        else None
    )
    if not _declared_list(found, labels, multi=multi):
        raise benchmark_contract_error("router keywords result names one selector's labels")
    matched = tuple(found)
    return SelectorEvidence("regex", matched, (), "ok" if matched else "no_match")


def read_error_row(row: str) -> RowFailure | None:
    """The failure a url4 ``collect`` error row carries, or None for a text row.

    A row is an error row only in exactly the shape url4 writes (`_error_payload`): one
    ``error`` key holding a string ``kind`` and ``message``, an optional string ``code`` and an
    optional boolean ``retryable``. Anything else is text.
    """
    try:
        decoded = strict_json(row)
    except ValueError:
        return None
    error = decoded.get("error") if isinstance(decoded, dict) and len(decoded) == 1 else None
    if not isinstance(error, dict) or not _error_shape(error):
        return None
    retryable = error.get("retryable")
    return RowFailure(bounded_code(error.get("code")), permanent=retryable is not True)


def _error_shape(error: Mapping[str, object]) -> bool:
    return (
        set(error) <= _ROW_KEYS
        and isinstance(error.get("kind"), str)
        and isinstance(error.get("message"), str)
        and isinstance(error.get("code", ""), str)
        and isinstance(error.get("retryable", False), bool)
    )


def bounded_code(code: object) -> str:
    """The row's code, or `upstream_error` for none, an unbounded one, or a Router code."""
    if not isinstance(code, str) or CODE.fullmatch(code) is None or code in ROUTER_CODES:
        return UPSTREAM_FALLBACK_CODE
    return code


def _declared_list(found: object, labels: Sequence[str], *, multi: bool) -> TypeGuard[list[str]]:
    return (
        isinstance(found, list)
        and all(isinstance(label, str) and label in labels for label in found)
        and len(set(found)) == len(found)
        and (multi or len(found) <= 1)
    )


__all__ = [
    "RowFailure",
    "bounded_code",
    "read_error_row",
    "read_keywords",
    "read_llm_reply",
]
