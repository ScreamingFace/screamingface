"""Render guards — what :mod:`url4.core.render` may emit without a re-parse.

INVARIANT (law L3s, "faithful or loud"): the front doors render with
``check=False``, so every guard here must make ``render`` either emit text that
re-parses to the same tree or raise :class:`~url4.core.errors.RenderError`. A
guard that lets a shape through which the parser then reads as a DIFFERENT
tree is a silent misreading — the bug class the 2026-10-09 audit (B3) found.

The guards reuse the grammar's own character classes and validators rather
than re-deriving them, so the two sides cannot drift.
"""

from __future__ import annotations

from collections.abc import Callable

from url4.core._annotations import validate_exec_annotations, validate_param
from url4.core._scan import find_top_level
from url4.core.errors import ParseError, RenderError
from url4.core.grammar import _IDENT_RE, _PATH_SEGMENT_RE, _VARREF_HEAD_RE, intent_atom
from url4.core.nodes import Iteration, Node, Params

# Annotation keys a Source must not carry as plain pairs: the parser folds them
# into node fields, so rendering them as pairs would reparse as another tree.
# WHY a local copy: `_annotations._directive_name` owns these prefixes, but it
# warns on the deprecated `foreach.` spelling, and url4 runs with its own
# DeprecationWarnings as errors — a render-side check must not warn.
_FOLDED_KEY_PREFIXES = ("iteration.", "foreach.")

# Spec B §8: a top-level URI intent is `bare-value`, which stops at an unquoted
# `, ) ! ;` and admits no `' ( *` (a `*(` would also start an iteration).
_TAIL_URI_FORBIDDEN = ",)!;'(*"


def check_token(text: str, what: str, *, extra_allowed: str) -> None:
    if not text or not all(ch.isalnum() or ch in extra_allowed for ch in text):
        raise RenderError(f"invalid {what} {text!r}")


def check_no_structural(text: str, what: str, *, top: bool, forbid_extra: str = "") -> None:
    # WHY "!": nested, the group parser splits an intent off at the first
    # depth-0 "!", so a value holding one is cut there (`mode=a!b` ran as
    # `mode=a` with intent `b`). A top-level param sits in the text's tail,
    # where "," and "!" are safe (the envelope guard checks that split).
    # Whitespace at the ends is stripped on reparse.
    forbidden = "';()" + forbid_extra + ("" if top else ",!")
    if any(ch in forbidden for ch in text) or text != text.strip():
        raise RenderError(f"{what} {text!r} contains a structural character")


def check_annotations(annotations: Params, value: Node) -> None:
    """A Source's ``;`` chain must pass the parser's own exec-chain validator."""
    for key, _ in annotations:
        if key == "expand" or (
            isinstance(value, Iteration) and key.startswith(_FOLDED_KEY_PREFIXES)
        ):
            # The parser folds these into Source.expand / Iteration.directives.
            raise RenderError(
                f"annotation {key!r} is carried by a node field on reparse — set "
                "Source.expand / Iteration.directives instead"
            )
    _as_render_error(validate_exec_annotations, annotations)


def check_param(key: str, value: str | None) -> None:
    """An expression or query param must pass the parser's ``param`` validator."""
    _as_render_error(validate_param, key, value)


def _as_render_error(check: Callable[..., None], *args: object) -> None:
    try:
        check(*args)
    except ParseError as exc:
        raise RenderError(f"the grammar rejects this on reparse: {exc}") from exc


def check_binding_name(name: str) -> None:
    # `name-part = (ALPHA / "_") *(ALPHA / DIGIT / "_")`, must not be "src"
    # (reserved): `src=@` reparses as a bare `@`, `é=@` as the text `é=@`.
    if name == "src" or not _IDENT_RE.fullmatch(name):
        raise RenderError(f"invalid binding name {name!r}")


def check_varref_name(name: str) -> None:
    # The grammar's own head regex (ASCII): str.isdigit() also accepts Unicode
    # digits such as '١', which reparse as Text.
    if not _VARREF_HEAD_RE.fullmatch("$" + name):
        raise RenderError(f"invalid variable name {name!r}")


def check_identity_collection(collection: str) -> None:
    # `identity-collection = 1*( "/" path-segment )`, checked with the parser's own
    # segment class. That class admits "!", but the envelope and group parsers
    # split an intent off at the first depth-0 "!" before the reference is read,
    # so a collection holding one cannot be written bare.
    segments = collection.split("/")
    if "!" in collection or not all(_PATH_SEGMENT_RE.fullmatch(seg) for seg in segments):
        raise RenderError(f"invalid identity collection {collection!r}")


