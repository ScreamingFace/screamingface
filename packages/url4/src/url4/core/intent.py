"""Intent classification: the mode an intent runs in, read from its ABNF production.

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author I never declare a mode. The form of my intent decides
# it: a quoted or bare intent is a prompt, a `/path` or `url4://` intent is a
# code pointer, a nested expression stays computed, and any other scheme is
# refused (PRD §2.5, P1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from url4.core._annotations import read_query_tail
from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import parse_value
from url4.core.nodes import (
    Expression,
    IdentityRef,
    Iteration,
    Node,
    RelExpr,
    RelUrl,
    RemoteExpr,
    SelfRef,
    StructObject,
    Text,
    Url,
    VarRef,
)

_URL4_SCHEME = "url4://"


class IntentMode(StrEnum):
    """The mode an intent runs in (PRD §2.5)."""

    LLM = "llm"
    """A quoted or bare-token intent: a prompt for the processor."""
    COMPUTED = "computed"
    """A nested expression or iteration: the intent is computed, not read."""
    VALUE = "value"
    """A variable, struct, self or identity reference: the intent is a value."""
    RDS = "rds"
    """A relative URI, or a `url4://` URI: one call to a code pointer."""
    UNSUPPORTED = "unsupported"
    """Any other `scheme://` intent: refused with `unsupported_mode`."""
    LEGACY = "legacy"
    """An expression written in a path form (`/p(c)!x`, `/reduce()`): unchanged in 2.0."""


@dataclass(frozen=True)
class CodePointer:
    """A code pointer as written in the intent.

    ``path`` may hold ``$name`` segments, which are substituted at run time.
    ``query`` is the ``query-tail`` text as written (``""`` when absent), and
    ``params`` is that text read by :func:`~url4.core._annotations.read_query_tail`.
    ``authority`` is set only for a ``url4://`` pointer, on the remote node.
    """

    path: str
    query: str
    params: Mapping[str, str]
    authority: str | None = None


@dataclass(frozen=True)
class IntentClass:
    """The mode of one intent, with its code pointer when the mode is RDS."""

    mode: IntentMode
    pointer: CodePointer | None = None


# WHY: these node types decide the mode alone. `RelUrl` and `Url` are not here:
# `intent_atom` gives them to any `/…` or `scheme://…` text, so their mode comes
# from the production the grammar finds in that text (`classify_intent`).
_MODE_BY_NODE: Mapping[type[object], IntentMode] = {
    Text: IntentMode.LLM,
    Expression: IntentMode.COMPUTED,
    Iteration: IntentMode.COMPUTED,
    VarRef: IntentMode.VALUE,
    StructObject: IntentMode.VALUE,
    SelfRef: IntentMode.VALUE,
    IdentityRef: IntentMode.VALUE,
    RelExpr: IntentMode.LEGACY,
    RemoteExpr: IntentMode.LEGACY,
}


def classify_intent(atom: Node) -> IntentClass:
    """Classify a parsed intent atom (``intent_atom`` output) into its mode.

    Raises:
        ParseError: ``malformed_source`` for a URI intent the grammar refuses, for a
            code pointer whose query leaves ``query-tail``, and for a ``url4://``
            reference with no path.
    """
    if isinstance(atom, Url) and not atom.value.startswith(_URL4_SCHEME):
        return IntentClass(IntentMode.UNSUPPORTED)
    if not isinstance(atom, RelUrl | Url):
        return IntentClass(_MODE_BY_NODE.get(type(atom), IntentMode.LEGACY))
    return _uri_class(atom.value)


def _uri_class(text: str) -> IntentClass:
    # INVARIANT (plan L7): the grammar owns the production rules (path charset,
    # spec §8 rule 16, host and port). This module never re-derives them, so a
    # text is a code pointer exactly when the grammar reads it as a bare URI.
    production = _production(text)
    if isinstance(production, RelUrl):
        return _pointer(production.value, authority=None)
    if isinstance(production, Url):
        return _remote_pointer(production.value)
    return IntentClass(_MODE_BY_NODE.get(type(production), IntentMode.LEGACY))


def _production(text: str) -> Node | None:
    try:
        return parse_value(text)
    except ParseError as exc:
        # WHY: `/reduce()` is a call with no intent of its own, which the grammar
        # refuses as a value. It is the 1.5.1 reducer-route form (`!/reduce()`), an
        # expression, so it stays LEGACY. Every other refusal is the author's error.
        if exc.code == ErrorCode.MISSING_INTENT:
            return None
        raise


def _remote_pointer(value: str) -> IntentClass:
    remainder = value[len(_URL4_SCHEME) :]
    cut = min((i for i in (remainder.find("/"), remainder.find("?")) if i >= 0), default=-1)
    if cut < 0 or remainder[cut] != "/":
        raise ParseError(
            f"code pointer {value!r} has no path — a url4:// intent names code on a "
            "node, so it needs a path after the authority",
        )
    return _pointer(remainder[cut:], authority=remainder[:cut])


def _pointer(text: str, authority: str | None) -> IntentClass:
    path, _, query = text.partition("?")
    return IntentClass(IntentMode.RDS, CodePointer(path, query, read_query_tail(query), authority))
