"""Parity: the new surface compiles to today's url4, byte for byte (E4b surface unit 2, LO-P1).

FEATURE: the map → select → reduce surface is a new spelling of the recipes of today, not a new
protocol. Each case below is compiled twice in the same process, in the new form and in today's
form, and the two url4 strings must be equal (lowering §3, rows S1–S4′, and every README and
public-docs Fusion example that has no judge).
INVARIANT: a byte change here outside the planned changes of the overview §4 stops the unit.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from _combine_flow_fixtures import flow_operators
from _fusion_doc_examples import EXAMPLES, DocExample, compile_example

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate

_GOLDEN_DIR = Path(__file__).parent / "data" / "fusion_docs"
_ROUTES = [
    "openrouter/openai/gpt-5.5",
    "openrouter/anthropic/claude-opus-4.8",
    "openrouter/google/gemini-3.1-pro-preview",
]
_JSON = "Reply with JSON: {'answer': <number>, 'confidence': <0..1>}."
_OPUS = "openrouter/anthropic/claude-opus-4.8"
_GPT = "openrouter/openai/gpt-5.5"
_GEMINI = "openrouter/google/gemini-3.1-pro-preview"


def _json_members() -> list[sf.Model]:
    return [sf.Model(route, prompt=_JSON) for route in _ROUTES]


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=flow_operators()).url4


# ---------------------------------------------------------------- S1–S4′ (lowering §3)

_NOTEBOOK: dict[str, tuple[Callable[[], sf.Recipe], Callable[[], sf.Recipe]]] = {
    "S1": (
        lambda: sx.Fanout(_ROUTES) >> sx.Median(over="last_number", select="value"),
        lambda: sf.Fusion(_ROUTES, synthesizer=sf.Median(extract="last_number", select="value")),
    ),
    "S2": (
        lambda: sx.Fanout(_ROUTES) >> sx.Median(over="last_number"),
        lambda: sf.Fusion(_ROUTES, synthesizer=sf.Median(extract="last_number")),
    ),
    "S3": (
        lambda: sx.Fanout(_ROUTES) >> sx.Mean(weights=(1, 1, 2)),
        lambda: sf.Fusion(_ROUTES, synthesizer=sf.Mean(weights=(1, 1, 2))),
    ),
    "S4": (
        lambda: (
            sx.Fanout(_json_members()) >> sx.Mean(over="field:answer", weights="field:confidence")
        ),
        lambda: sf.Fusion(
            _json_members(),
            synthesizer=sf.Reduce(
                "mean",
                extract=sf.Extract("field", path="answer"),
                weights=sf.signal("field:confidence"),
            ),
        ),
    ),
    "S4'": (
        lambda: (
            sx.Fanout(_json_members())
            >> sx.Median(over="field:answer", weights="field:confidence", select="value")
        ),
        lambda: sf.Fusion(
            _json_members(),
            synthesizer=sf.Reduce(
                "median",
                mode="compute",
                extract=sf.Extract("field", path="answer"),
                weights=sf.signal("field:confidence"),
            ),
        ),
    ),
}


@pytest.mark.parametrize("case", sorted(_NOTEBOOK))
def test_lop1_notebook_case_compiles_to_the_bytes_of_today(case: str) -> None:
    new, today = _NOTEBOOK[case]

    assert _url4(new()) == _url4(today())


# ---------------------------------------------------------------- the README and docs examples


def _opus() -> sf.Model:
    return sf.Model(_OPUS)


def _gpt() -> sf.Model:
    return sf.Model(_GPT)


def _recursive() -> sf.Recipe:  # README.md:222
    review_chain = sx.Pipeline(
        [
            sf.Model(_GPT),
            sf.Model(_OPUS, prompt="Review the previous answer and return a corrected answer."),
            sf.Model(_GPT, prompt="Polish the previous answer without adding unsupported claims."),
        ],
        name="review-chain",
    )
    return sx.Fanout([review_chain, sf.Model(_GEMINI)]) >> sx.Synthesize(
        sx.Pipeline([sf.Model(_OPUS), sf.Model(_GPT)])
    )


def _pipelines_recursive() -> sf.Recipe:  # PipelinesPage.vue:39
    judge = sf.Model(_OPUS, name="judge")
    writer = sf.Model(_GPT, name="writer")
    return sx.Fanout([sx.Pipeline([_gpt(), _opus()]), sf.Model(_GEMINI)]) >> sx.Synthesize(
        sx.Pipeline([judge, writer])
    )


def _pipelines_mixed() -> sf.Recipe:  # PipelinesPage.vue:45
    final = sf.Model(_GPT, name="polish")
    refine = sx.Pipeline([_opus(), final], name="refine")
    return sx.Pipeline(
        [_gpt(), sx.Fanout([_gpt(), _opus()]), sx.Synthesize(final), refine], name="mixed"
    )


def _fusions_nested() -> sf.Recipe:  # FusionsPage.vue:36
    pair = sx.Fanout([_opus(), _gpt()]) >> sx.Synthesize(_OPUS)
    haiku = sf.Model("openrouter/anthropic/claude-haiku-4.5")
    return sx.Fanout([pair, haiku], name="nested") >> sx.Synthesize(_GPT)


def _quickstart_trio() -> sf.Recipe:  # QuickstartPage.vue:233
    answer = "Answer this research prompt thoroughly, in prose, with specific evidence."
    synthesis = "Combine the panel's answers into one unified prose answer. Add no new facts."
    gemini = sf.Model(_GEMINI, params={"temperature": 0, "max_tokens": 8192})
    writer = sf.Model(_OPUS, params={"temperature": 0, "max_tokens": 8192})
    return sx.Fanout([_OPUS, _GPT, gemini], name="frontier-trio", prompt=answer) >> sx.Synthesize(
        writer, prompt=synthesis
    )


_PAIR = ["provider/a", "provider/b"]
_OPUS5 = "anthropic/claude-opus-5"
_HIGHER = "Give a higher number to a more correct answer."

# slug -> the example in the new form. Every example with no judge is here; the judge examples
# (by-label, by-scores, judge-weighted, merged, pick, rank, joined) are unit 3.
_NEW_FORM: dict[str, Callable[[], sf.Recipe]] = {
    "readme-57-frontier-pair": lambda: (
        sx.Fanout([_opus(), _gpt()], name="frontier-pair") >> sx.Synthesize(_OPUS)
    ),
    "readme-119-pair": lambda: sx.Fanout([_opus(), _gpt()]) >> sx.Synthesize(_OPUS),
    "readme-134-constraint-aware": lambda: (
        sx.Fanout([_opus(), _gpt()])
        >> sx.Synthesize(
            sf.Model(_GPT, params={"reasoning_effort": "high"}),
            prompt=(
                "Produce one final answer that preserves every constraint in the original request."
            ),
        )
    ),
    "readme-158-samples-vote": lambda: (
        sx.Fanout(sf.samples(_GPT, 5, temperature=0.7))
        >> sx.Vote(over="last_number", normalize="numeric")
    ),
    "readme-222-recursive": _recursive,
    "readme-260-by-vote": lambda: (
        sx.Fanout(_ROUTES) >> sx.Vote(over="last_number", normalize="numeric")
    ),
    "readme-261-by-median": lambda: (
        sx.Fanout(_ROUTES) >> sx.Median(over="last_number", select="value")
    ),
    "readme-273-by-grader": lambda: sx.Fanout(_ROUTES) >> sx.Vote(over="benchmark"),
    "readme-290-fixed-weights": lambda: sx.Fanout(_ROUTES) >> sx.Vote(weights=[2, 1, 1]),
    "readme-293-by-confidence-weighted": lambda: (
        sx.Fanout(_ROUTES) >> sx.Vote(over="field:answer", weights="field:confidence")
    ),
    "readme-303-by-cost": lambda: sx.Fanout(_ROUTES) >> sx.Vote(weights="cost_usd"),
    "readme-304-by-cost-block": lambda: (
        sx.Fanout(_ROUTES)
        >> sx.Vote(over=sf.Extract("last_line", normalize="text"), weights="cost_usd")
    ),
    "docs-index-27-overview": lambda: (
        sx.Fanout([_gpt(), sf.Model("openrouter/google/gemini-3-flash-preview")])
        >> sx.Synthesize(_GPT)
    ),
    "docs-first-fusion-15": lambda: (
        sx.Fanout([_GPT, "openrouter/google/gemini-3-flash-preview"]) >> sx.Synthesize(_GPT)
    ),
    "docs-pipelines-39-recursive": _pipelines_recursive,
    "docs-pipelines-45-mixed": _pipelines_mixed,
    "docs-fusions-17-pair": lambda: sx.Fanout([_opus(), _gpt()]) >> sx.Synthesize(_OPUS),
    "docs-fusions-24-synth": lambda: (
        sx.Fanout([_opus(), _gpt()], name="pair-gpt-synth")
        >> sx.Synthesize(_GPT, prompt="Write the final answer from the drafts.")
    ),
    "docs-fusions-36-nested": _fusions_nested,
    "docs-evaluation-33-many": lambda: sx.Fanout([_opus(), _gpt()]) >> sx.Synthesize(_GPT),
    "docs-api-fusions-19": lambda: (
        sx.Fanout(["openrouter/deepseek/deepseek-v4-pro", "openrouter/z-ai/glm-5.2"])
        >> sx.Synthesize("openrouter/moonshotai/kimi-k3")
    ),
    "docs-quickstart-233-trio": _quickstart_trio,
    "extra-named-pipeline-synthesizer": lambda: (
        sx.Fanout(_PAIR)
        >> sx.Synthesize(sx.Pipeline(["provider/j", "provider/w"], name="judge-write"))
    ),
    "extra-named-pipeline-of-one-fusion": lambda: sx.Pipeline(
        [sx.Fanout(_PAIR), sx.Synthesize("provider/s")], name="x"
    ),
    "extra-nested-fusion": lambda: (
        sx.Fanout(
            [sx.Fanout(["provider/a", "provider/b"]) >> sx.Synthesize("provider/s1"), "provider/c"]
        )
        >> sx.Synthesize("provider/s2")
    ),
    "extra-300-members": lambda: (
        sx.Fanout([f"provider/m{index}" for index in range(300)]) >> sx.Synthesize("provider/s")
    ),
    "readme-339-by-label": lambda: (
        sx.Fanout(_ROUTES) >> sx.JudgePick(_OPUS5, rubric="Pick the most correct answer.")
    ),
    "readme-345-by-scores": lambda: (
        sx.Fanout(_ROUTES)
        >> sx.Judge(_OPUS5, rubric=_HIGHER, params={"temperature": 0})
        >> sx.ArgMax("score:judge")
    ),
    "readme-387-judge-weighted": lambda: (
        sx.Fanout(_ROUTES)
        >> sx.Judge(_OPUS5, rubric="Score each answer.")
        >> sx.Vote(over="last_number", normalize="numeric", weights="score:judge")
    ),
    "readme-397-judge-weighted-block": lambda: (
        sx.Fanout(_ROUTES)
        >> sx.Judge(_OPUS5, rubric="Score each answer.")
        >> sx.Vote(over=sf.Extract("last_number", normalize="numeric"), weights="score:judge")
    ),
    "readme-419-pick-answer": lambda: (
        sx.Fanout(_ROUTES) >> sx.First(where=sx.field("answer", normalize="text") == "yes")
    ),
    "readme-422-cheapest": lambda: sx.Fanout(_ROUTES) >> sx.ArgMin("cost_usd"),
    "readme-424-cheapest-block": lambda: sx.Fanout(_ROUTES) >> sx.ArgMin(sf.signal("cost_usd")),
    "readme-428-merged": lambda: (
        sx.Fanout(_ROUTES)
        >> sx.Merge(
            {
                "answer": sf.FieldRule.majority(normalize="text"),
                "score": sf.FieldRule.max(),
                "source": sf.FieldRule.from_member(2),
                "synonyms": sf.FieldRule.union(normalize="text"),
                "summary": sf.FieldRule.model(
                    "anthropic/claude-sonnet-5", prompt="Write one summary."
                ),
            }
        )
    ),
    "readme-514-ranked": lambda: (
        sx.Fanout(_ROUTES)
        >> sx.Judge(_OPUS5, rubric=_HIGHER)
        >> sx.Rank(2, by="score:judge")
        >> sx.Synthesize(
            "anthropic/claude-sonnet-5", prompt="Write the final answer from these drafts."
        )
    ),
    "readme-529-joined": lambda: (
        sx.Fanout(_ROUTES)
        >> sx.Concat(separator="\n\n---\n\n", label=True)
        >> sx.Synthesize("provider/next")
    ),
    "extra-fusion-then-model": lambda: (
        sx.Fanout(_PAIR) >> sx.Synthesize("provider/s") >> "provider/after"
    ),
}
_EXAMPLES = {example.slug: example for example in EXAMPLES}


# The doc examples whose bytes change at the swap (overview §4.2): a field pick or a field rank
# reads a signal in the new surface. S5 and S7 compare their new form with today's by_signal form.
_PLANNED_BYTE_CHANGES = frozenset({"readme-418-pick-confidence", "readme-528-rank-by-field"})


def test_every_doc_example_is_in_the_new_form_or_a_planned_byte_change() -> None:
    assert set(_NEW_FORM) | _PLANNED_BYTE_CHANGES == set(_EXAMPLES)
    assert not set(_NEW_FORM) & _PLANNED_BYTE_CHANGES


@pytest.mark.parametrize("slug", sorted(_NEW_FORM))
def test_lop1_doc_example_compiles_to_the_bytes_of_today(slug: str) -> None:
    example: DocExample = _EXAMPLES[slug]
    golden = (_GOLDEN_DIR / f"{slug}.url4").read_text(encoding="utf-8").removesuffix("\n")

    new = compile_example(example, _NEW_FORM[slug]())

    assert new == compile_example(example)
    assert new == golden


# ---------------------------------------- LO-P2 (lowering §3, before the swap)

_W = "openrouter/openai/gpt-5.5"
_P = "Write the final answer from the selected drafts."
_JR = "openrouter/anthropic/claude-opus-4.8"
_R_MAX = "Give a higher number to a more correct answer."
_R_MIN = "Give a lower number to a more correct answer."


def _writer() -> sx.Synthesize:
    return sx.Synthesize(_W, prompt=_P)


def _today_writer() -> sf.Model:
    return sf.Model(_W, prompt=_P)


def _today_scores(rubric: str, **options: object) -> sf.Judge:
    return sf.Judge(_JR, returns="scores", rubric=rubric, **options)  # type: ignore[arg-type]


# S5 and S7 compare with today's by_signal form, S10, S10', S11 and S11' with today's @1 judge form.
_STEPS: dict[str, tuple[Callable[[], sf.Recipe], Callable[[], sf.Recipe]]] = {
    "S5": (
        lambda: sx.Fanout(_json_members()) >> sx.ArgMax("field:confidence", output="answer"),
        lambda: sf.Fusion(
            _json_members(),
            synthesizer=sf.Pick(
                by_signal=sf.signal("field:confidence"), order="max", output="answer"
            ),
        ),
    ),
    "S7": (
        lambda: sx.Fanout(_json_members()) >> sx.Rank(2, by="field:confidence") >> _writer(),
        lambda: sf.Pipeline(
            [
                sf.Fusion(
                    _json_members(),
                    synthesizer=sf.Rank(k=2, by_signal=sf.signal("field:confidence")),
                ),
                _today_writer(),
            ]
        ),
    ),
    "S8": (
        lambda: (
            sx.Fanout(_json_members()) >> sx.ArgMax(sf.signal("field:confidence"), output="answer")
        ),
        lambda: sf.Fusion(
            _json_members(),
            synthesizer=sf.Pick(
                by_signal=sf.signal("field:confidence"), order="max", output="answer"
            ),
        ),
    ),
    "S9": (
        lambda: (
            sx.Fanout(_json_members())
            >> sx.Filter(where=sf.signal("field:confidence") > 0.7)
            >> _writer()
        ),
        lambda: sf.Pipeline(
            [
                sf.Fusion(
                    _json_members(),
                    synthesizer=sf.Filter(where=sf.signal("field:confidence") > 0.7),
                ),
                _today_writer(),
            ]
        ),
    ),
    "S10": (
        lambda: (
            sx.Fanout(_ROUTES)
            >> sx.Judge(_JR, rubric=_R_MAX)
            >> sx.Rank(2, by="score:judge")
            >> _writer()
        ),
        lambda: sf.Pipeline(
            [
                sf.Fusion(_ROUTES, synthesizer=sf.Rank(k=2, by=_today_scores(_R_MAX))),
                _today_writer(),
            ]
        ),
    ),
    "S10'": (
        lambda: (
            sx.Fanout(_ROUTES)
            >> sx.Judge(_JR, rubric=_R_MAX)
            >> sx.Filter(where=sf.signal("score:judge") >= 7)
            >> _writer()
        ),
        lambda: sf.Pipeline(
            [
                sf.Fusion(
                    _ROUTES,
                    synthesizer=sf.Filter(
                        where=sf.signal("score:judge") >= 7, judge=_today_scores(_R_MAX)
                    ),
                ),
                _today_writer(),
            ]
        ),
    ),
    "S11": (
        lambda: sx.Fanout(_ROUTES) >> sx.Judge(_JR, rubric=_R_MAX) >> sx.ArgMax("score:judge"),
        lambda: sf.Fusion(_ROUTES, synthesizer=_today_scores(_R_MAX)),
    ),
    "S11'": (
        lambda: sx.Fanout(_ROUTES) >> sx.Judge(_JR, rubric=_R_MIN) >> sx.ArgMin("score:judge"),
        lambda: sf.Fusion(_ROUTES, synthesizer=_today_scores(_R_MIN, order="min")),
    ),
}


@pytest.mark.parametrize("case", sorted(_STEPS))
def test_lop2_notebook_case_compiles_to_the_bytes_of_today(case: str) -> None:
    new, today = _STEPS[case]

    assert _url4(new()) == _url4(today())
