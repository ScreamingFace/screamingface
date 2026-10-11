"""Parser facade: build() shapes, walk() traversal, and the string decoders."""

from __future__ import annotations

import pytest

from url4.core.errors import ParseError
from url4.core.nodes import Binding, Expression, Iteration, NamedJob, RelUrl, Text, Url
from url4.core.parser import (
    GroupEnvelope,
    IterationEnvelope,
    Parser,
    decode_envelope,
    split_collection_iteration,
    split_expr_params,
    split_foreach_annotations,
    split_intent,
    split_top_level_commas,
    strip_one_paren_layer,
)


def test_build_group_with_intent() -> None:
    tree = Parser().build("(a, b)!summarize")
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert tree == Expression(
        sources=(Text("a"), Text("b")), intent=NamedJob(value="summarize"), broadcast=False
    )


def test_build_single_source_wraps_in_expression() -> None:
    tree = Parser().build("https://x")
    assert tree == Expression(sources=(Url("https://x"),), intent=None)


def test_build_broadcast_flag() -> None:
    tree = Parser().build("(a, b)!*upper")
    assert isinstance(tree, Expression)
    assert tree.broadcast is True
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert tree.intent == NamedJob(value="upper")


def test_build_empty_source_list() -> None:
    tree = Parser().build("()!write a haiku")
    assert tree == Expression(sources=(), intent=Text("write a haiku"))


def test_build_binding() -> None:
    tree = Parser().build("(article=https://x)!use $article")
    assert isinstance(tree, Expression)
    assert tree.sources == (Binding("article", Url("https://x"), "="),)


def test_build_collection_iteration_yields_node() -> None:
    # A top-level intent after the iteration is the per-row reduce intent.
    tree = Parser().build("https://data*(x)!y")
    assert tree == Iteration(collection=Url("https://data"), body="x", intent="y", reducer=None)


def test_build_reduce_over_iteration_yields_node() -> None:
    # `OME-508`: the inner expression after "*" carries its per-row intent.
    tree = Parser().build("(/data*(x)!p)!/reduce(all)")
    assert tree == Iteration(
        collection=RelUrl("/data"), body="x", intent="p", reducer="/reduce(all)"
    )


def test_build_expression_params_preserved() -> None:
    # §9.2 — trailing ;key=val protocol params land on the Expression.
    tree = Parser().build("(a, b)!go;quorum=2;t=60")
    assert isinstance(tree, Expression)
    assert tree.params == (("quorum", "2"), ("t", "60"))


def test_build_broadcast_param_folds_into_flag() -> None:
    # §6.1.1 — `!intent;broadcast` ≡ `!*intent`; the flag never stays in params.
    tree = Parser().build("(a, b)!go;broadcast")
    assert isinstance(tree, Expression)
    assert tree.broadcast is True
    assert tree.params == ()


def test_walk_preorder() -> None:
    tree = Parser().build("(a, https://x)!go")
    kinds = [type(n).__name__ for n in Parser().walk(tree)]
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert kinds == ["Expression", "Text", "Url", "NamedJob"]


def test_split_intent_basic() -> None:
    assert split_intent("(a, b)!x") == ("(a, b)", "x", False)


def test_split_intent_broadcast() -> None:
    assert split_intent("(a, b)!*x") == ("(a, b)", "x", True)


def test_split_intent_backend_call_not_split() -> None:
    assert split_intent("/claude()!hello") == ("/claude()!hello", None, False)


def test_split_intent_empty_iteration_body_is_split() -> None:
    # `src*()!intent` — the `()` is an empty iteration body, not a sub-request
    # tail, so its `!` IS the top-level separator.
    assert split_intent("('a','b')*()!'X $item'") == ("('a','b')*()", "'X $item'", False)


def test_split_intent_quoted_bang_not_split() -> None:
    # A '!' inside quotes is content, not the intent separator.
    assert split_intent("('hello!world')!go") == ("('hello!world')", "go", False)


def test_split_intent_right_associative() -> None:
    # First top-level '!' splits; the remainder is the (nested) intent.
    assert split_intent("a!b!c") == ("a", "b!c", False)


def test_split_collection_iteration() -> None:
    assert split_collection_iteration("/data*(claude:/c($item.q)!Answer)") == (
        "/data",
        "claude:/c($item.q)!Answer",
    )


def test_split_collection_iteration_absent() -> None:
    assert split_collection_iteration("(a, b)") == (None, None)


def test_split_collection_iteration_ignores_leading_star() -> None:
    # B2: a leading "*(" is the expansion prefix (§5.2 rule 9), not iteration.
    assert split_collection_iteration("*(a)!x") == (None, None)


