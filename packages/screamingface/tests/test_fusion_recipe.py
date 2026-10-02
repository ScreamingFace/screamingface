"""sf.Fusion is the named recipe Fan-out -> Reduce('context') -> Model (OME-1289 gap, FR#3-12).

FEATURE: ``sf.Pipeline([sf.Fusion(members, synthesizer=sf.Reduce("context")), S, *rest])`` is the
block form of ``sf.Fusion(members, synthesizer=S)``. A pure rewrite lowers it BEFORE compile, so
the url4 is byte for byte the url4 of the Fusion form (leaderboard risk: the Fusion migration must
not change an output).
INVARIANT: the goldens of ``test_fusion_doc_goldens.py`` and ``test_reducer_characterization.py``
are characterized BEFORE the rewrite and never edited.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from _combine_flow_fixtures import flow_operators
from _fusion_doc_examples import EXAMPLES, DocExample, compile_example
from test_client_run import _engine, _ForbiddenTransport, _ReplayTransport
from test_reducer_characterization import _GOLDEN as _CHARACTERIZED
from url4 import expr, render, src, text

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate, recipes_need_operators
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface._evaluation.fusion_recipe import rewrite_fusion_recipe
from screamingface.recipe import Recipe
from screamingface.reducer import Reducer

_DATA = Path(__file__).parent / "data"
_BASE = "https://engine.example"
_MISUSE = (
    r"sf\.Reduce\('context'\) is the first half of the Fusion recipe: put the synthesizer right "
    r"after it, as sf\.Pipeline\(\[sf\.Fusion\(members, synthesizer=sf\.Reduce\('context'\)\), "
    r"synthesizer, \.\.\.\]\)"
)
_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)
_CONTEXT = sf.Reduce("context")
_AB = ["provider/a", "provider/b"]


def _golden(slug: str) -> str:
    path = _DATA / "fusion_docs" / f"{slug}.url4"
    # WHY removesuffix: the end-of-file-fixer hook appends one newline to data files
    return path.read_text(encoding="utf-8").removesuffix("\n")


def _fusions(recipe: Recipe) -> Iterator[sf.Fusion]:
    if isinstance(recipe, sf.Fusion):
        yield recipe
        for member in recipe.members:
            yield from _fusions(member)
        if isinstance(recipe.synthesizer, Recipe):
            yield from _fusions(recipe.synthesizer)
    elif isinstance(recipe, sf.Pipeline):
        for stage in recipe.stages:
            yield from _fusions(stage)


def _unnamed_pipeline_synthesizer(fusion: sf.Fusion) -> bool:
    synthesizer = fusion.synthesizer
    return isinstance(synthesizer, sf.Pipeline) and not synthesizer._is_named


def _block(recipe: Recipe) -> Recipe:
    """The block form of a recipe: every Fusion with a Model or Recipe synthesizer written as
    ``Pipeline([Fusion(m, name, Reduce("context")), S])``, the way a researcher would."""

    if isinstance(recipe, sf.Pipeline):
        stages = [_block(stage) for stage in recipe.stages]
        return sf.Pipeline(stages, name=recipe.name if recipe._is_named else None)
    return _block_fusion(recipe) if isinstance(recipe, sf.Fusion) else recipe


def _block_fusion(fusion: sf.Fusion) -> Recipe:
    members = [_block(member) for member in fusion.members]
    inferred = "+".join(member.name for member in fusion.members)
    name = None if fusion.name == inferred else fusion.name
    synthesizer = fusion.synthesizer
    if isinstance(synthesizer, Reducer):
        return sf.Fusion(members, name=name, synthesizer=synthesizer)
    context = sf.Fusion(members, name=name, synthesizer=_CONTEXT)
    return sf.Pipeline([context, _block(synthesizer)])


# The goldens whose Fusion has an UNNAMED Pipeline synthesizer have no block form (F11):
# sf.Pipeline flattens an unnamed nested Pipeline at construction, so the block form of
# Fusion(m, Pipeline([j, w])) would read as [Fusion(m, context), j, w] and mean something else.
_NO_BLOCK_FORM = {"readme-222-recursive", "docs-pipelines-39-recursive"}
_BLOCK_EXAMPLES = [
    example
    for example in EXAMPLES
    if example.slug not in _NO_BLOCK_FORM
    and any(not isinstance(fusion.synthesizer, Reducer) for fusion in _fusions(example.build()))
]


def test_the_goldens_without_a_block_form_are_exactly_the_unnamed_pipeline_synthesizers() -> None:
    found = {
        example.slug
        for example in EXAMPLES
        if any(_unnamed_pipeline_synthesizer(fusion) for fusion in _fusions(example.build()))
    }

    assert found == _NO_BLOCK_FORM
    assert _unnamed_pipeline_synthesizer(_CHARACTERIZED["fusion_recipe_synthesizer.url4"])  # type: ignore[arg-type]
    assert len(_BLOCK_EXAMPLES) == 17


# --- FR#3 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("example", _BLOCK_EXAMPLES, ids=[e.slug for e in _BLOCK_EXAMPLES])
def test_block_form_rewrites_to_fusion_and_compiles_byte_identical(example: DocExample) -> None:
    block = _block(example.build())

    assert block != example.build()  # the block form really is another value
    assert compile_example(example, block) == _golden(example.slug)


@pytest.mark.parametrize(
    "golden", ["fusion_model_synthesizer.url4", "pipeline_fusion_synthesizer.url4"]
)
def test_block_form_of_a_characterized_golden_compiles_to_it(golden: str) -> None:
    block = _block(_CHARACTERIZED[golden])
    expected = (_DATA / golden).read_text(encoding="utf-8").removesuffix("\n")

    assert compile_candidate(block).url4 == expected


# --- FR#4 -------------------------------------------------------------------------------------


def test_rewrite_keeps_the_rest_of_the_pipeline() -> None:
    block = sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s", "provider/after"])

    assert compile_candidate(block).url4 == _golden("extra-fusion-then-model")
    assert rewrite_fusion_recipe(
        sf.Pipeline(
            [sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s", "provider/x", "provider/y"]
        )
    ) == sf.Pipeline([sf.Fusion(_AB, synthesizer="provider/s"), "provider/x", "provider/y"])
    # a context Fusion that is not the first stage keeps the stages before it
    assert rewrite_fusion_recipe(
        sf.Pipeline(["provider/first", sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s"])
    ) == sf.Pipeline(["provider/first", sf.Fusion(_AB, synthesizer="provider/s")])


def test_an_unnamed_pipeline_of_one_stage_is_that_stage_and_a_named_one_keeps_its_name() -> None:
    block = sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s"])

    assert rewrite_fusion_recipe(block) == sf.Fusion(_AB, synthesizer="provider/s")
    named = sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s"], name="x")
    assert rewrite_fusion_recipe(named) == sf.Pipeline(
        [sf.Fusion(_AB, synthesizer="provider/s")], name="x"
    )


# --- FR#5 -------------------------------------------------------------------------------------


def test_recipe_synthesizer_keeps_the_synthesis_flag_on_its_first_stage_only() -> None:
    synthesizer = sf.Pipeline(["provider/j", "provider/w"], name="judge-write")
    block = sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), synthesizer])
    compiled = compile_candidate(block)

    assert compiled.url4 == _golden("extra-named-pipeline-synthesizer")
    assert [operation.kind for operation in compiled.operations] == [
        "model",
        "model",
        "synthesis",
        "model",
    ]
    # a Fusion as the synthesizer is a Recipe synthesizer too
    inner = sf.Fusion(["provider/c", "provider/d"], synthesizer="provider/e")
    assert (
        compile_candidate(sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), inner])).url4
        == compile_candidate(sf.Fusion(_AB, synthesizer=inner)).url4
    )


# --- FR#6 -------------------------------------------------------------------------------------


def test_named_pipeline_keeps_its_name_after_the_rewrite() -> None:
    block = sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s"], name="x")

    assert compile_candidate(block).url4 == _golden("extra-named-pipeline-of-one-fusion")
    assert "x" in compile_candidate(block).url4
    assert (
        compile_candidate(block).url4
        != compile_candidate(sf.Fusion(_AB, synthesizer="provider/s")).url4
    )


# --- FR#7 -------------------------------------------------------------------------------------


def test_nested_fusion_keeps_its_bindings_in_both_block_forms() -> None:
    golden = _golden("extra-nested-fusion")
    inner_ctx = sf.Fusion(["provider/a", "provider/b"], synthesizer=_CONTEXT)
    outer = sf.Pipeline(
        [
            sf.Fusion(
                [sf.Fusion(["provider/a", "provider/b"], synthesizer="provider/s1"), "provider/c"],
                synthesizer=_CONTEXT,
            ),
            "provider/s2",
        ]
    )
    as_member = sf.Fusion(
        [sf.Pipeline([inner_ctx, "provider/s1"]), "provider/c"], synthesizer="provider/s2"
    )
    both = sf.Pipeline(
        [
            sf.Fusion(
                [sf.Pipeline([inner_ctx, "provider/s1"]), "provider/c"], synthesizer=_CONTEXT
            ),
            "provider/s2",
        ]
    )

    for block in (outer, as_member, both):
        assert compile_candidate(block).url4 == golden
    # the name is inferred again from the rewritten member ("a+b", not "a+b->s1")
    assert rewrite_fusion_recipe(as_member).name == "a+b+c"
    assert as_member.name == "a+b->s1+c"


# --- FR#8 -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "example", [e for e in EXAMPLES if e.reducer], ids=[e.slug for e in EXAMPLES if e.reducer]
)
def test_reducer_synthesizer_fusion_is_unchanged(example: DocExample) -> None:
    recipe = example.build()

    # Vote, Pick, Rank, Judge, Merge and every other reducer Fusion: no context, no new object
    assert rewrite_fusion_recipe(recipe) is recipe
    assert compile_example(example) == _golden(example.slug)


def test_every_recipe_without_a_context_block_is_returned_as_it_is() -> None:
    for example in EXAMPLES:
        recipe = example.build()
        assert rewrite_fusion_recipe(recipe) is recipe
    for recipe in _CHARACTERIZED.values():
        assert rewrite_fusion_recipe(recipe) is recipe
    loop = sf.CorrectiveLoop(["provider/a", "provider/b"], judge="provider/j")
    solo = sf.SelfCorrective("provider/a")
    assert rewrite_fusion_recipe(loop) is loop
    assert rewrite_fusion_recipe(solo) is solo


# --- the rewrite itself ----------------------------------------------------------------------


def test_the_rewrite_is_idempotent() -> None:
    block = sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s", "provider/after"])
    once = rewrite_fusion_recipe(block)

    assert once == sf.Pipeline([sf.Fusion(_AB, synthesizer="provider/s"), "provider/after"])
    assert rewrite_fusion_recipe(once) is once


def test_the_name_rule_infers_again_or_keeps_the_given_name() -> None:
    # a name equal to the one inferred from the original children is inferred again
    nested = sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s1"])
    inferred = sf.Fusion([nested, "provider/c"], synthesizer="provider/s2")
    assert inferred.name == "a+b->s1+c"
    assert rewrite_fusion_recipe(inferred).name == "a+b+c"
    same_as_inferred = sf.Fusion(
        [nested, "provider/c"], name="a+b->s1+c", synthesizer="provider/s2"
    )
    assert rewrite_fusion_recipe(same_as_inferred).name == "a+b+c"
    # any other name is kept
    kept = sf.Fusion([nested, "provider/c"], name="mine", synthesizer="provider/s2")
    assert rewrite_fusion_recipe(kept).name == "mine"
    # the context Fusion's own name is kept, or inferred from its members
    named = sf.Pipeline([sf.Fusion(_AB, name="pair", synthesizer=_CONTEXT), "provider/s"])
    assert rewrite_fusion_recipe(named).name == "pair"
    assert rewrite_fusion_recipe(nested).name == "a+b"
    # a Pipeline uses _is_named: an unnamed one is inferred again, a named one keeps its name
    plain = sf.Pipeline(["provider/x", nested])
    assert plain.name == "x->a+b->s1" or plain.name.startswith("x->")
    assert rewrite_fusion_recipe(plain).name == "x->a+b"
    same_name = sf.Pipeline(["provider/x", nested], name=plain.name)
    assert rewrite_fusion_recipe(same_name).name == plain.name


def test_the_rewrite_reaches_loops_members_and_judges() -> None:
    block = sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s"])
    fusion = sf.Fusion(_AB, synthesizer="provider/s")

    loop = sf.CorrectiveLoop([block, "provider/c"], judge=block, max_rounds=2)
    assert rewrite_fusion_recipe(loop) == sf.CorrectiveLoop(
        [fusion, "provider/c"], judge=fusion, max_rounds=2
    )
    named = sf.CorrectiveLoop([block, "provider/c"], judge="provider/j", name="mine")
    assert rewrite_fusion_recipe(named).name == "mine"
    solo = sf.SelfCorrective(block, max_rounds=2)
    assert rewrite_fusion_recipe(solo) == sf.SelfCorrective(fusion, max_rounds=2)
    assert rewrite_fusion_recipe(sf.SelfCorrective(block, name="mine")).name == "mine"
    # the loop compiles the rewritten member
    assert (
        compile_candidate(loop, check_surface=_SURFACE).url4
        == compile_candidate(rewrite_fusion_recipe(loop), check_surface=_SURFACE).url4
    )


def test_the_rewrite_reaches_a_fusion_synthesizer_and_a_fusion_member() -> None:
    block = sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s"])
    fusion = sf.Fusion(_AB, synthesizer="provider/s")

    as_synthesizer = sf.Fusion(["provider/c", "provider/d"], synthesizer=block)
    assert rewrite_fusion_recipe(as_synthesizer) == sf.Fusion(
        ["provider/c", "provider/d"], synthesizer=fusion
    )
    # a context Fusion inside a rewritten stage's members is lowered first
    deep = sf.Pipeline([sf.Fusion([block, "provider/c"], synthesizer=_CONTEXT), "provider/t"])
    assert rewrite_fusion_recipe(deep) == sf.Fusion(
        [fusion, "provider/c"], synthesizer="provider/t"
    )
    # a context Fusion whose synthesizer stage itself holds a block form
    chained = sf.Pipeline(
        [
            sf.Fusion(_AB, synthesizer=_CONTEXT),
            sf.Pipeline(
                [sf.Fusion(["provider/c", "provider/d"], synthesizer=_CONTEXT), "provider/t"],
                name="inner",
            ),
        ]
    )
    assert rewrite_fusion_recipe(chained) == sf.Fusion(
        _AB,
        synthesizer=sf.Pipeline(
            [sf.Fusion(["provider/c", "provider/d"], synthesizer="provider/t")], name="inner"
        ),
    )


# --- FR#9 -------------------------------------------------------------------------------------


def _paths_engine(paths: list[str]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return _engine(request)

    return handler


def _client(paths: list[str], transport: Any) -> sf.Client:
    return sf.Client(
        engine_url=_BASE,
        http_transport=httpx.MockTransport(_paths_engine(paths)),
        run_transport=transport,
    )


def _block_pair() -> sf.Recipe:
    return sf.Pipeline(
        [sf.Fusion(["provider/opus", "provider/judge"], synthesizer=_CONTEXT), "provider/opus"]
    )


def test_context_block_does_not_fetch_operators() -> None:
    paths: list[str] = []
    transport = _ReplayTransport()

    with _client(paths, transport) as client:
        client.evaluate(_block_pair(), benchmark="draco", progress=False)

    assert "/v1/operators" not in paths
    assert transport.candidate is not None
    assert "ensemble/combine/v1" not in transport.candidate.url4


def test_a_300_member_block_form_constructs_and_compiles_to_its_golden() -> None:
    members = [f"provider/m{index}" for index in range(300)]
    block = sf.Pipeline([sf.Fusion(members, synthesizer=_CONTEXT), "provider/s"])

    assert compile_candidate(block).url4 == _golden("extra-300-members")
    # the member cap still holds for every reducer that compiles to a combine call
    with pytest.raises(ValueError, match="at most 256 members"):
        sf.Fusion(members, synthesizer=sf.Vote())
    assert recipes_need_operators([block]) is False
    assert recipes_need_operators([sf.Fusion(_AB, synthesizer=sf.Vote())]) is True
    mixed = sf.Pipeline(
        [sf.Fusion(_AB, synthesizer=_CONTEXT), sf.Fusion(_AB, synthesizer=sf.Vote())]
    )
    assert recipes_need_operators([mixed]) is True


def test_only_the_context_block_skips_the_combine_exclusions() -> None:
    assert _CONTEXT._compiles_to_combine() is False
    for reducer in (sf.Vote(), sf.Reduce("plurality", extract=sf.Extract("last_number"))):
        assert reducer._compiles_to_combine() is True
    for judge in (sf.Judge("provider/j", returns="label", rubric="r"), sf.Concat()):
        assert judge._compiles_to_combine() is True


# --- FR#10 ------------------------------------------------------------------------------------

_MISUSES: dict[str, Callable[[], Recipe]] = {
    "root": lambda: sf.Fusion(_AB, synthesizer=_CONTEXT),
    "last stage": lambda: sf.Pipeline(["provider/x", sf.Fusion(_AB, synthesizer=_CONTEXT)]),
    "only stage": lambda: sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT)]),
    "fusion member": lambda: sf.Fusion(
        [sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/c"], synthesizer="provider/s"
    ),
    "fusion synthesizer": lambda: sf.Fusion(
        ["provider/c", "provider/d"], synthesizer=sf.Fusion(_AB, synthesizer=_CONTEXT)
    ),
    "before another context fusion": lambda: sf.Pipeline(
        [
            sf.Fusion(_AB, synthesizer=_CONTEXT),
            sf.Fusion(["provider/c", "provider/d"], synthesizer=_CONTEXT),
            "provider/s",
        ]
    ),
    "loop member": lambda: sf.CorrectiveLoop(
        [sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/c"], judge="provider/j"
    ),
    "loop judge": lambda: sf.CorrectiveLoop(_AB, judge=sf.Fusion(_AB, synthesizer=_CONTEXT)),
    "self corrective": lambda: sf.SelfCorrective(sf.Fusion(_AB, synthesizer=_CONTEXT)),
}


@pytest.mark.parametrize("case", sorted(_MISUSES))
def test_context_misuse_raises_before_spend(case: str) -> None:
    recipe = _MISUSES[case]()

    with pytest.raises(ValueError, match=_MISUSE):
        compile_candidate(recipe, check_surface=_SURFACE, operators=flow_operators())


@pytest.mark.parametrize("case", ["root", "last stage", "before another context fusion"])
def test_context_misuse_through_a_client_never_spends_or_fetches_operators(case: str) -> None:
    paths: list[str] = []
    transport = _ForbiddenTransport()
    members = ["provider/opus", "provider/judge"]
    recipes: dict[str, Recipe] = {
        "root": sf.Fusion(members, synthesizer=_CONTEXT),
        "last stage": sf.Pipeline(["provider/opus", sf.Fusion(members, synthesizer=_CONTEXT)]),
        "before another context fusion": sf.Pipeline(
            [
                sf.Fusion(members, synthesizer=_CONTEXT),
                sf.Fusion(members, synthesizer=_CONTEXT),
                "provider/opus",
            ]
        ),
    }

    with _client(paths, transport) as client, pytest.raises(ValueError, match=_MISUSE):
        client.evaluate(recipes[case], benchmark="draco", progress=False)

    assert transport.called is False
    assert "/v1/operators" not in paths


def test_a_context_block_compiled_directly_is_the_misuse() -> None:
    with pytest.raises(ValueError, match=_MISUSE):
        _CONTEXT._plan()
    with pytest.raises(ValueError, match=_MISUSE):
        combine_spec_text(_CONTEXT, member_count=2, operators=flow_operators())
    with pytest.raises(ValueError, match="'context' is a compute op, not select"):
        sf.Reduce("context", mode="select")


# --- FR#11 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("example", _BLOCK_EXAMPLES, ids=[e.slug for e in _BLOCK_EXAMPLES])
def test_synthesizer_operation_ids_are_unchanged(example: DocExample) -> None:
    fusion_form = compile_candidate(
        example.build(),
        operators=flow_operators() if example.reducer else None,
    )
    block_form = compile_candidate(
        _block(example.build()), operators=flow_operators() if example.reducer else None
    )

    assert [(op.id, op.kind, op.label, op.depends_on) for op in block_form.operations] == [
        (op.id, op.kind, op.label, op.depends_on) for op in fusion_form.operations
    ]
    assert block_form.kind == fusion_form.kind
    assert block_form.models == fusion_form.models


def test_the_synthesizer_operation_is_op_synthesis_n() -> None:
    compiled = compile_candidate(_block_pair())

    assert [(op.id, op.kind) for op in compiled.operations] == [
        ("op_model_1", "model"),
        ("op_model_2", "model"),
        ("op_synthesis_1", "synthesis"),
    ]
    assert compiled.kind == "fusion"


# --- FR#12 ------------------------------------------------------------------------------------


def _linked(candidate: str) -> str:
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/ifeval/revision-1/cases", name="rows", weight=0.0),
            intent=text("$rows"),
        )
    )


@pytest.mark.parametrize("case", ["named synthesizer", "model synthesizer", "nested"])
def test_recovered_fusion_prints_as_fusion(case: str) -> None:
    named = sf.Pipeline(["provider/j", "provider/w"], name="judge-write")
    blocks: dict[str, Recipe] = {
        "named synthesizer": sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), named]),
        "model synthesizer": sf.Pipeline([sf.Fusion(_AB, synthesizer=_CONTEXT), "provider/s"]),
        "nested": sf.Pipeline(
            [
                sf.Fusion(
                    [sf.Fusion(_AB, synthesizer="provider/s1"), "provider/c"], synthesizer=_CONTEXT
                ),
                "provider/s2",
            ]
        ),
    }

    text_ = sf.Url4(_linked(compile_candidate(blocks[case]).url4)).to_python()

    assert "sf.Fusion(" in text_
    assert "context" not in text_
    assert "Reduce(" not in text_


def test_both_forms_report_the_same_candidate_name_in_a_scripted_run() -> None:
    names: list[str] = []
    for recipe in (
        _block_pair(),
        sf.Fusion(["provider/opus", "provider/judge"], synthesizer="provider/opus"),
    ):
        transport = _ReplayTransport()
        with _client([], transport) as client:
            client.evaluate(recipe, benchmark="draco", progress=False)
        assert transport.candidate is not None
        names.append(transport.candidate.name)

    assert names == ["opus+judge", "opus+judge"]


def test_a_cyclic_value_is_left_for_the_compiler_to_refuse() -> None:
    pipeline = sf.Pipeline(["provider/a", "provider/b"])
    object.__setattr__(pipeline, "stages", (sf.Model("provider/a"), pipeline))

    assert rewrite_fusion_recipe(pipeline) is pipeline
    with pytest.raises(ValueError, match="cycle"):
        compile_candidate(pipeline)
