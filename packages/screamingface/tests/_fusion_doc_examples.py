"""Every ``sf.Fusion(`` example of the SDK README and the public docs, as a factory (not a test).

FEATURE (FR#1): the Fusion recipe rewrite (unit 10S, Commit G) must not change one byte of what an
existing Fusion compiles to. ``test_fusion_doc_goldens.py`` freezes the url4 of each example below
BEFORE the rewrite; the rewrite tests then re-derive the block form of the same examples.

Each factory carries a ``# <file>:<line>`` comment. A variable the snippet does not define is taken
from the nearest definition on the same page, and the comment says so.

Non-examples (listed so a later reader sees they were looked at, and why they are skipped):
- signature strings: ``fusionSig`` in public-docs guides/FusionsPage.vue:39 and
  api/FusionsPage.vue:12, and the ``<td>`` row at guides/FusionsPage.vue:163;
- repr-output strings: ``basicOut`` (guides/FusionsPage.vue:19), ``synthOut`` (:32), ``nestedOut``
  (:37) and ``recursiveOut`` (guides/PipelinesPage.vue:43).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from _combine_flow_fixtures import flow_operators

import screamingface as sf
from screamingface._evaluation.answer_rule import _AnswerRule, _BenchmarkAnswerRule
from screamingface._evaluation.candidate import compile_candidate

README = "packages/screamingface/README.md"
DOCS = "public-docs/src/pages/sf-client"

_ROUTES = [
    "openrouter/openai/gpt-5.5",
    "openrouter/anthropic/claude-opus-4.8",
    "openrouter/google/gemini-3.1-pro-preview",
]
_GSM8K_RULE = _BenchmarkAnswerRule(
    "inspect-gsm8k",
    _AnswerRule(
        "inspect_number@1", "inspect_numeric@1", "inspect_ai.scorer:match(numeric=True)@0.3.263"
    ),
)


@dataclass(frozen=True, slots=True)
class DocExample:
    slug: str
    source: str  # "<file>:<line>" of the ``sf.Fusion(`` call
    build: Callable[[], sf.Recipe]
    reducer: bool = False  # compiles with the flow operator catalog
    benchmark: bool = False  # compiles with the GSM8K answer rule
    wrapped: bool = False  # a selection, wrapped as Pipeline([x, "provider/next"]) to compile


def compile_example(example: DocExample, recipe: sf.Recipe | None = None) -> str:
    """The url4 of an example (or of ``recipe``, a rewritten twin of it), as compiled today."""

    chosen = example.build() if recipe is None else recipe
    return compile_candidate(
        chosen,
        operators=flow_operators() if example.reducer else None,
        benchmark_rule=_GSM8K_RULE if example.benchmark else None,
    ).url4


def _opus() -> sf.Model:
    return sf.Model("openrouter/anthropic/claude-opus-4.8")


def _gpt() -> sf.Model:
    return sf.Model("openrouter/openai/gpt-5.5")


# ---------------------------------------------------------------- README.md


def _readme_frontier_pair() -> sf.Recipe:  # README.md:57
    return sf.Fusion(
        [_opus(), _gpt()],
        name="frontier-pair",
        synthesizer="openrouter/anthropic/claude-opus-4.8",
    )


def _readme_pair() -> sf.Recipe:  # README.md:119 (opus and gpt: README.md:54-55)
    return sf.Fusion(
        [_opus(), _gpt()],
        synthesizer="openrouter/anthropic/claude-opus-4.8",
    )


def _readme_constraint_aware() -> sf.Recipe:  # README.md:134 (opus and gpt: README.md:54-55)
    return sf.Fusion(
        [_opus(), _gpt()],
        synthesizer=sf.Model(
            "openrouter/openai/gpt-5.5",
            prompt=(
                "Produce one final answer that preserves every constraint in the original request."
            ),
            params={"reasoning_effort": "high"},
        ),
    )


def _readme_samples_vote() -> sf.Recipe:  # README.md:158
    return sf.Fusion(
        sf.samples("openrouter/openai/gpt-5.5", 5, temperature=0.7),
        synthesizer=sf.Vote(extract="last_number", normalize="numeric"),
    )


def _readme_recursive() -> sf.Recipe:  # README.md:222 (draft, review, final: README.md:200-207)
    draft = sf.Model("openrouter/openai/gpt-5.5")
    review = sf.Model(
        "openrouter/anthropic/claude-opus-4.8",
        prompt="Review the previous answer and return a corrected answer.",
    )
    final = sf.Model(
        "openrouter/openai/gpt-5.5",
        prompt="Polish the previous answer without adding unsupported claims.",
    )
    review_chain = sf.Pipeline([draft, review, final], name="review-chain")
    judge = sf.Model("openrouter/anthropic/claude-opus-4.8")
    writer = sf.Model("openrouter/openai/gpt-5.5")
    return sf.Fusion(
        [
            review_chain,
            sf.Model("openrouter/google/gemini-3.1-pro-preview"),
        ],
        synthesizer=sf.Pipeline([judge, writer]),
    )


def _readme_by_vote() -> sf.Recipe:  # README.md:260
    return sf.Fusion(_ROUTES, synthesizer=sf.Vote(extract="last_number", normalize="numeric"))


def _readme_by_median() -> sf.Recipe:  # README.md:261
    return sf.Fusion(_ROUTES, synthesizer=sf.Median(extract="last_number", select="value"))


def _readme_by_grader() -> sf.Recipe:  # README.md:273
    return sf.Fusion(_ROUTES, synthesizer=sf.Vote(extract="benchmark"))


def _readme_fixed() -> sf.Recipe:  # README.md:290
    return sf.Fusion(_ROUTES, synthesizer=sf.Vote(weights=[2, 1, 1]))


def _readme_by_confidence_weighted() -> sf.Recipe:  # README.md:293
    return sf.Fusion(
        _ROUTES,
        synthesizer=sf.Reduce(
            "weighted",
            extract=sf.Extract("field", path="answer", normalize="text"),
            weights=sf.signal("field:confidence"),
        ),
    )


def _readme_by_cost() -> sf.Recipe:  # README.md:303
    return sf.Fusion(_ROUTES, synthesizer=sf.Vote(weights=sf.signal("cost_usd")))


def _readme_by_cost_block() -> sf.Recipe:  # README.md:304
    return sf.Fusion(
        _ROUTES,
        synthesizer=sf.Reduce(
            "weighted",
            extract=sf.Extract("last_line", normalize="text"),
            weights=sf.signal("cost_usd"),
        ),
    )


def _readme_by_label() -> sf.Recipe:  # README.md:339
    return sf.Fusion(
        _ROUTES,
        synthesizer=sf.Judge(
            "anthropic/claude-opus-5", returns="label", rubric="Pick the most correct answer."
        ),
    )


def _readme_by_scores() -> sf.Recipe:  # README.md:345
    return sf.Fusion(
        _ROUTES,
        synthesizer=sf.Judge(
            "anthropic/claude-opus-5",
            returns="scores",
            rubric="Give a higher number to a more correct answer.",
            params={"temperature": 0},
        ),
    )


def _readme_weighted() -> sf.Recipe:  # README.md:387
    return sf.Fusion(
        _ROUTES,
        synthesizer=sf.Vote(
            extract="last_number",
            normalize="numeric",
            weights=sf.signal("score:judge"),
            judge=sf.Judge(
                "anthropic/claude-opus-5", returns="scores", rubric="Score each answer."
            ),
        ),
    )


def _readme_weighted_block() -> sf.Recipe:  # README.md:397
    return sf.Fusion(
        _ROUTES,
        synthesizer=sf.Reduce(
            "weighted",
            extract=sf.Extract("last_number", normalize="numeric"),
            weights=sf.signal("score:judge"),
            judge=sf.Judge(
                "anthropic/claude-opus-5", returns="scores", rubric="Score each answer."
            ),
        ),
    )


def _readme_pick_confidence() -> sf.Recipe:  # README.md:418
    return sf.Fusion(_ROUTES, synthesizer=sf.Pick("confidence", order="max"))


def _readme_pick_answer() -> sf.Recipe:  # README.md:419
    return sf.Fusion(_ROUTES, synthesizer=sf.Pick("answer", equals="yes", normalize="text"))


def _readme_cheapest() -> sf.Recipe:  # README.md:422
    return sf.Fusion(_ROUTES, synthesizer=sf.Pick(by_signal=sf.signal("cost_usd"), order="min"))


def _readme_cheapest_block() -> sf.Recipe:  # README.md:424
    return sf.Fusion(
        _ROUTES, synthesizer=sf.Reduce("argmax", by_signal=sf.signal("cost_usd"), order="min")
    )


def _readme_merged() -> sf.Recipe:  # README.md:428
    return sf.Fusion(
        _ROUTES,
        synthesizer=sf.Merge(
            fields={
                "answer": sf.FieldRule.majority(normalize="text"),
                "score": sf.FieldRule.max(),
                "source": sf.FieldRule.from_member(2),
                "synonyms": sf.FieldRule.union(normalize="text"),
                "summary": sf.FieldRule.model(
                    "anthropic/claude-sonnet-5", prompt="Write one summary."
                ),
            }
        ),
    )


def _readme_ranked() -> sf.Recipe:  # README.md:514 (the Pipeline of the snippet, as written)
    return sf.Pipeline(
        [
            sf.Fusion(
                _ROUTES,
                synthesizer=sf.Rank(
                    k=2,
                    by=sf.Judge(
                        "anthropic/claude-opus-5",
                        returns="scores",
                        rubric="Give a higher number to a more correct answer.",
                    ),
                ),
            ),
            sf.Model(
                "anthropic/claude-sonnet-5", prompt="Write the final answer from these drafts."
            ),
        ]
    )


def _readme_rank_by_field() -> sf.Recipe:  # README.md:528
    return sf.Pipeline(
        [sf.Fusion(_ROUTES, synthesizer=sf.Rank(k=2, by_field="score")), "provider/next"]
    )


def _readme_joined() -> sf.Recipe:  # README.md:529
    return sf.Pipeline(
        [
            sf.Fusion(_ROUTES, synthesizer=sf.Concat(separator="\n\n---\n\n", label=True)),
            "provider/next",
        ]
    )


# ---------------------------------------------------------------- public-docs


def _docs_overview() -> sf.Recipe:  # public-docs .../Index.vue:27
    gpt = sf.Model("openrouter/openai/gpt-5.5")
    flash = sf.Model("openrouter/google/gemini-3-flash-preview")
    return sf.Fusion([gpt, flash], synthesizer="openrouter/openai/gpt-5.5")


def _docs_first_fusion() -> sf.Recipe:  # public-docs .../FirstFusionPage.vue:15
    return sf.Fusion(
        ["openrouter/openai/gpt-5.5", "openrouter/google/gemini-3-flash-preview"],
        synthesizer="openrouter/openai/gpt-5.5",
    )


def _docs_pipelines_recursive() -> sf.Recipe:  # public-docs .../guides/PipelinesPage.vue:39
    # draft, review: PipelinesPage.vue:15-16 (the `basic` cell)
    draft = sf.Model("openrouter/openai/gpt-5.5")
    review = sf.Model("openrouter/anthropic/claude-opus-4.8")
    judge = sf.Model("openrouter/anthropic/claude-opus-4.8", name="judge")
    writer = sf.Model("openrouter/openai/gpt-5.5", name="writer")
    return sf.Fusion(
        [draft.then(review), sf.Model("openrouter/google/gemini-3.1-pro-preview")],
        synthesizer=sf.Pipeline([judge, writer]),
    )


def _docs_pipelines_mixed() -> sf.Recipe:  # public-docs .../guides/PipelinesPage.vue:45
    # draft, review: PipelinesPage.vue:15-16; final: PipelinesPage.vue:20 (the `then` cell)
    draft = sf.Model("openrouter/openai/gpt-5.5")
    review = sf.Model("openrouter/anthropic/claude-opus-4.8")
    final = sf.Model("openrouter/openai/gpt-5.5", name="polish")
    panel = sf.Fusion([draft, review], synthesizer=final)
    refine = sf.Pipeline([review, final], name="refine")
    return sf.Pipeline([draft, panel, refine], name="mixed")


def _docs_fusions_pair() -> sf.Recipe:  # public-docs .../guides/FusionsPage.vue:17
    return sf.Fusion([_opus(), _gpt()], synthesizer="openrouter/anthropic/claude-opus-4.8")


def _docs_fusions_synth() -> sf.Recipe:  # public-docs .../guides/FusionsPage.vue:24
    return sf.Fusion(
        [_opus(), _gpt()],
        name="pair-gpt-synth",
        synthesizer=sf.Model(
            "openrouter/openai/gpt-5.5",
            prompt="Write the final answer from the drafts.",
        ),
    )


def _docs_fusions_nested() -> sf.Recipe:  # public-docs .../guides/FusionsPage.vue:36
    # pair: FusionsPage.vue:17; haiku: FusionsPage.vue:34
    pair = sf.Fusion([_opus(), _gpt()], synthesizer="openrouter/anthropic/claude-opus-4.8")
    haiku = sf.Model("openrouter/anthropic/claude-haiku-4.5")
    return sf.Fusion([pair, haiku], name="nested", synthesizer="openrouter/openai/gpt-5.5")


def _docs_evaluation_many() -> sf.Recipe:  # public-docs .../guides/EvaluationPage.vue:33
    return sf.Fusion([_opus(), _gpt()], synthesizer="openrouter/openai/gpt-5.5")


def _docs_api_fusion() -> sf.Recipe:  # public-docs .../api/FusionsPage.vue:19
    return sf.Fusion(
        ["openrouter/deepseek/deepseek-v4-pro", "openrouter/z-ai/glm-5.2"],
        synthesizer="openrouter/moonshotai/kimi-k3",
    )


def _docs_quickstart_trio() -> sf.Recipe:  # public-docs .../QuickstartPage.vue:233
    answer = "Answer this research prompt thoroughly, in prose, with specific evidence."
    synthesis = "Combine the panel's answers into one unified prose answer. Add no new facts."
    opus = sf.Model("openrouter/anthropic/claude-opus-4.8", prompt=answer)
    gpt = sf.Model("openrouter/openai/gpt-5.5", prompt=answer)
    gemini = sf.Model(
        "openrouter/google/gemini-3.1-pro-preview",
        prompt=answer,
        params={"temperature": 0, "max_tokens": 8192},
    )
    return sf.Fusion(
        [opus, gpt, gemini],
        name="frontier-trio",
        synthesizer=sf.Model(
            "openrouter/anthropic/claude-opus-4.8",
            prompt=synthesis,
            params={"temperature": 0, "max_tokens": 8192},
        ),
    )


# ---------------------------------------------------------------- extra recipes for later rows

_PAIR = ["provider/a", "provider/b"]


def _extra_named_pipeline_synthesizer() -> sf.Recipe:
    return sf.Fusion(
        _PAIR, synthesizer=sf.Pipeline(["provider/j", "provider/w"], name="judge-write")
    )


def _extra_named_pipeline_of_one_fusion() -> sf.Recipe:
    return sf.Pipeline([sf.Fusion(_PAIR, synthesizer="provider/s")], name="x")


def _extra_nested_fusion() -> sf.Recipe:
    return sf.Fusion(
        [sf.Fusion(["provider/a", "provider/b"], synthesizer="provider/s1"), "provider/c"],
        synthesizer="provider/s2",
    )


def _extra_300_members() -> sf.Recipe:
    return sf.Fusion([f"provider/m{index}" for index in range(300)], synthesizer="provider/s")


def _extra_fusion_then_model() -> sf.Recipe:
    return sf.Pipeline([sf.Fusion(_PAIR, synthesizer="provider/s"), "provider/after"])


def _doc(slug: str, source: str, build: Callable[[], sf.Recipe], **flags: bool) -> DocExample:
    return DocExample(slug, source, build, **flags)


EXAMPLES: tuple[DocExample, ...] = (
    _doc("readme-57-frontier-pair", f"{README}:57", _readme_frontier_pair),
    _doc("readme-119-pair", f"{README}:119", _readme_pair),
    _doc("readme-134-constraint-aware", f"{README}:134", _readme_constraint_aware),
    _doc("readme-158-samples-vote", f"{README}:158", _readme_samples_vote, reducer=True),
    _doc("readme-222-recursive", f"{README}:222", _readme_recursive),
    _doc("readme-260-by-vote", f"{README}:260", _readme_by_vote, reducer=True),
    _doc("readme-261-by-median", f"{README}:261", _readme_by_median, reducer=True),
    _doc(
        "readme-273-by-grader",
        f"{README}:273",
        _readme_by_grader,
        reducer=True,
        benchmark=True,
    ),
    _doc("readme-290-fixed-weights", f"{README}:290", _readme_fixed, reducer=True),
    _doc(
        "readme-293-by-confidence-weighted",
        f"{README}:293",
        _readme_by_confidence_weighted,
        reducer=True,
    ),
    _doc("readme-303-by-cost", f"{README}:303", _readme_by_cost, reducer=True),
    _doc("readme-304-by-cost-block", f"{README}:304", _readme_by_cost_block, reducer=True),
    _doc("readme-339-by-label", f"{README}:339", _readme_by_label, reducer=True),
    _doc("readme-345-by-scores", f"{README}:345", _readme_by_scores, reducer=True),
    _doc("readme-387-judge-weighted", f"{README}:387", _readme_weighted, reducer=True),
    _doc("readme-397-judge-weighted-block", f"{README}:397", _readme_weighted_block, reducer=True),
    _doc("readme-418-pick-confidence", f"{README}:418", _readme_pick_confidence, reducer=True),
    _doc("readme-419-pick-answer", f"{README}:419", _readme_pick_answer, reducer=True),
    _doc("readme-422-cheapest", f"{README}:422", _readme_cheapest, reducer=True),
    _doc("readme-424-cheapest-block", f"{README}:424", _readme_cheapest_block, reducer=True),
    _doc("readme-428-merged", f"{README}:428", _readme_merged, reducer=True),
    _doc("readme-514-ranked", f"{README}:514", _readme_ranked, reducer=True),
    _doc(
        "readme-528-rank-by-field",
        f"{README}:528",
        _readme_rank_by_field,
        reducer=True,
        wrapped=True,
    ),
    _doc("readme-529-joined", f"{README}:529", _readme_joined, reducer=True, wrapped=True),
    _doc("docs-index-27-overview", f"{DOCS}/Index.vue:27", _docs_overview),
    _doc("docs-first-fusion-15", f"{DOCS}/FirstFusionPage.vue:15", _docs_first_fusion),
    _doc(
        "docs-pipelines-39-recursive",
        f"{DOCS}/guides/PipelinesPage.vue:39",
        _docs_pipelines_recursive,
    ),
    _doc("docs-pipelines-45-mixed", f"{DOCS}/guides/PipelinesPage.vue:45", _docs_pipelines_mixed),
    _doc("docs-fusions-17-pair", f"{DOCS}/guides/FusionsPage.vue:17", _docs_fusions_pair),
    _doc("docs-fusions-24-synth", f"{DOCS}/guides/FusionsPage.vue:24", _docs_fusions_synth),
    _doc("docs-fusions-36-nested", f"{DOCS}/guides/FusionsPage.vue:36", _docs_fusions_nested),
    _doc("docs-evaluation-33-many", f"{DOCS}/guides/EvaluationPage.vue:33", _docs_evaluation_many),
    _doc("docs-api-fusions-19", f"{DOCS}/api/FusionsPage.vue:19", _docs_api_fusion),
    _doc("docs-quickstart-233-trio", f"{DOCS}/QuickstartPage.vue:233", _docs_quickstart_trio),
    _doc("extra-named-pipeline-synthesizer", "extra", _extra_named_pipeline_synthesizer),
    _doc("extra-named-pipeline-of-one-fusion", "extra", _extra_named_pipeline_of_one_fusion),
    _doc("extra-nested-fusion", "extra", _extra_nested_fusion),
    _doc("extra-300-members", "extra", _extra_300_members),
    _doc("extra-fusion-then-model", "extra", _extra_fusion_then_model),
)