def test_split_collection_iteration_ignores_leading_star_after_space() -> None:
    # The expansion prefix is the first non-space character (F5).
    assert split_collection_iteration("  *(a)!x") == (None, None)


# strip_one_paren_layer, reimplemented over the shared balanced_body scanner
# (see url4._scan). Pinning the full behavior matrix here since it previously
# had only indirect coverage via decode_envelope.
@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("(a, b)", "a, b"),
        ("()", ""),
        ("((a, b))", "(a, b)"),
        ("(a)(b)", None),
        ("(a", None),
        ("(a))", None),
        ("(a)b", None),
        ("abc", None),
        ("", None),
        ("  (a, b)  ", "a, b"),
    ],
)
def test_strip_one_paren_layer(expr: str, expected: str | None) -> None:
    assert strip_one_paren_layer(expr) == expected


_LANL_ROW_BODY = (
    "(question:0.0:$item.input, case_id:0.0:$item.id, "
    "member_round_1:0.0:$members*(answer:0.0:/ans($question)!'a')!'$rec'"
    ";iteration.concurrency=4;iteration.on_error=fail, "
    "tie_gate_1:0.0:/gate($member_round_1)!'tie', "
    "check_1:0.0:/check($selection_1)!'grade')!'$check_1'"
)


def test_decode_map_row_body_with_mid_list_iterate_is_group() -> None:
    envelope = decode_envelope(_LANL_ROW_BODY, require_intent=False)
    assert isinstance(envelope, GroupEnvelope)
    assert envelope.intent == "'$check_1'"
    inner = strip_one_paren_layer(envelope.source_expr)
    assert inner is not None
    assert len(split_top_level_commas(inner)) == 5


def test_decode_reduce_over_iteration_still_binds() -> None:
    envelope = decode_envelope("(/data*(x!'p')!'peri';iteration.on_error=fail)!/reduce(all)")
    assert isinstance(envelope, IterationEnvelope)
    assert envelope.collection == "/data"
    assert envelope.reducer == "/reduce(all)"
    assert envelope.directives.on_error == "fail"


def test_decode_reduce_over_iteration_with_paren_collection_commas() -> None:
    envelope = decode_envelope("((a, b, c)*(x!'p')!'peri')!/reduce(all)")
    assert isinstance(envelope, IterationEnvelope)
    assert envelope.collection == "(a, b, c)"


def test_split_expr_params_directives() -> None:
    expr = "body;iteration.concurrency=10;iteration.on_error=collect"
    clean, params, directives = split_expr_params(expr)
    assert clean == "body"
    assert params == ()
    assert directives.concurrency == 10
    assert directives.on_error == "collect"


def test_split_expr_params_defaults() -> None:
    clean, params, directives = split_expr_params("body")
    assert clean == "body"
    assert params == ()
    assert directives.concurrency is None
    assert directives.on_error == "collect"  # §5.3.6 default


def test_split_expr_params_preserves_protocol_keys() -> None:
    clean, params, directives = split_expr_params("body;quorum=2;t=60;required")
    assert clean == "body"
    assert params == (("quorum", "2"), ("t", "60"), ("required", None))
    assert directives.concurrency is None


def test_split_expr_params_slice_and_fmt() -> None:
    _, _, directives = split_expr_params("body;iteration.slice=1:3;iteration.fmt_result=ndjson")
    assert directives.slice == (1, 3)
    assert directives.fmt_result == "ndjson"


@pytest.mark.parametrize(
    "expr",
    [
        "body;iteration.on_error=ignore",
        "body;iteration.on_error=Collect",  # case-sensitive
        "body;iteration.concurrency=-1",
        "body;iteration.concurrency=0",
        "body;iteration.concurrency=abc",
        "body;iteration.slice=3",
        "body;iteration.slice=3:1",
    ],
)
def test_split_expr_params_invalid_directive_raises(expr: str) -> None:
    with pytest.raises(ParseError):
        split_expr_params(expr)


def test_deprecated_foreach_spelling_warns() -> None:
    with pytest.warns(DeprecationWarning):
        _, _, directives = split_expr_params("body;foreach.concurrency=10")
    assert directives.concurrency == 10


def test_deprecated_abort_maps_to_fail() -> None:
    with pytest.warns(DeprecationWarning):
        _, _, directives = split_expr_params("body;iteration.on_error=abort")
    assert directives.on_error == "fail"


def test_split_foreach_annotations_wrapper_deprecated() -> None:
    with pytest.warns(DeprecationWarning):
        clean, directives = split_foreach_annotations("body;iteration.concurrency=10")
    assert clean == "body"
    assert directives.concurrency == 10
