"""The system fingerprint — the identity the leaderboard uses for "the same system".

STORY: as a leaderboard maintainer I want one fingerprint for one system, whichever benchmark
it ran on and however its url4 was spelled, so that the registry lists one system once.

# INVARIANT: every oracle below is `hashlib.sha256` over a literal. No expected value comes
# from the code under test.
"""

from __future__ import annotations

import hashlib
import inspect
import re

import pytest

from url4 import Url4Error, build, expr, render, src, text
from url4.fingerprint import ExcludedBindingError, canonical_system_url4, system_fingerprint

C = "(model_1:0.0:/openrouter/model($input)!'Be brief')!'$model_1'"
C2 = "(model_1:0.0:/openrouter/other($input)!'Be brief')!'$model_1'"
B1 = build("(answer:0.0:/candidate(question)!'$candidate')!'$answer'")
SF = frozenset({"_sf_recipe"})
S8 = "(model_1:0.0:/openrouter/model($input)!'Answer the request.')!'$model_1'"


def recipe(name: str, named: str) -> str:
    """The SDK recipe source (sf.Model("openrouter/model", name="kevins-best") -> named true)."""
    return (
        '_sf_recipe:0.0:\'{"recipe":{"binding":"model_1","kind":"model","name":"'
        + name
        + '","named":'
        + named
        + ',"role":"model"},"schema":"screamingface.recipe.v1"}\''
    )


A8 = (
    "(model_1:0.0:/openrouter/model($input)!'Answer the request.', "
    + recipe("model", "false")
    + ")!'$model_1'"
)
A9 = (
    "(model_1:0.0:/openrouter/model($input)!'Answer the request.', "
    + recipe("kevins-best", "true")
    + ")!'$model_1'"
)


def link(c: str) -> str:
    """The SDK linker shape (packages/screamingface/.../_evaluation/linking.py:37-38)."""
    return render(expr(src(text(c), name="candidate", weight=0.0), B1, intent=text("")))


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


LINKED_1 = link(C)
LINKED_2 = render(
    expr(
        src(text(C), name="candidate", weight=0.0),
        src("/benchmarks/draco/revision-1/cases", name="rows", weight=0.0),
        intent=text("$rows"),
    )
)


def test_fingerprint_same_candidate_on_two_benchmarks() -> None:
    """SR-4: the benchmark is not part of the system."""
    expected = sha(C)
    assert system_fingerprint(LINKED_1) == system_fingerprint(LINKED_2) == expected
    assert system_fingerprint(LINKED_1, exclude_bindings=SF) == expected
    assert system_fingerprint(LINKED_2, exclude_bindings=SF) == expected
    assert system_fingerprint(link(C2)) != expected


def test_fingerprint_is_lowercase_sha256_hex() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", system_fingerprint(LINKED_1))


def test_fingerprint_without_binding_hashes_whole_canonical_url4() -> None:
    # D3, OD-5: a direct run has no `candidate` binding, so the whole url4 is the system.
    assert system_fingerprint(C) == sha(C)
    # the fallback canonicalizes: `:0:` and `?q=` spell the same url4 as C
    assert system_fingerprint(
        "(model_1:0:/openrouter/model?q=($input)!'Be brief')!'$model_1'"
    ) == sha(C)


def test_fingerprint_iteration_root_hashes_whole_canonical_url4() -> None:
    # `build` returns an Iteration here, not an Expression: no binding, nothing to exclude.
    literal = "/rows*(/m($item)!'a')!'b'"
    assert system_fingerprint(literal) == sha(literal)
    assert system_fingerprint(literal, exclude_bindings=SF) == sha(literal)


def test_fingerprint_non_text_candidate_binding_is_no_binding() -> None:
    # The `candidate` value is a RelUrl, not a Text: the SDK rule says "no binding".
    linked = render(
        expr(
            src("/benchmarks/x/cases", name="candidate", weight=0.0),
            src(text(C), name="system", weight=0.0),
            intent=text(""),
        )
    )
    assert system_fingerprint(linked) == sha(linked)


@pytest.mark.parametrize("bad", ["(((", ""], ids=["parse-error", "render-error"])
def test_fingerprint_unparseable_linked_url4_raises_url4_error(bad: str) -> None:
    with pytest.raises(Url4Error):
        system_fingerprint(bad)


def test_fingerprint_first_candidate_binding_wins() -> None:
    linked = render(
        expr(
            src(text(C), name="candidate", weight=0.0),
            src(text(C2), name="candidate", weight=0.0),
            intent=text(""),
        )
    )
    assert system_fingerprint(linked) == sha(C)


