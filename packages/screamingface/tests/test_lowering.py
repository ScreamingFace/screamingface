"""The lowering of the map → select → reduce surface (E4b surface unit 2, lowering §1–§2).

FEATURE: ``lower()`` turns a chain into the internal values that today's compiler reads. It is
pure, deterministic and idempotent, and it runs once, at the first compile entry. Until the swap it
is the identity on every value that is not a ``_surface`` value and holds none (LO-0), so no
existing recipe can change by one byte.
INVARIANT: no ``_surface`` value reaches ``_CandidateCompiler._recipe`` (LO-3).
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from pathlib import Path

import pytest
from _combine_flow_fixtures import flow_operators
from _fusion_doc_examples import EXAMPLES, DocExample, compile_example
from _nodes import FusionNode, MedianNode, VoteNode, frozen_url4, fusion_node
from test_pipeline_compilation import _whole_candidate_benchmark
from test_reducer_characterization import _GOLDEN

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation import candidate as candidate_module
from screamingface._evaluation.candidate import compile_candidate, recipes_need_operators
from screamingface._evaluation.compilation import compile_evaluation
from screamingface._evaluation.model import _candidate_values
from screamingface._surface.lowering import lower

_DATA = Path(__file__).parent / "data"
_PAIR = ["provider/a", "provider/b"]
_INTERNAL = (sf.Model, FusionNode, sf.Pipeline, sf.CorrectiveLoop, sf.SelfCorrective)


def _golden(path: Path) -> str:
    return path.read_text(encoding="utf-8").removesuffix("\n")


# ---------------------------------------------------------------- LO-0


@pytest.mark.parametrize("example", EXAMPLES, ids=[example.slug for example in EXAMPLES])
def test_lo0_lower_is_the_identity_on_every_doc_golden(example: DocExample) -> None:
    recipe = example.build()

    assert lower(recipe) is recipe
    assert compile_example(example, lower(recipe)) == _golden(
        _DATA / "fusion_docs" / f"{example.slug}.url4"
    )


@pytest.mark.parametrize("golden", sorted(_GOLDEN))
def test_lo0_lower_is_the_identity_on_every_characterized_golden(golden: str) -> None:
    recipe = _GOLDEN[golden]

    assert lower(recipe) is recipe
    assert compile_candidate(recipe).url4 == _golden(_DATA / golden)


@pytest.mark.parametrize(
    "value",
    [
        sf.CorrectiveLoop(["provider/a", "provider/b"], judge="provider/j"),
        sf.SelfCorrective("provider/a"),
        sf.Model("provider/a"),
        "provider/a",
        3,
    ],
    ids=["corrective-loop", "self-corrective", "model", "route", "not-a-recipe"],
)
def test_lo0_lower_is_the_identity_on_other_values(value: object) -> None:
    assert lower(value) is value  # type: ignore[arg-type]


def test_lo0_a_cyclic_value_is_left_for_the_compiler_to_refuse() -> None:
    pipeline = sf.Pipeline(["provider/a", "provider/b"])
    object.__setattr__(pipeline, "stages", (sf.Model("provider/a"), pipeline))

    assert lower(pipeline) is pipeline


def test_lo0_the_evaluation_entry_keeps_old_values_as_they_are() -> None:
    recipe = fusion_node(_PAIR, VoteNode())

    (value,) = _candidate_values(recipe)

    assert value is recipe


# ---------------------------------------------------------------- the block form


def test_fanout_then_vote_lowers_to_the_fusion_of_today() -> None:
    chain = sx.Fanout(_PAIR) >> sx.Vote()

    assert lower(chain) == fusion_node(_PAIR, VoteNode())
    assert compile_candidate(chain, operators=flow_operators()).url4 == frozen_url4(
        "lowering:pair-vote"
    )


# ---------------------------------------------------------------- NM-1


def test_nm1_a_closed_block_has_the_name_of_its_lowered_value() -> None:
    chains = [
        sx.Fanout(_PAIR) >> sx.Vote(),
        sx.Fanout(_PAIR, name="panel") >> sx.Synthesize("provider/w"),
        sx.Pipeline([sx.Fanout(_PAIR), sx.Mean()], optional=True),
    ]

    assert [chain.name for chain in chains] == ["a+b", "panel", "a+b"]
    assert [chain.name for chain in chains] == [lower(chain).name for chain in chains]


def test_nm1_a_chain_joins_its_stage_names() -> None:
    chain = "provider/x" >> (sx.Fanout(_PAIR) >> sx.Vote()) >> sf.Model("provider/y")

    assert chain.name == "x->a+b->y"
    assert lower(chain).name == chain.name


def test_nm1_a_named_chain_keeps_its_name() -> None:
    chain = sx.Pipeline(["provider/x", sx.Fanout(_PAIR), sx.Vote()], name="mine")

    assert chain.name == "mine"
    assert lower(chain).name == "mine"


# ---------------------------------------------------------------- LO-1


def test_lo1_lower_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("lower() must not open a connection")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    chain = "provider/x" >> (sx.Fanout(_PAIR) >> sx.Vote())

    assert lower(chain) == lower(chain)


@pytest.mark.parametrize(
    "build",
    [
        lambda: sx.Fanout(_PAIR) >> sx.Vote(),
        lambda: "provider/x" >> (sx.Fanout(_PAIR) >> sx.Median()),
        lambda: sx.Pipeline([sx.Fanout(_PAIR), sx.Mean()], name="named"),
        lambda: sf.CorrectiveLoop([sx.Fanout(_PAIR) >> sx.Vote(), "provider/c"], judge="j/j"),
    ],
    ids=["block", "chain", "named", "loop"],
)
def test_lo1_lower_is_idempotent(build: Callable[[], sf.Recipe]) -> None:
    once = lower(build())

    assert lower(once) is once
    assert once == lower(build())


# ---------------------------------------------------------------- LO-3


def test_lo3_the_compiler_sees_only_internal_values(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[type] = []
    original = candidate_module._CandidateCompiler._recipe

    def recording(self: object, recipe: sf.Recipe, **kwargs: object) -> object:
        seen.append(type(recipe))
        return original(self, recipe, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(candidate_module._CandidateCompiler, "_recipe", recording)
    inner = sx.Fanout(["provider/x", "provider/y"]) >> sx.Synthesize("provider/s")
    chain = (
        "provider/first"
        >> (sx.Fanout([inner, "provider/c"]) >> sx.Vote())
        >> sx.Pipeline(["provider/a", "provider/b"], name="tail")
    )

    compile_candidate(chain, operators=flow_operators())

    assert seen
    assert all(issubclass(kind, _INTERNAL) for kind in seen)
    assert not any(kind.__module__.startswith("screamingface._surface") for kind in seen)


def test_lo3_an_unlowered_chain_is_not_a_compile_kind() -> None:
    from screamingface.recipe import _recipe_kind

    with pytest.raises(TypeError, match="candidate must be an sf.Model, sf.Fusion, or sf.Pipeline"):
        _recipe_kind(sx.Fanout(_PAIR) >> sx.Vote())


# ---------------------------------------------------------------- LO-4


def test_lo4_a_chain_lowers_stage_by_stage() -> None:
    group = sx.Pipeline(["provider/p", "provider/q"], name="group")
    chain = sx.Pipeline(
        [sf.Model("provider/x"), sx.Fanout([group, "provider/c"]), sx.Vote(), group, "provider/y"]
    )

    assert lower(chain) == sf.Pipeline(
        [
            "provider/x",
            fusion_node(
                [sf.Pipeline(["provider/p", "provider/q"], name="group"), "provider/c"], VoteNode()
            ),
            sf.Pipeline(["provider/p", "provider/q"], name="group"),
            "provider/y",
        ]
    )


def test_lo4_old_containers_lower_the_chains_they_hold() -> None:
    block = sx.Fanout(_PAIR) >> sx.Vote()
    node = fusion_node(_PAIR, VoteNode())

    assert lower(sf.CorrectiveLoop([block, "provider/c"], judge=block)) == sf.CorrectiveLoop(
        [node, "provider/c"], judge=node
    )
    assert lower(sf.SelfCorrective(block, max_rounds=2)) == sf.SelfCorrective(node, max_rounds=2)
    assert lower(fusion_node([block, "provider/c"], block)) == fusion_node(
        [node, "provider/c"], node
    )
    assert lower(sf.Pipeline([block, "provider/c"], name="p")) == sf.Pipeline(
        [node, "provider/c"], name="p"
    )


# ---------------------------------------------------------------- LO-5


def test_lo5_an_unnamed_chain_of_one_block_lowers_to_the_node() -> None:
    chain = sx.Pipeline([sx.Fanout(_PAIR), sx.Median()])

    assert lower(chain) == fusion_node(_PAIR, MedianNode())


def test_lo5_the_optional_flag_moves_to_the_node() -> None:
    chain = sx.Pipeline([sx.Fanout(_PAIR), sx.Vote()], optional=True)

    assert chain.optional is True
    assert lower(chain) == fusion_node(_PAIR, VoteNode(), optional=True)


def test_lo5_an_unnamed_chain_of_one_model_stays_a_one_stage_pipeline() -> None:
    assert lower(sx.Pipeline(["provider/x"])) == sf.Pipeline(["provider/x"])


# ---------------------------------------------------------------- LO-6


def test_lo6_a_named_chain_keeps_its_grouping() -> None:
    chain = sx.Pipeline([sx.Fanout(_PAIR), sx.Vote()], name="x")

    assert lower(chain) == sf.Pipeline([fusion_node(_PAIR, VoteNode())], name="x")


def test_lo6_a_named_optional_chain_keeps_the_flag_on_the_pipeline() -> None:
    chain = sx.Pipeline([sx.Fanout(_PAIR), sx.Vote()], name="x", optional=True)

    assert lower(chain) == sf.Pipeline([fusion_node(_PAIR, VoteNode())], name="x", optional=True)


# ---------------------------------------------------------------- the compile entry (§2.4)


def test_the_evaluation_entry_lowers_each_candidate_once() -> None:
    chain = sx.Fanout(_PAIR) >> sx.Vote()

    values = _candidate_values([chain, sf.Model("provider/solo")])

    assert values == (fusion_node(_PAIR, VoteNode()), sf.Model("provider/solo"))
    assert recipes_need_operators(values)


def test_the_evaluation_entry_names_a_duplicate_chain() -> None:
    with pytest.raises(ValueError, match="duplicate Candidate name 'a\\+b'"):
        _candidate_values([sx.Fanout(_PAIR) >> sx.Vote(), sx.Fanout(_PAIR) >> sx.Median()])


def test_compile_evaluation_lowers_a_chain_it_is_given() -> None:
    chain = sx.Fanout(_PAIR) >> sx.Synthesize("provider/s")
    resource = _whole_candidate_benchmark()

    from_chain = compile_evaluation((chain,), resource, 1)

    # today's Fusion of _PAIR with the writer "provider/s", through the same entry
    assert from_chain.candidates[0].url4 == frozen_url4("lowering:pair-synthesize-evaluation")
    assert from_chain.candidates[0].name == "a+b"


def test_compile_evaluation_reads_values_the_entry_already_lowered() -> None:
    values = _candidate_values(sx.Fanout(_PAIR) >> sx.Synthesize("provider/s"))

    lowered = compile_evaluation(values, _whole_candidate_benchmark(), 1, warn_judge_writers=False)

    assert lowered.candidates[0].name == "a+b"


def test_compile_candidate_lowers_even_when_it_does_not_warn() -> None:
    chain = sx.Fanout(_PAIR) >> sx.Vote()

    assert compile_candidate(
        chain, operators=flow_operators(), warn_judge_writers=False
    ).url4 == frozen_url4("lowering:pair-vote")