def check_raw_tail(text: str, what: str, *, top: bool) -> None:
    """A raw-text iteration intent / reducer: stripped, no depth-0 ``;`` or ``,``.

    The parser strips these, splits the ``;`` chain off, and (in a source list)
    splits at a depth-0 comma. At top level a comma stays in the tail.
    """
    if text != text.strip():
        raise RenderError(f"{what} {text!r} has leading or trailing whitespace")
    for ch in ";" if top else ";,":
        if find_top_level(text, ch) is not None:
            raise RenderError(f"{what} {text!r} contains a depth-0 {ch!r}")


def check_structured_intent(node: Node, text: str) -> None:
    """A nested-expression / iteration / struct / reference intent must read back as itself.

    WHY a local re-parse: ``grammar.intent_atom`` turns ANY intent it cannot
    parse into natural-language ``Text`` — by design, an intent is prose first —
    so a sub-tree that would fail loudly as a source fails silently here. Only
    these structured intents pay for it (prompt text, URLs and paths do not).
    """
    for ch in ";,":
        # The enclosing chain/list would split it off first (params hoisted).
        if find_top_level(text, ch) is not None:
            raise RenderError(f"intent {text!r} contains a depth-0 {ch!r}")
    if intent_atom(text) != node:
        raise RenderError(f"intent {text!r} does not read back as {node!r}")


def check_tail_uri(text: str) -> None:
    """A top-level URL / path intent: Spec B §8 ``bare-value``, the text's tail."""
    if text != text.strip() or any(ch in _TAIL_URI_FORBIDDEN for ch in text):
        raise RenderError(
            f"intent {text!r} is not a bare value (Spec B §8): it has edge whitespace "
            f"or one of {_TAIL_URI_FORBIDDEN!r}"
        )


def check_fragment_envelope(text: str) -> None:
    """A bare fragment root must stay one intent-less, param-less source."""
    check_group_envelope(text, text, None, broadcast=False, params=())


def check_group_envelope(
    text: str, sources: str, intent: str | None, *, broadcast: bool, params: Params
) -> None:
    """The top-level envelope must split ``text`` exactly where render joined it.

    ``parser.decode_envelope`` peels the top level with string scanners whose
    rules (iteration-first, first depth-0 ``!``, the call-tail exemption) the
    nested grammar does not share. Re-running only that string-level decode —
    no value is parsed — catches every top-level re-split.
    """
    from url4.core.parser import GroupEnvelope  # runtime-only: parser is a higher layer

    env = _decode(text)
    if (
        not isinstance(env, GroupEnvelope)
        or env.source_expr.strip() != sources
        or _stripped(env.intent) != intent
        or env.broadcast != broadcast
        or env.params != params
    ):
        raise RenderError(f"the top-level envelope reads {text!r} as a different expression")


def check_iteration_envelope(text: str, node: Iteration, collection: str) -> None:
    """Top-level iteration counterpart of :func:`check_group_envelope`."""
    from url4.core.parser import IterationEnvelope  # runtime-only: parser is a higher layer

    env = _decode(text)
    if (
        not isinstance(env, IterationEnvelope)
        or env.collection.strip() != collection
        or (env.body, env.intent, env.reducer, env.directives)
        != (node.body, node.intent, node.reducer, node.directives)
    ):
        raise RenderError(f"the top-level envelope reads {text!r} as a different iteration")


def _decode(text: str) -> object:
    from url4.core.parser import decode_envelope  # runtime-only: parser is a higher layer

    try:
        return decode_envelope(text)
    except ParseError as exc:
        raise RenderError(f"rendered text {text!r} does not reparse: {exc}") from exc


def _stripped(text: str | None) -> str | None:
    return None if text is None else text.strip()


def scan_uri(text: str, *, allow_parens: bool, forbid: str) -> None:
    if text != text.strip():
        raise RenderError(f"URI {text!r} has leading or trailing whitespace")
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(" and allow_parens:
            depth += 1
        elif ch == ")" and allow_parens:
            depth -= 1
        elif depth == 0 and (ch in forbid or _starts_iteration(text, i, ch)):
            raise RenderError(
                f"URI {text!r} cannot be carried bare: depth-0 {ch!r} at offset {i} "
                "is structural (quote-as-Text changes semantics)"
            )
        if depth < 0:
            raise RenderError(f"URI {text!r} has unbalanced parentheses")
    if depth != 0:
        raise RenderError(f"URI {text!r} has unbalanced parentheses")


def _starts_iteration(text: str, i: int, ch: str) -> bool:
    return ch == "*" and text[i + 1 : i + 2] == "("
