# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai), absent in
# the default (extra-less) install the typecheck gate runs against; it is loaded only behind
# `inspect_available()`, like every other module in this package.
"""ContractEval as a LOCAL inspect Task — the hand-built folder in inspect's shape (OME-1527).

Think of it as the same exam, now printed by the shared press: a dataset loader that prints the
question booklet, a scorer that marks one reply, a tally sheet that turns the marks into the
paper's F1, and one `@task` that binds them. The importer seals the Cases by digest and the
plugin's shared serving path does the rest.

Execution order, as the importer and the Engine see it:

    1. `contracteval()` → `load_cuad_test()`: inspect's `hf_dataset` reads the pinned CUAD test
       split (the importer forces the recorded Hub commit at every build) and renders each row
       into a Sample whose `input` is the exact Candidate-facing text and whose `target` is the
       LIST of gold clause sentences — `[]` on the 2,938 of 4,182 rows with no clause, which
       the row's `empty_answer_key_allowed` keeps as `[]` (inspect's `Target([])` holds no
       answer; `Target("")` would hold one blank answer found inside every reply).
    2. the importer replays that twice in a clean child and seals the Cases by digest; at
       build, prepare replays it once more and serves nothing unless the digest matches.
    3. at grading, `contracteval_containment` marks each reply 1 or 0 with the paper's rule
       (`grading.verdict`) and writes the Case's confusion-matrix facts on the Score.
    4. after the last Case, the row's whole-run metric `contracteval_f1` rebuilds the run's
       confusion matrix from those facts and returns the paper's F1 (the Headline Score, the
       row's `whole_run_headline`) beside the hand-built Benchmark's other run numbers.

INVARIANT — the headline is F1 from a RUN-level confusion matrix, never a mean of Case scores.
70.3% of rows have no clause, so a model that always declines is right on 70% of Cases (a mean
of 0.70) while answering nothing; F1 scores it 0. The mean is still what each Case's own score
says (1 = correct), so the Report's per-Case view stays honest.

INVARIANT — the prompt bytes are Benchmark identity (they sit inside the Case Digest) and equal
the hand-built Benchmark's byte for byte. The WHOLE text goes in one user message: capture
joins a system message to the user text with a blank line, while the reference joins them with
one newline, so a system message would move the bytes. `test_local_task_contracteval.py` pins
them.

References:
    - Paper: https://arxiv.org/abs/2508.03080 · https://aclanthology.org/2025.nllp-1.19/
    - Reference harness: https://github.com/olivialiu121/ContractEval (MIT)
      @ f2de74479bb067a13da2fd034972eec6905563b2 (repo tip at the 2026-09-09 fetch)
    - Case Source: https://huggingface.co/datasets/theatticusproject/cuad-qa (CC BY 4.0)
"""

from __future__ import annotations

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Dataset, Sample, hf_dataset
from inspect_ai.scorer import Metric, SampleScore, Score, Scorer, Target, metric, scorer
from inspect_ai.solver import TaskState, generate

from screamingface_engine_inspect.local_tasks.contracteval.grading import (
    f1,
    is_abstention,
    jaccard,
    verdict,
)

# ── pins (the hand-built revision_inputs.py) ─────────────────────────────────────────────
DATASET = "theatticusproject/cuad-qa"
DATASET_SPLIT = "test"
# WHY a `refs/convert/parquet` commit and not a `main` one: CUAD's `main` carries only a
# loading SCRIPT, which `datasets` 4.x no longer runs; the Hub's auto-converted parquet branch
# is the only loadable form, and its commit pins the bytes as tightly as a `main` SHA would.
DATASET_REVISION = "d9c4ee0250ae2eb97bdb5b50773ab14ea62d0631"

# ── the prompt (byte-identical to the hand-built prompts.py) ─────────────────────────────
# INVARIANT: byte-for-byte from the reference harness at the pinned commit —
# `proprietary_model.py` lines 75-79 for the system prompt and lines 19-27 for the user
# template. KNOWN one-byte delta (review of PR #984): the reference's user template opens with
# `"Context: \n"` (trailing space) and `USER_TEMPLATE` drops it; kept, because these bytes have
# been published and restoring it would be a second, silent change of Benchmark.
# WHY the wording matters more than usual: the grader is string containment, so "Do not
# rephrase or summarize in any way" is the difference between a correct answer and a zero.
SYSTEM_PROMPT = """You are an assistant with strong legal knowledge, supporting senior lawyers \
by preparing reference materials.
Given a Context and a Question, extract and return only the sentence(s) from the Context that \
directly address or relate to the Question.
Do not rephrase or summarize in any way—respond with exact sentences from the Context relevant \
to the Question. If a relevant sentence contains unrelated elements such as page numbers or \
whitespace, include them exactly as they appear.
If no part of the Context is relevant to the Question, respond with: "No related clause."
"""

USER_TEMPLATE = """Context:
```
{context}
```
Question:
```
{question}
```
"""


def render_case_input(context: str, question: str) -> str:
    """The exact Candidate-facing text for one Case — system instructions plus the pair."""

    return f"{SYSTEM_PROMPT}\n{USER_TEMPLATE.format(context=context, question=question)}"


# ── dataset loader ────────────────────────────────────────────────────────────────────────
def load_cuad_test() -> Dataset:
    """Read the pinned CUAD test split and render each row into a Sample."""

    return hf_dataset(
        DATASET,
        split=DATASET_SPLIT,
        revision=DATASET_REVISION,
        sample_fields=record_to_sample,
    )


