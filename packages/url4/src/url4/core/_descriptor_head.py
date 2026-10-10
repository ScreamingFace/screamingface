"""Source-descriptor heads (Spec B §4.3, §8 parsing rules 4–6): what the pre-``;`` part is.

Split out of :mod:`url4.core.grammar` so the grammar and the DAG text path
share one classification. A head is a bare value, a ``src=`` value (an
explicit, unnamed binding — ``src`` is reserved and never a name), a
``name=value`` sugar binding, or an attribution chain. The text path asks
:func:`deferrable_group` whether a source is a group it may compile lazily;
anything else it parses eagerly with the grammar, so the two paths read every
source the same way.
"""

from __future__ import annotations

from typing import Literal

from url4.core._annotations import (
    classify_boundary,
    fold_broadcast,
    split_annotation_pairs,
    validate_params,
)
from url4.core._lexical import _IDENT_RE, reject_chained_intent
from url4.core._scan import balanced_body, iter_top_level, split_top_level

HeadForm = Literal["value", "src", "sugar", "chain"]


def classify_head(head: str) -> tuple[HeadForm, str | None, str]:
    """``(form, name, value_text)`` for a source head; a chain keeps ``head`` whole.

    The sugar test runs before the bare-value test so ``article=https://x``
    binds ``article`` (§4.5) — the ``://`` inside the *value* must not promote
    the whole token to a bare URI.
    """
    result: tuple[HeadForm, str | None, str]
    if head.startswith("src="):
        result = ("src", None, head[4:])
    elif (sugar := _match_sugar(head)) is not None:
        result = ("sugar", sugar[0], sugar[1])
    else:
        # The top-level colon scan is shared: is_value_shaped needs it, and its
        # absence is itself the "no descriptor chain" test.
        colon = first_colon(head)
        shaped = colon is None or is_value_shaped(head, colon)
        result = ("value" if shaped else "chain", None, head)
    return result


def deferrable_group(segment: str) -> tuple[str | None, str, str] | None:
    """``(name, kind, group_text)`` when ``segment`` is a group the text path may defer.

    Only a bare or name-only group WITH an intent qualifies (``(…)!x``,
    ``n=(…)!x``, ``n:(…)!x``), and only when its ``;`` chain holds expression
    params alone (§8.1.2). A source with a source annotation (a guard,
    ``;expand``, a weight or budget), an expansion ``*``, or any other head
    returns None, and the caller parses it eagerly with the grammar.

    For a group it does defer, it checks at once what the deferred compile
    would only find at run time: the group's own intent must be one value
    (D-1b) and its params must be well-formed. Those raise ``ParseError``
    here. The group's sources are NOT parsed here; they stay lazy.
    """
    head, *chain = split_top_level(segment, ";")
    pairs = split_annotation_pairs(chain)
    if segment.startswith("*") or classify_boundary(pairs)[1]:
        return None
    binding = _name_and_value(head)
    if binding is None or not is_processed_group(binding[2]):
        return None
    name, kind, value = binding
    reject_chained_intent(_group_intent(value))
    validate_params(fold_broadcast(pairs)[1])
    return name, kind, ";".join([value, *chain])


def _group_intent(group: str) -> str:
    """The intent text after a processed group's ``)!`` (or ``)!*``)."""
    body = balanced_body(group, 1)
    assert body is not None  # is_processed_group checked it
    after = group[len(body) + 2 :]
    return after[2:] if after.startswith("!*") else after[1:]


def _name_and_value(head: str) -> tuple[str | None, str, str] | None:
    """A head's ``(name, kind, value)`` when it names at most a name; None otherwise."""
    form, name, value = classify_head(head)
    if form != "chain":
        return name, "=", value
    colon = first_colon(head)
    assert colon is not None  # a chain has a top-level colon
    name = head[:colon].strip()
    if not _IDENT_RE.fullmatch(name) or name == "src":
        return None
    return name, ":", head[colon + 1 :].strip()


def is_processed_group(text: str) -> bool:
    """True for ``(…)!intent`` — a parenthesized group followed by its intent."""
    if not text.startswith("("):
        return False
    body = balanced_body(text, 1)
    return body is not None and text[len(body) + 2 :].startswith("!")


def is_value_shaped(text: str, colon: int | None = None) -> bool:
    """§4.3 disambiguation — a token that is a bare data value, no descriptor.

    ``colon`` is the precomputed top-level colon index, for callers that already
    scanned for it; omitted, it is computed here.
    """
    if text[0] in "'(/@{$":
        return True
    if colon is None:
        colon = first_colon(text)
    return colon is not None and text[colon : colon + 3] == "://"


def first_colon(text: str) -> int | None:
    for i, ch in iter_top_level(text):
        if ch == ":":
            return i
    return None


def _match_sugar(head: str) -> tuple[str, str] | None:
    """``name=value`` with no ``:`` before the ``=`` (§4.3 sugar form)."""
    m = _IDENT_RE.match(head)
    if m is None or head[m.end() : m.end() + 1] != "=" or len(head) == m.end() + 1:
        return None
    return m.group(), head[m.end() + 1 :]