def test_fingerprint_custom_binding_name() -> None:
    linked = render(expr(src(text(C), name="system", weight=0.0), intent=text("")))
    assert system_fingerprint(linked, binding="system") == sha(C)
    assert system_fingerprint(linked) == sha(linked)


def test_fingerprint_keeps_a_candidate_declared_seed() -> None:
    # D3, OD-2: a seed the Candidate declares is part of the system and stays in the hash.
    seven = "(model_1:0.0:/openrouter/model?seed=7&q=($input)!'Be brief')!'$model_1'"
    eight = "(model_1:0.0:/openrouter/model?seed=8&q=($input)!'Be brief')!'$model_1'"
    first = system_fingerprint(link(seven), exclude_bindings=SF)
    second = system_fingerprint(link(eight), exclude_bindings=SF)
    assert first == sha(seven)
    assert second == sha(eight)
    assert first != second


def test_canonical_system_url4_is_canonical() -> None:
    assert canonical_system_url4(LINKED_1) == C
    for linked in (LINKED_1, LINKED_2, C):
        assert sha(canonical_system_url4(linked)) == system_fingerprint(linked)


def test_fingerprint_unparseable_embedded_candidate_raises_url4_error() -> None:
    with pytest.raises(Url4Error):
        system_fingerprint("(candidate:0.0:'(((')!''")


def test_fingerprint_sr_h3_recipe_name_is_excluded() -> None:
    """SR-H3 (url4 half, D3): two display names of one system give one fingerprint."""
    assert system_fingerprint(link(A8), exclude_bindings=SF) == sha(S8)
    assert system_fingerprint(link(A9), exclude_bindings=SF) == sha(S8)
    assert canonical_system_url4(link(A9), exclude_bindings=SF) == S8
    # with the default empty set the blob stays in the hash (the ERD value)
    assert system_fingerprint(link(A8)) == sha(A8)
    assert system_fingerprint(link(A8)) != system_fingerprint(link(A9))


def test_fingerprint_exclude_bindings_applies_to_direct_run() -> None:
    # No candidate binding: a direct run of a Candidate and a linked run give one value.
    assert system_fingerprint(A9, exclude_bindings=SF) == sha(S8)


def test_fingerprint_exclude_bindings_is_root_level_of_the_system_only() -> None:
    # The linked root has a `_sf_recipe` source: it is not the system, the Candidate is.
    linked = render(
        expr(
            src(text(C), name="candidate", weight=0.0),
            src(text("x"), name="_sf_recipe", weight=0.0),
            B1,
            intent=text(""),
        )
    )
    assert system_fingerprint(linked, exclude_bindings=SF) == sha(C)
    # A `_sf_recipe` nested one level down inside the Candidate stays.
    nested = (
        "(model_1:0.0:(inner:0.0:/p($input)!'a', "
        + recipe("model", "false")
        + ")!'$inner')!'$model_1'"
    )
    assert system_fingerprint(link(nested), exclude_bindings=SF) == sha(nested)


def test_fingerprint_exclude_every_source_renders_an_empty_group() -> None:
    literal = "(_sf_recipe:0.0:'x')!'y'"
    assert canonical_system_url4(literal, exclude_bindings=SF) == "()!'y'"
    assert system_fingerprint(literal, exclude_bindings=SF) == sha("()!'y'")


def test_fingerprint_strips_answer_seed() -> None:
    """SR-3 (a guard): the answer seed has no channel into the fingerprint.

    The seed is not in the url4 text. The SDK sends it as the `X-Answer-Seed` header
    (packages/screamingface/src/screamingface/_engine/transport.py:1197-1206); the compiled
    Candidate carries it as a separate attribute and copies `url4` unchanged
    (_evaluation/model.py:171-185); the report keeps it in its own field
    (_evaluation/results.py:137-140); the engine stamps it on each model call at egress only
    (apps/screamingface-engine/src/screamingface_engine/world/request_parameters.py:81-102).
    The submitted `url4_expression` is the linked url4 (_scoreboard/leaderboards.py:454,
    _evaluation/compilation.py:33-43): the same text for every seed.

    # INVARIANT: no seed parameter exists. This test fails the moment one is added.
    """
    for function in (system_fingerprint, canonical_system_url4):
        parameters = inspect.signature(function).parameters
        assert list(parameters) == ["linked", "binding", "exclude_bindings"]
        assert parameters["exclude_bindings"].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters["exclude_bindings"].default == frozenset()
    # the text the SDK submits for answer_seed=1 and for answer_seed=2 is this one text
    assert system_fingerprint(LINKED_1, exclude_bindings=SF) == sha(C)