def record_to_sample(row: dict[str, Any]) -> Sample:
    """One CUAD row → the Candidate-facing text and the gold clause sentences as the key.

    CUAD row shape: `id` · `title` (contract) · `context` (full contract text) · `question`
    (one of 41 clause categories) · `answers: {text: [...], answer_start: [...]}`. An empty
    `answers.text` means no clause of that category exists.
    """

    return Sample(
        id=row["id"],
        input=render_case_input(row["context"], row["question"]),
        # A list, `[]` when no clause exists: the scorer reads emptiness as "decline".
        target=list(row["answers"]["text"]),
        # The only link back to the dataset row; private Grading Material, never published.
        metadata={"source_id": row["id"]},
    )


# ── the run's tally sheet ─────────────────────────────────────────────────────────────────
@metric
def contracteval_f1() -> Metric:
    """The paper's F1 over the run's confusion matrix, beside the paper's other run numbers.

    Each graded Case lands in one cell: a Case with a clause is a true positive when marked
    correct, else a false negative; a Case with none is a true negative when marked correct,
    else a false positive. A Case whose grading failed never reaches the metric, so an outage
    is never filed as a miss.

    Returns a dict under the hand-built Benchmark's key names, so a Report reads the same
    keys as before the move: ``f1`` (the row's ``whole_run_headline``, the Headline Score),
    then ``accuracy``, ``precision``, ``recall``, ``f2``, the four cell counts, the decline
    rate ``no_related_clause_rate``, the *laziness* rate ``false_no_related_clause_rate``
    (declines on Cases that have a clause, over those Cases) and ``jaccard_mean`` (token
    overlap, over Cases that have a clause only, as the reference merges it). The tally
    publishes every key but ``f1`` as a run metric beside its own ``scored_cases``, which is
    why this dict leaves that one out.

    Worked example (the 8 canned replies the conservation test pins): TP 3, FN 2, TN 2, FP 1
    → precision 3/4 = 0.75, recall 3/5 = 0.6, F1 0.6667, F2 5·0.75·0.6 / (4·0.75 + 0.6) =
    0.625; 1 decline among the 5 clause Cases → laziness 0.2.

    Raises KeyError on a Score that lacks `is_positive`: only `contracteval_containment` writes
    it, and guessing a missing cell would file the Case wrongly with no failure anywhere.
    """

    def compute(scores: list[SampleScore]) -> dict[str, float | int]:
        true_positives: int = 0
        false_negatives: int = 0
        true_negatives: int = 0
        false_positives: int = 0
        declines: int = 0
        lazy_declines: int = 0
        overlaps: list[float] = []
        for sample_score in scores:
            facts: dict[str, Any] = sample_score.score.metadata or {}
            is_positive: bool = bool(facts["is_positive"])
            declined: bool = bool(facts["abstained"])
            correct: bool = sample_score.score.as_float() >= 1.0
            declines += 1 if declined else 0
            if is_positive:
                overlaps.append(float(facts["jaccard"]))
                lazy_declines += 1 if declined else 0
                true_positives, false_negatives = (
                    (true_positives + 1, false_negatives)
                    if correct
                    else (true_positives, false_negatives + 1)
                )
            else:
                true_negatives, false_positives = (
                    (true_negatives + 1, false_positives)
                    if correct
                    else (true_negatives, false_positives + 1)
                )
        graded: int = len(scores)
        positives: int = true_positives + false_negatives
        found: int = true_positives + false_positives
        precision: float = true_positives / found if found else 0.0
        recall: float = true_positives / positives if positives else 0.0
        # The hand-built reducer's F2, with the same zero guard as F1.
        f2: float = (
            5 * precision * recall / (4 * precision + recall) if 4 * precision + recall else 0.0
        )
        return {
            "f1": f1(true_positives, false_negatives, false_positives),
            "accuracy": round((true_positives + true_negatives) / graded, 4) if graded else 0.0,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f2": round(f2, 4),
            "true_positives": true_positives,
            "false_negatives": false_negatives,
            "true_negatives": true_negatives,
            "false_positives": false_positives,
            "no_related_clause_rate": round(declines / graded, 4) if graded else 0.0,
            # NAMED DEVIATION (kept from the hand-built Benchmark): the reference divides by a
            # hardcoded 1244, the full split's clause count, which is wrong for any subset run.
            "false_no_related_clause_rate": (
                round(lazy_declines / positives, 4) if positives else 0.0
            ),
            "jaccard_mean": round(sum(overlaps) / len(overlaps), 4) if overlaps else 0.0,
        }

    return compute


# ── the scorer ────────────────────────────────────────────────────────────────────────────
@scorer(metrics=[contracteval_f1()])
def contracteval_containment() -> Scorer:
    """Mark one reply: every gold sentence quoted verbatim, or a rightful "No related clause."

    The Score's metadata carries the Case's cell facts, the same three the hand-built check
    record published: whether the Case has a clause, whether the reply declined, and the
    reply's Jaccard overlap with the gold text (per-Case evidence only).
    """

    async def score(state: TaskState, target: Target) -> Score:
        reply: str = state.output.completion
        gold_spans: list[str] = list(target.target)
        correct: bool = verdict(reply, gold_spans)
        return Score(
            value=1.0 if correct else 0.0,
            metadata={
                "is_positive": bool(gold_spans),
                "abstained": is_abstention(reply),
                "jaccard": jaccard(gold_spans, reply),
            },
        )

    return score


# ── the Task ──────────────────────────────────────────────────────────────────────────────
@task
def contracteval() -> Task:
    """ContractEval on CUAD test: 4,182 clause-extraction questions over 102 contracts."""

    return Task(
        dataset=load_cuad_test(),
        solver=generate(),
        scorer=contracteval_containment(),
    )
