"""url4.fingerprint — the system identity of a linked url4 (E14, OME-1307).

A *system* is "the url4 minus the benchmark". The ScreamingFace linker embeds the
Candidate as the text value of a zero-weight ``candidate`` binding in the linked url4
(packages/screamingface/src/screamingface/_evaluation/linking.py:34-40). The fingerprint
is the sha256 of that Candidate's canonical text, after the caller's metadata bindings are
removed from the Candidate's root: ``render(drop(build(candidate), exclude_bindings))``.

INVARIANT: pure. No I/O, no clock, no randomness, no environment. It imports the
standard library and ``url4.core`` only (contracts.md C11).
INVARIANT: the answer seed has no channel into this value. The seed travels out of band
(the ``X-Answer-Seed`` header), never in the url4 text. A seed that the Candidate itself
declares (a ``seed`` query parameter) is part of the system and stays in the hash.
INVARIANT: this module names no SDK binding. The caller passes ``exclude_bindings``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re

from url4.core.errors import ErrorCode, Url4Error
from url4.core.nodes import Expression, Node, Source, Text
from url4.core.parser import build
from url4.core.render import render

CANDIDATE_BINDING = "candidate"


# `$$` is the escape; `$name` takes the longest identifier (so `$_sf_recipe_input` is not a
# reference to `_sf_recipe`). Mirrors `_ENV_VAR_RE` in url4.dag.semantics.ensemble, restated here
# because this module may import `url4.core` and the standard library only.
_REFERENCE = re.compile(r"\$\$|\$([a-zA-Z_]\w*|[0-9]+)", re.ASCII)


class ExcludedBindingError(Url4Error):
    """A source named in ``exclude_bindings`` is a working part of the system.

    Raised instead of hiding it: dropping such a source would give two systems that behave
    differently one fingerprint. Callers map it like any other ``Url4Error`` (a client
    ``url4_expression`` error). ``code`` is ``malformed_source``; retrying cannot succeed.
    """

    code = ErrorCode.MALFORMED_SOURCE


def canonical_system_url4(
    linked: str,
    binding: str = CANDIDATE_BINDING,
    *,
    exclude_bindings: frozenset[str] = frozenset(),
) -> str:
    """The canonical text of the system inside ``linked``.

    - ``linked`` has a root-level source named ``binding`` whose value is text →
      the system is ``build(that text)``.
    - no such source (a direct run, SR-E5) → the system is ``build(linked)``.
    Then every root-level ``Source`` of the system whose name is in ``exclude_bindings``
    is removed, and the result is ``render``-ed. Only an inert source is removed (see
    ``_without_bindings``).
    Raises the url4 errors unchanged (``url4.Url4Error``: ``ParseError``, ``RenderError``),
    and ``ExcludedBindingError`` when a source named in ``exclude_bindings`` is not inert.
    """
    root = build(linked)
    embedded = _binding_text(root, binding)
    system = root if embedded is None else build(embedded)
    return render(_without_bindings(system, exclude_bindings))


def system_fingerprint(
    linked: str,
    binding: str = CANDIDATE_BINDING,
    *,
    exclude_bindings: frozenset[str] = frozenset(),
) -> str:
    """Lowercase hex sha256 (64 chars) of ``canonical_system_url4(...)``, UTF-8."""
    canonical = canonical_system_url4(linked, binding, exclude_bindings=exclude_bindings)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _binding_text(root: Node, binding: str) -> str | None:
    """The text value of the FIRST root-level source named ``binding``, else None."""
    if not isinstance(root, Expression):
        return None
    for node in root.sources:
        if isinstance(node, Source) and node.name == binding and isinstance(node.value, Text):
            return node.value.value
    return None


def _without_bindings(system: Node, exclude_bindings: frozenset[str]) -> Node:
    """``system`` with its inert root-level sources named in ``exclude_bindings`` removed.

    INVARIANT: only inert metadata leaves the identity. A named source is inert when it is a
    ``Source`` with a ``Text`` value and the scalar weight ``0.0``, and nothing left in the
    system references its name. Any other named source raises ``ExcludedBindingError``.
    WHY: the scoreboard takes client text. A client can name a working member `_sf_recipe`;
    hiding it would file a different system under an existing fingerprint.
    """
    if not exclude_bindings or not isinstance(system, Expression):
        return system
    dropped = [s for s in system.sources if isinstance(s, Source) and s.name in exclude_bindings]
    if not dropped:
        return system
    for source in dropped:
        if not _is_inert_metadata(source):
            raise ExcludedBindingError(
                f"source {source.name!r} is named in exclude_bindings but is not inert "
                "(it needs a Text value and weight 0.0)"
            )
    kept = tuple(
        s for s in system.sources if not (isinstance(s, Source) and s.name in exclude_bindings)
    )
    remainder = dataclasses.replace(system, sources=kept)
    referenced = {m.group(1) for m in _REFERENCE.finditer(render(remainder))}
    for source in dropped:
        if source.name in referenced:
            raise ExcludedBindingError(
                f"source {source.name!r} is named in exclude_bindings but the system references it"
            )
    return remainder


def _is_inert_metadata(source: Source) -> bool:
    """Text value and the explicit scalar weight ``0.0`` (the rule of `_is_instrumental_weight`)."""
    weight = source.weight
    return (
        isinstance(source.value, Text)
        and isinstance(weight, (int, float))
        and not isinstance(weight, bool)
        and float(weight) == 0.0
    )


__all__ = [
    "CANDIDATE_BINDING",
    "ExcludedBindingError",
    "canonical_system_url4",
    "system_fingerprint",
]