# --- exclude_bindings strips only INERT sources (review finding F1) --------------------------
#
# INVARIANT: a source leaves the identity only when it is a zero-weight Text source that no
# other part of the system references. Anything else named in `exclude_bindings` is a working
# part of the system: hiding it would give two systems that behave differently one fingerprint.
# The scoreboard takes client text, so a client can name a working member `_sf_recipe`.


def _worker(route: str) -> str:
    """A system whose model_1 reads the `_sf_recipe` source through a sibling reference."""
    return (
        f"(_sf_recipe:0.0:/{route}($input)!'Solve it', "
        "model_1:0.0:/openrouter/model($_sf_recipe)!'Copy the answer.')!'$model_1'"
    )


def test_fingerprint_exclude_refuses_a_referenced_member_named_like_metadata() -> None:
    # The finding: a working `_sf_recipe` member fed model_1. Two different routes must not
    # collapse to one fingerprint, and the caller must hear about it.
    for candidate in (_worker("anthropic-claude-opus"), _worker("openai-gpt-5")):
        with pytest.raises(ExcludedBindingError):
            system_fingerprint(link(candidate), exclude_bindings=SF)
        with pytest.raises(ExcludedBindingError):
            canonical_system_url4(candidate, exclude_bindings=SF)
    # without the exclude set the two systems keep two fingerprints (the ERD value)
    assert system_fingerprint(link(_worker("anthropic-claude-opus"))) != system_fingerprint(
        link(_worker("openai-gpt-5"))
    )


@pytest.mark.parametrize(
    "member",
    [
        pytest.param("_sf_recipe:1.0:/route($input)!'x'", id="weight-1.0-relexpr"),
        pytest.param("_sf_recipe:0.5:'x'", id="weight-0.5-text"),
        pytest.param("_sf_recipe:1.0:'x'", id="weight-1.0-text"),
        pytest.param("_sf_recipe:0.0:/route($input)!'x'", id="zero-weight-relexpr"),
        pytest.param("_sf_recipe:0.0:$input", id="zero-weight-varref"),
        pytest.param("_sf_recipe:0.0:https://example.test/a", id="zero-weight-url"),
    ],
)
def test_fingerprint_exclude_refuses_a_source_that_is_not_inert(member: str) -> None:
    candidate = f"({member}, model_1:0.0:/openrouter/model($input)!'Be brief')!'$model_1'"
    with pytest.raises(ExcludedBindingError):
        system_fingerprint(candidate, exclude_bindings=SF)


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param(
            "(_sf_recipe:0.0:'x', m:0.0:/p($_sf_recipe)!'a')!'$m'", id="in-a-source-context"
        ),
        pytest.param("(_sf_recipe:0.0:'x', m:0.0:/p($input)!'a')!'$_sf_recipe'", id="in-intent"),
        pytest.param(
            "(_sf_recipe:0.0:'x', m:0.0:/p($input)!'a')!'$_sf_recipe.name'", id="with-field-path"
        ),
        pytest.param("(_sf_recipe:0.0:'x', m:0.0:'see $_sf_recipe')!'$m'", id="in-a-text-value"),
    ],
)
def test_fingerprint_exclude_refuses_a_source_that_something_references(candidate: str) -> None:
    with pytest.raises(ExcludedBindingError):
        system_fingerprint(candidate, exclude_bindings=SF)


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param("m:0.0:/p($input)!'$_sf_recipe_input'", id="longer-name"),
        pytest.param("m:0.0:/p($input)!'$$_sf_recipe'", id="escaped-dollar"),
    ],
)
def test_fingerprint_exclude_ignores_text_that_is_not_a_reference(tail: str) -> None:
    # A longer identifier and an escaped `$$` are not references to `_sf_recipe`
    # (`$_sf_recipe_input` is what the SDK corrective loop writes, corrective.py:67).
    candidate = f"(_sf_recipe:0.0:'x', {tail})!'$m'"
    assert canonical_system_url4(candidate, exclude_bindings=SF) == f"({tail})!'$m'"


def test_excluded_binding_error_is_a_url4_error_with_a_stable_code() -> None:
    with pytest.raises(Url4Error) as caught:
        system_fingerprint(_worker("a-route"), exclude_bindings=SF)
    assert isinstance(caught.value, ExcludedBindingError)
    assert caught.value.code == "malformed_source"
    assert caught.value.permanent is True
    assert "_sf_recipe" in str(caught.value)
