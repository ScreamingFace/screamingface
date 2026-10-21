"""Parity: the new surface compiles to today's url4, byte for byte (E4b surface unit 2, LO-P1).

FEATURE: the map → select → reduce surface is a new spelling of the recipes of today, not a new
protocol. Each case below compiles in the new form, and the url4 must equal the bytes of today's
form, frozen in step 7d-0 in ``data/surface_parity.json`` (lowering §3, rows S1–S4′, and every
README and public-docs Fusion example).
INVARIANT: a byte change here outside the planned changes of the overview §4 stops the unit.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from _combine_flow_fixtures import flow_operators
from _fusion_doc_examples import EXAMPLES, DocExample, compile_example
from _nodes import frozen_url4

import screamingface as sf
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

_NOTEBOOK: dict[str, Callable[[], sf.Recipe]] = {
    "S1": lambda: sf.Fanout(_ROUTES) >> sf.Median(over="last_number", select="value"),
    "S2": lambda: sf.Fanout(_ROUTES) >> sf.Median(over="last_number"),
    "S3": lambda: sf.Fanout(_ROUTES) >> sf.Mean(weights=(1, 1, 2)),
    "S4": lambda: (
        sf.Fanout(_json_members()) >> sf.Mean(over="field:answer", weights="field:confidence")
    ),
    "S4'": lambda: (
        sf.Fanout(_json_members())
        >> sf.Median(over="field:answer", weights="field:confidence", select="value")
    ),
}


@pytest.mark.parametrize("case", sorted(_NOTEBOOK))
def test_lop1_notebook_case_compiles_to_the_bytes_of_today(case: str) -> None:
    assert _url4(_NOTEBOOK[case]()) == frozen_url4(f"surface_parity:{case}")


# ---------------------------------------------------------------- the README and docs examples


def _opus() -> sf.Model:
    return sf.Model(_OPUS)


def _gpt() -> sf.Model:
    return sf.Model(_GPT)


def _recursive() -> sf.Recipe:  # README.md:222
    review_chain = sf.Pipeline(
        [
            sf.Model(_GPT),
            sf.Model(_OPUS, prompt="Review the previous answer and return a corrected answer."),
            sf.Model(_GPT, prompt="Polish the previous answer without adding unsupported claims."),
        ],
        name="review-chain",
    )
    return sf.Fanout([review_chain, sf.Model(_GEMINI)]) >> sf.Synthesize(
        sf.Pipeline([sf.Model(_OPUS), sf.Model(_GPT)])
    )


def _pipelines_recursive() -> sf.Recipe:  # PipelinesPage.vue:39
    judge = sf.Model(_OPUS, name="judge")
    writer = sf.Model(_GPT, name="writer")
    return sf.Fanout([sf.Pipeline([_gpt(), _opus()]), sf.Model(_GEMINI)]) >> sf.Synthesize(
        sf.Pipeline([judge, writer])
    )


def _pipelines_mixed() -> sf.Recipe:  # PipelinesPage.vue:45
    final = sf.Model(_GPT, name="polish")
    refine = sf.Pipeline([_opus(), final], name="refine")
    return sf.Pipeline(
        [_gpt(), sf.Fanout([_gpt(), _opus()]), sf.Synthesize(final), refine], name="mixed"
    )


def _fusions_nested() -> sf.Recipe:  # FusionsPage.vue:36
    pair = sf.Fanout([_opus(), _gpt()]) >> sf.Synthesize(_OPUS)
    haiku = sf.Model("openrouter/anthropic/claude-haiku-4.5")
    return sf.Fanout([pair, haiku], name="nested") >> sf.Synthesize(_GPT)


def _quickstart_trio() -> sf.Recipe:  # QuickstartPage.vue:233
    answer = "Answer this research prompt thoroughly, in prose, with specific evidence."
    synthesis = "Combine the panel's answers into one unified prose answer. Add no new facts."
    gemini = sf.Model(_GEMINI, params={"temperature": 0, "max_tokens": 8192})
    writer = sf.Model(_OPUS, params={"temperature": 0, "max_tokens": 8192})
    return sf.Fanout([_OPUS, _GPT, gemini], name="frontier-trio", prompt=answer) >> sf.Synthesize(
        writer, prompt=synthesis
    )


_PAIR = ["provider/a", "provider/b"]
_OPUS5 = "anthropic/claude-opus-5"
_HIGHER = "Give a higher number to a more correct answer."

# slug -> the example in the new form. Every example with no judge is here; the judge examples
# (by-label, by-scores, judge-weighted, merged, pick, rank, joined) are unit 3.
_NEW_FORM: dict[str, Callable[[], sf.Recipe]] = {
    "readme-57-frontier-pair": lambda: (
        sf.Fanout([_opus(), _gpt()], name="frontier-pair") >> sf.Synthesize(_OPUS)
    ),
    "readme-119-pair": lambda: sf.Fanout([_opus(), _gpt()]) >> sf.Synthesize(_OPUS),
    "readme-134-constraint-aware": lambda: (
        sf.Fanout([_opus(), _gpt()])
        >> sf.Synthesize(
            sf.Model(_GPT, params={"reasoning_effort": "high"}),
            prompt=(
                "Produce one final answer that preserves every constraint in the original request."
            ),
        )
    ),
    "readme-158-samples-vote": lambda: (
        sf.Fanout(sf.samples(_GPT, 5, temperature=0.7))
        >> sf.Vote(over="last_number", normalize="numeric")
    ),
    "readme-222-recursive": _recursive,
    "readme-260-by-vote": lambda: (
        sf.Fanout(_ROUTES) >> sf.Vote(over="last_number", normalize="numeric")
    ),
    "readme-261-by-median": lambda: (
        sf.Fanout(_ROUTES) >> sf.Median(over="last_number", select="value")
    ),
    "readme-273-by-grader": lambda: sf.Fanout(_ROUTES) >> sf.Vote(over="benchmark"),
    "readme-290-fixed-weights": lambda: sf.Fanout(_ROUTES) >> sf.Vote(weights=[2, 1, 1]),
    "readme-293-by-confidence-weighted": lambda: (
        sf.Fanout(_ROUTES) >> sf.Vote(over="field:answer", weights="field:confidence")
    ),
    "readme-303-by-cost": lambda: sf.Fanout(_ROUTES) >> sf.Vote(weights="cost_usd"),
    "readme-304-by-cost-block": lambda: (
        sf.Fanout(_ROUTES)
        >> sf.Vote(over=sf.Extract("last_line", normalize="text"), weights="cost_usd")
    ),
    "docs-index-27-overview": lambda: (
        sf.Fanout([_gpt(), sf.Model("openrouter/google/gemini-3-flash-preview")])
        >> sf.Synthesize(_GPT)
    ),
    "docs-first-fusion-15": lambda: (
        sf.Fanout([_GPT, "openrouter/google/gemini-3-flash-preview"]) >> sf.Synthesize(_GPT)
    ),
    "docs-pipelines-39-recursive": _pipelines_recursive,
    "docs-pipelines-45-mixed": _pipelines_mixed,
    "docs-fusions-17-pair": lambda: sf.Fanout([_opus(), _gpt()]) >> sf.Synthesize(_OPUS),
    "docs-fusions-24-synth": lambda: (
        sf.Fanout([_opus(), _gpt()], name="pair-gpt-synth")
        >> sf.Synthesize(_GPT, prompt="Write the final answer from the drafts.")
    ),
    "docs-fusions-36-nested": _fusions_nested,
    "docs-evaluation-33-many": lambda: sf.Fanout([_opus(), _gpt()]) >> sf.Synthesize(_GPT),
    "docs-api-fusions-19": lambda: (
        sf.Fanout(["openrouter/deepseek/deepseek-v4-pro", "openrouter/z-ai/glm-5.2"])
        >> sf.Synthesize("openrouter/moonshotai/kimi-k3")
    ),
    "docs-quickstart-233-trio": _quickstart_trio,
    "extra-named-pipeline-synthesizer": lambda: (
        sf.Fanout(_PAIR)
        >> sf.Synthesize(sf.Pipeline(["provider/j", "provider/w"], name="judge-write"))
    ),
    "extra-named-pipeline-of-one-fusion": lambda: sf.Pipeline(
        [sf.Fanout(_PAIR), sf.Synthesize("provider/s")], name="x"
    ),
    "extra-nested-fusion": lambda: (
        sf.Fanout(
            [sf.Fanout(["provider/a", "provider/b"]) >> sf.Synthesize("provider/s1"), "provider/c"]
        )
        >> sf.Synthesize("provider/s2")
    ),
    "extra-300-members": lambda: (
        sf.Fanout([f"provider/m{index}" for index in range(300)]) >> sf.Synthesize("provider/s")
    ),
    "readme-339-by-label": lambda: (
        sf.Fanout(_ROUTES) >> sf.JudgePick(_OPUS5, rubric="Pick the most correct answer.")
    ),
    "readme-345-by-scores": lambda: (
        sf.Fanout(_ROUTES)
        >> sf.Judge(_OPUS5, rubric=_HIGHER, params={"temperature": 0})
        >> sf.ArgMax("score:judge")
    ),
    "readme-387-judge-weighted": lambda: (
        sf.Fanout(_ROUTES)
        >> sf.Judge(_OPUS5, rubric="Score each answer.")
        >> sf.Vote(over="last_number", normalize="numeric", weights="score:judge")
    ),
    "readme-397-judge-weighted-block": lambda: (
        sf.Fanout(_ROUTES)
        >> sf.Judge(_OPUS5, rubric="Score each answer.")
        >> sf.Vote(over=sf.Extract("last_number", normalize="numeric"), weights="score:judge")
    ),
    "readme-418-pick-confidence": lambda: sf.Fanout(_ROUTES) >> sf.ArgMax("field:confidence"),
    "readme-528-rank-by-field": lambda: (
        sf.Fanout(_ROUTES) >> sf.Rank(2, by="field:score") >> sf.Synthesize("provider/next")
    ),
    "readme-419-pick-answer": lambda: (
        sf.Fanout(_ROUTES) >> sf.First(where=sf.field("answer", normalize="text") == "yes")
    ),
    "readme-422-cheapest": lambda: sf.Fanout(_ROUTES) >> sf.ArgMin("cost_usd"),
    "readme-424-cheapest-block": lambda: sf.Fanout(_ROUTES) >> sf.ArgMin(sf.signal("cost_usd")),
    "readme-428-merged": lambda: (
        sf.Fanout(_ROUTES)
        >> sf.Merge(
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
        sf.Fanout(_ROUTES)
        >> sf.Judge(_OPUS5, rubric=_HIGHER)
        >> sf.Rank(2, by="score:judge")
        >> sf.Synthesize(
            "anthropic/claude-sonnet-5", prompt="Write the final answer from these drafts."
        )
    ),
    "readme-529-joined": lambda: (
        sf.Fanout(_ROUTES)
        >> sf.Concat(separator="\n\n---\n\n", label=True)
        >> sf.Synthesize("provider/next")
    ),
    "extra-fusion-then-model": lambda: (
        sf.Fanout(_PAIR) >> sf.Synthesize("provider/s") >> "provider/after"
    ),
}
_EXAMPLES = {example.slug: example for example in EXAMPLES}


def test_every_doc_example_is_in_the_new_form() -> None:
    assert set(_NEW_FORM) == set(_EXAMPLES)


# LO-P3: every doc example equals its golden and its frozen row. The field pick (418) and the field
# rank (528) read a signal since the swap (overview §4.2): their goldens hold those new bytes.
@pytest.mark.parametrize("slug", sorted(_NEW_FORM))
def test_lop1_doc_example_compiles_to_the_bytes_of_today(slug: str) -> None:
    example: DocExample = _EXAMPLES[slug]
    golden = (_GOLDEN_DIR / f"{slug}.url4").read_text(encoding="utf-8").removesuffix("\n")

    new = compile_example(example, _NEW_FORM[slug]())

    assert new == frozen_url4(f"surface_parity:{slug}")
    assert new == golden


# ---------------------------------------- LO-P2 and LO-P3 (lowering §3, swap §1 7h)

_W = "openrouter/openai/gpt-5.5"
_P = "Write the final answer from the selected drafts."
_JR = "openrouter/anthropic/claude-opus-4.8"
_R_MAX = "Give a higher number to a more correct answer."
_R_MIN = "Give a lower number to a more correct answer."


def _writer() -> sf.Synthesize:
    return sf.Synthesize(_W, prompt=_P)


_STEPS: dict[str, Callable[[], sf.Recipe]] = {
    "S5": lambda: sf.Fanout(_json_members()) >> sf.ArgMax("field:confidence", output="answer"),
    "S7": lambda: sf.Fanout(_json_members()) >> sf.Rank(2, by="field:confidence") >> _writer(),
    "S8": lambda: (
        sf.Fanout(_json_members()) >> sf.ArgMax(sf.signal("field:confidence"), output="answer")
    ),
    "S9": lambda: (
        sf.Fanout(_json_members())
        >> sf.Filter(where=sf.signal("field:confidence") > 0.7)
        >> _writer()
    ),
    "S10": lambda: (
        sf.Fanout(_ROUTES)
        >> sf.Judge(_JR, rubric=_R_MAX)
        >> sf.Rank(2, by="score:judge")
        >> _writer()
    ),
    "S10'": lambda: (
        sf.Fanout(_ROUTES)
        >> sf.Judge(_JR, rubric=_R_MAX)
        >> sf.Filter(where=sf.signal("score:judge") >= 7)
        >> _writer()
    ),
    "S11": lambda: sf.Fanout(_ROUTES) >> sf.Judge(_JR, rubric=_R_MAX) >> sf.ArgMax("score:judge"),
    "S11'": lambda: sf.Fanout(_ROUTES) >> sf.Judge(_JR, rubric=_R_MIN) >> sf.ArgMin("score:judge"),
}


# LO-P3: the rows whose bytes changed at the swap. S5 and S7 read the field as a signal (overview
# §4.2); S10, S10', S11 and S11' write the neutral judge-template@2 (§4.1). Their rows in
# surface_parity.json were frozen after those changes, so the frozen rows are their new goldens.
_CHANGED = ("S5", "S7", "S10", "S10'", "S11", "S11'")


@pytest.mark.parametrize("case", sorted(set(_STEPS) - set(_CHANGED)))
def test_lop2_notebook_case_compiles_to_the_bytes_of_today(case: str) -> None:
    assert _url4(_STEPS[case]()) == frozen_url4(f"surface_parity:{case}")


@pytest.mark.parametrize("case", _CHANGED)
def test_lop3_a_row_that_changed_at_the_swap_equals_its_new_golden(case: str) -> None:
    url4 = _url4(_STEPS[case]())

    assert url4 == frozen_url4(f"surface_parity:{case}")
    if case in ("S5", "S7"):
        assert "by_signal@1" in url4
        assert "json_field@1" not in url4
    else:
        assert url4.count("judge-template@2") == 1
        assert "judge-template@1" not in url4


def test_lop3_the_field_pick_s5_is_the_signal_pick_s8() -> None:
    assert _url4(_STEPS["S5"]()) == _url4(_STEPS["S8"]())
