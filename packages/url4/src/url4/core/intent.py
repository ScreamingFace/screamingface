"""Intent classification (Spec B §5.2, §6) and the code-pointer reader (url4 2.0).

FEATURE: code-pointer intents run as RDS calls (``docs/spec/2026-10-10-url4-rds-code-pointer``,
contracts C1 and C7).

Spec A §1.1 gives URL4 two modes with one grammar: in LLM mode the intent is a prompt, in
RDS mode it is a code pointer. :func:`classify_intent` names the intent's *form* and
:func:`intent_mode` maps a form to the mode Spec B §6 gives it. The mode is a pure function
of the form, so it is known from the parse tree alone (B §8.2.1 runs interpolation before
resolution, and B §5.3.4.1 makes field paths strict in RDS mode only).

url4 2.0 acts on two forms differently from the spec table (overview §6, the Lean ``v1``
profile): an absolute URI keeps the 1.5.1 fetch-as-prompt meaning (deviation D2, owner
decision Q1), and a bare token stays a prompt (deviation D1, until phase P3). So only a
``RELATIVE_URI`` intent ever runs code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from url4.core._annotations import parse_query_tail
from url4.core._call_head import REMOTE_SCHEME, check_data_path
from url4.core.errors import ParseError
from url4.core.grammar import intent_atom, parse_value
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
    Url,
)


class IntentForm(StrEnum):
    """The syntactic form of an intent, by the B §5.2 detection rules."""

    QUOTED = "quoted"  # rule 4
    RELATIVE_URI = "relative_uri"  # rule 2.3
    URL4_REFERENCE = "url4_reference"  # rule 3.3
    ABSOLUTE_URI = "absolute_uri"  # rule 5
    BARE_TOKEN = "bare_token"  # rule 10
    EXPRESSION = "expression"  # rules 1, 2.1, 2.2, 3.1, 3.2, iteration
    VARIABLE_REF = "variable_ref"  # rule 8.1
    SELF_REF = "self_ref"  # rule 7.1
    IDENTITY_REF = "identity_ref"  # rule 7.2
    STRUCT_OBJECT = "struct_object"  # rule 6


class IntentMode(StrEnum):
    """The execution mode Spec B §6 gives an intent form."""

    LLM = "llm"
    RDS = "rds"
    COMPUTED = "computed"


_MODE_OF_FORM: Mapping[IntentForm, IntentMode] = MappingProxyType(
    {
        IntentForm.QUOTED: IntentMode.LLM,
        IntentForm.RELATIVE_URI: IntentMode.RDS,
        IntentForm.URL4_REFERENCE: IntentMode.RDS,
        IntentForm.ABSOLUTE_URI: IntentMode.RDS,
        IntentForm.BARE_TOKEN: IntentMode.RDS,
        IntentForm.EXPRESSION: IntentMode.COMPUTED,
        IntentForm.VARIABLE_REF: IntentMode.COMPUTED,
        IntentForm.SELF_REF: IntentMode.COMPUTED,
        IntentForm.IDENTITY_REF: IntentMode.COMPUTED,
        IntentForm.STRUCT_OBJECT: IntentMode.COMPUTED,
    }
)

_FORM_OF_NODE: Mapping[type[Node], IntentForm] = MappingProxyType(
    {
        RelUrl: IntentForm.RELATIVE_URI,
        Url: IntentForm.ABSOLUTE_URI,
        RelExpr: IntentForm.EXPRESSION,
        Expression: IntentForm.EXPRESSION,
        Iteration: IntentForm.EXPRESSION,
        StructObject: IntentForm.STRUCT_OBJECT,
        SelfRef: IntentForm.SELF_REF,
        IdentityRef: IntentForm.IDENTITY_REF,
    }
)

# B §8.2.3 `variable-ref = "$" ( name / 1*DIGIT ) *field-path`, as a whole intent.
_VARIABLE_REF_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+)(?:[.\[].*)?", re.DOTALL)


def intent_mode(form: IntentForm) -> IntentMode:
    """The B §6 mode of ``form`` (total; mirrors the Lean ``IntentForm.specMode``)."""
    return _MODE_OF_FORM[form]


def classify_intent(text: str) -> IntentForm:
    """The form of the raw intent ``text`` (its ``;`` params already split off).

    # INVARIANT: the classifier and the parser cannot disagree. Every form except the
    # two text-only ones (quoted, ``url4://``) is read off the node :func:`intent_atom`
    # builds — the same call both compilation paths make — so a relative expression is
    # an EXPRESSION here exactly when the grammar builds a RelExpr for it.

    A remote expression (``url4://n/p(c)!x``) is an EXPRESSION, although the parser
    still refuses it as an intent (url4 2.0 changes no acceptance). A text the parser
    refuses outright raises its :class:`~url4.core.errors.ParseError`.
    """
    stripped = text.strip()
    if stripped.startswith("'"):
        return IntentForm.QUOTED
    if stripped.startswith(REMOTE_SCHEME):
        return _remote_form(stripped)
    form = _FORM_OF_NODE.get(type(intent_atom(stripped)))
    return form if form is not None else _text_form(stripped)


def _text_form(text: str) -> IntentForm:
    """A Text intent: unquoted, and no value rule claimed it (B §5.2 rules 8, 10)."""
    if _VARIABLE_REF_RE.fullmatch(text):
        return IntentForm.VARIABLE_REF
    return IntentForm.BARE_TOKEN


def _remote_form(text: str) -> IntentForm:
    try:
        node = parse_value(text)
    except ParseError:
        return IntentForm.URL4_REFERENCE
    return IntentForm.EXPRESSION if isinstance(node, RemoteExpr) else IntentForm.URL4_REFERENCE


@dataclass(frozen=True, slots=True)
class CodePointer:
    """A relative code-pointer intent, split once at its first ``?`` (contracts C1, C7).

    ``path`` may hold ``$name`` / ``$N`` references (B §8.2.3). They name the group's
    OWN sources (B §6.2) and are interpolated strictly at call time (C6).
    """

    path: str
    params: Mapping[str, str]

    @property
    def is_static(self) -> bool:
        """No ``$`` in the path: the mount can be checked before any source starts (R4)."""
        return "$" not in self.path


def parse_code_pointer(text: str) -> CodePointer:
    """Read a ``RELATIVE_URI`` intent as a code pointer, or raise ``malformed_source``.

    The path must be ``"/" path-segment *( "/" path-segment )`` and the query a
    ``query-tail`` (:func:`~url4.core._annotations.parse_query_tail`: no percent-decoding,
    duplicate keys refused). WHY at compile time: an invalid pointer is the author's
    error, so it fails before any source runs.
    """
    path, _, query = text.strip().partition("?")
    check_data_path(path)
    return CodePointer(path, MappingProxyType(parse_query_tail(query)))


__all__ = [
    "CodePointer",
    "IntentForm",
    "IntentMode",
    "classify_intent",
    "intent_mode",
    "parse_code_pointer",
]
