"""``sf.Fusion``: the public shortcut for ``sf.Fanout(members) >> <step>`` (surface §3b).

FEATURE (owner decision 2026-10-20, revises A4): ``sf.Fusion(members, synthesizer=S, ...)`` is a
function that returns the ordinary chain. A reduce step, ``sf.Synthesize`` or a narrow step is
used as it is; a route string, an ``sf.Model`` or a recipe becomes ``sf.Synthesize(S)``;
``sf.Judge`` is refused; ``optional=True`` gives ``sf.Pipeline([chain], optional=True)``.
INVARIANT defended: no second compile path: the result equals the Fanout chain and compiles to its
bytes, and to the bytes of the Fusion of before the swap (``data/surface_parity.json``).
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable

import pytest
from _combine_flow_fixtures import flow_operators
from _fusion_doc_examples import EXAMPLES, compile_example
from _nodes import frozen_url4

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.chain import OPEN_BLOCK, Step

_ROUTES = [
    "openrouter/openai/gpt-5.5",
    "openrouter/anthropic/claude-opus-4.8",
    "openrouter/google/gemini-3.1-pro-preview",
]
_PROV = ["prov/alpha", "prov/beta", "prov/gamma"]
_OPUS = "openrouter/anthropic/claude-opus-4.8"
_GPT = "openrouter/openai/gpt-5.5"
_EXAMPLES = {example.slug: example for example in EXAMPLES}
_JUDGE_ONLY_SCORES = (
    "sf.Fusion synthesizer= takes a reducer, a writer or a narrow step; sf.Judge only scores: "
    "use sf.Fanout(...) >> sf.Judge(...) >> <reader>"
)


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=flow_operators()).url4


# step -> what sf.Fusion puts after the Fanout
_STEPS: dict[str, tuple[Callable[[], object], Callable[[], Step]]] = {
    "vote": (lambda: sf.Vote(), lambda: sf.Vote()),
    "median": (lambda: sf.Median(select="value"), lambda: sf.Median(select="value")),
    "mean": (lambda: sf.Mean(), lambda: sf.Mean()),
    "argmax": (lambda: sf.ArgMax("cost_usd"), lambda: sf.ArgMax("cost_usd")),
    "argmin": (lambda: sf.ArgMin("cost_usd"), lambda: sf.ArgMin("cost_usd")),
    "first": (
        lambda: sf.First(where=sf.field("answer") == "yes"),
        lambda: sf.First(where=sf.field("answer") == "yes"),
    ),
    "merge": (
        lambda: sf.Merge({"answer": sf.FieldRule.majority()}),
        lambda: sf.Merge({"answer": sf.FieldRule.majority()}),
    ),
    "judge-pick": (
        lambda: sf.JudgePick("prov/judge", rubric="Pick one."),
        lambda: sf.JudgePick("prov/judge", rubric="Pick one."),
    ),
    "gate": (
        lambda: sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote()),
        lambda: sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote()),
    ),
    "synthesize": (
        lambda: sf.Synthesize("prov/writer", prompt="Write."),
        lambda: sf.Synthesize("prov/writer", prompt="Write."),
    ),
    "route": (lambda: "prov/writer", lambda: sf.Synthesize("prov/writer")),
    "model": (
        lambda: sf.Model("prov/writer", prompt="Write."),
        lambda: sf.Synthesize(sf.Model("prov/writer", prompt="Write.")),
    ),
    "recipe": (
        lambda: sf.Pipeline(["prov/judge", "prov/writer"]),
        lambda: sf.Synthesize(sf.Pipeline(["prov/judge", "prov/writer"])),
    ),
}


@pytest.mark.parametrize("kind", sorted(_STEPS))
def test_the_shortcut_is_the_fanout_chain_and_compiles_to_its_bytes(kind: str) -> None:
    synthesizer, step = _STEPS[kind]

    shortcut = sf.Fusion(_PROV, synthesizer=synthesizer())  # type: ignore[arg-type]
    chain = sf.Fanout(_PROV) >> step()

    assert shortcut == chain
    assert repr(shortcut) == repr(chain)
    assert repr(shortcut).startswith("Fanout(")
    assert _url4(shortcut) == _url4(chain)


@pytest.mark.parametrize(
    ("row", "build"),
    [
        (
            "S1",
            lambda: sf.Fusion(_ROUTES, synthesizer=sf.Median(over="last_number", select="value")),
        ),
        ("S2", lambda: sf.Fusion(_ROUTES, synthesizer=sf.Median(over="last_number"))),
        ("S3", lambda: sf.Fusion(_ROUTES, synthesizer=sf.Mean(weights=(1, 1, 2)))),
    ],
    ids=["S1", "S2", "S3"],
)
def test_the_shortcut_compiles_to_the_bytes_of_the_fusion_before_the_swap(
    row: str, build: Callable[[], sf.Recipe]
) -> None:
    assert _url4(build()) == frozen_url4(f"surface_parity:{row}")


def test_a_vote_shortcut_compiles_to_the_frozen_vote_row() -> None:
    assert _url4(sf.Fusion(_PROV, synthesizer=sf.Vote())) == frozen_url4("surface_rebuild:vote")


def test_a_nested_writer_shortcut_compiles_to_the_frozen_docs_row() -> None:
    pair = sf.Fusion([sf.Model(_OPUS), sf.Model(_GPT)], synthesizer=_OPUS)
    haiku = sf.Model("openrouter/anthropic/claude-haiku-4.5")
    nested = sf.Fusion([pair, haiku], synthesizer=_GPT, name="nested")
    example = _EXAMPLES["docs-fusions-36-nested"]

    assert compile_example(example, nested) == frozen_url4("surface_parity:docs-fusions-36-nested")


def test_signals_quorum_name_and_prompt_pass_through_to_the_fanout() -> None:
    signals = {"conf": sf.Verbalized("Confidence: ([0-9]+)")}
    members = ["prov/a", "prov/b", sf.Model("prov/c", optional=True)]

    shortcut = sf.Fusion(
        members,
        synthesizer=sf.Vote(weights="conf"),
        signals=signals,
        quorum=2,
        name="panel",
        prompt="Answer briefly.",
    )

    expected = sf.Fanout(
        members, signals=signals, quorum=2, name="panel", prompt="Answer briefly."
    ) >> sf.Vote(weights="conf")
    assert shortcut == expected
    fanout = shortcut.steps[0]
    assert isinstance(fanout, sf.Fanout)
    assert (fanout.signals, fanout.quorum, fanout.name, fanout.prompt) == (
        signals,
        2,
        "panel",
        "Answer briefly.",
    )
    assert _url4(shortcut) == _url4(expected)


def test_optional_gives_the_optional_pipeline_of_the_chain() -> None:
    inner = sf.Fusion(["prov/a", "prov/b"], synthesizer=sf.Vote(), optional=True)

    assert inner == sf.Pipeline([sf.Fanout(["prov/a", "prov/b"]), sf.Vote()], optional=True)
    assert inner.optional
    outer = sf.Fanout([inner, "prov/c"], quorum=1) >> sf.Vote()
    assert _url4(sf.Fusion([inner, "prov/c"], synthesizer=sf.Vote(), quorum=1)) == _url4(outer)


def test_a_narrow_step_gives_an_open_chain_that_a_writer_closes() -> None:
    open_chain = sf.Fusion(_PROV, synthesizer=sf.Rank(2, by="cost_usd"))

    assert open_chain == sf.Fanout(_PROV) >> sf.Rank(2, by="cost_usd")
    with pytest.raises(ValueError, match=f"^{re.escape(OPEN_BLOCK)}$"):
        _url4(open_chain)
    closed = open_chain >> sf.Synthesize("prov/writer")
    assert _url4(closed) == _url4(
        sf.Fanout(_PROV) >> sf.Rank(2, by="cost_usd") >> sf.Synthesize("prov/writer")
    )


def test_a_judge_is_refused_because_it_only_scores() -> None:
    with pytest.raises(ValueError, match=f"^{re.escape(_JUDGE_ONLY_SCORES)}$"):
        sf.Fusion(_PROV, synthesizer=sf.Judge("prov/judge", rubric="Score."))


def test_the_signature_is_pinned_and_the_name_is_public() -> None:
    assert inspect.isfunction(sf.Fusion)
    assert "Fusion" in sf.__all__
    assert str(inspect.signature(sf.Fusion)) == (
        "(members: 'Sequence[str | Recipe]', *, synthesizer: 'str | Recipe | Step', "
        "signals: 'Mapping[str, SignalSource] | None' = None, "
        "quorum: \"int | Literal['all']\" = 'all', name: 'str | None' = None, "
        "prompt: 'str | None' = None, optional: 'bool' = False) -> 'Pipeline'"
    )
