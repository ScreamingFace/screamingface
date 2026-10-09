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
from url4.core.grammar import _DATA_PATH_RE
from url4.core.nodes import (
    Expression,
    IdentityRef,
    Iteration,
    Node,
    RelUrl,
    SelfRef,
    StructObject,
    Text,
    Url,
    VarRef,
)

_URL4_SCHEME = "url4://"
# WHY: the grammar does not validate `host` (it defines no hostname rule), so
# only the characters that end an authority or open an expression are refused.
_AUTHORITY_STOP = frozenset("(?#'")


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


# The modes whose node type is enough. RelUrl and Url are not here: their text
# decides (see `classify_intent`).
_MODE_BY_NODE: Mapping[type[object], IntentMode] = {
    Text: IntentMode.LLM,
    Expression: IntentMode.COMPUTED,
    Iteration: IntentMode.COMPUTED,
    VarRef: IntentMode.VALUE,
    StructObject: IntentMode.VALUE,
    SelfRef: IntentMode.VALUE,
    IdentityRef: IntentMode.VALUE,
}


def classify_intent(atom: Node) -> IntentClass:
    """Classify a parsed intent atom (``intent_atom`` output) into its mode.

    # INVARIANT: the decision reads the ABNF production the atom's text matches,
    # never the node type alone. `intent_atom` also places relative and remote
    # EXPRESSIONS in `RelUrl` and `Url`, and those must stay LEGACY.
    """
    if isinstance(atom, RelUrl):
        return _classify_path(atom.value, authority=None)
    if isinstance(atom, Url):
        return _classify_url(atom.value)
    return IntentClass(_MODE_BY_NODE.get(type(atom), IntentMode.LEGACY))


def _classify_url(value: str) -> IntentClass:
    if not value.startswith(_URL4_SCHEME):
        return IntentClass(IntentMode.UNSUPPORTED)
    authority, _, rest = value[len(_URL4_SCHEME) :].partition("/")
    if not authority or not _AUTHORITY_STOP.isdisjoint(authority):
        return IntentClass(IntentMode.LEGACY)
    return _classify_path("/" + rest, authority=authority)


def _classify_path(text: str, authority: str | None) -> IntentClass:
    path, _, query = text.partition("?")
    # WHY: a `(` in the path or the query makes the text an expression, not a
    # code pointer, so `/p?q=(c)!x` stays LEGACY and is not read as a query.
    if _DATA_PATH_RE.fullmatch(path) is None or "(" in query:
        return IntentClass(IntentMode.LEGACY)
    pointer = CodePointer(path, query, read_query_tail(query), authority)
    return IntentClass(IntentMode.RDS, pointer)
