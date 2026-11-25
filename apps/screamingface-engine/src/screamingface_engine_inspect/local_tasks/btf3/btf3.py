# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai,
# huggingface_hub, pyarrow), absent in the default (extra-less) install the typecheck gate runs
# against; it is loaded only behind `inspect_available()`, like every other module in this package.
"""BTF-3's binary questions as a LOCAL inspect Task, run the way the contributor's study ran them.

FEATURE: forecasting Benchmarks for fused LLM committees (spec
docs/spec/2026-11-17-btf3-local-task.md; design ScreamingFace/screamingface#1868, OME-1938).
STORY: as a researcher whose paper scored forecasters on BTF-3, I rerun the same yes/no questions
with the paper's prompt and grading rule on ScreamingFace and compare.

Think of it as a forecasting exam with the answers sealed: each question comes with background
and resolution criteria, the model writes a probability that the answer is Yes, and the mark is
whether that probability fell on the right side of one half (accuracy), with how far it landed
from what happened, squared (the Brier score), kept beside it.

Execution order, as the importer and the Engine see it:

    1. ``btf3()`` → ``load_btf3()``: fetch the pinned parquet (commit pin + sha256, refused on
       mismatch); each row becomes a Sample whose ``input`` is the study's prompt (its shortened
       copy of Bench to the Future's A.1, research left empty) with its ``Final answer:`` line
       reworded to name a probability, filled with the row, and whose target is ``"1"`` (Yes)
       or ``"0"``.
    2. the importer replays that twice in a clean child and seals the 1,515 Cases by digest.
    3. at grading, ``btf3_accuracy`` reads the forecast with the study's reader
       (``vendor/study_btf_parse.py``) and marks 1 when ``f >= 0.5`` matches the outcome;
       ``btf3_headline`` reports that accuracy over every Case, the mean Brier beside it, and
       the counts. A reply with no forecast is a miss and costs Brier 0.25: the study's rule
       for a crowd with no decision. For ONE model's unreadable reply the paper drops the
       Case from both sides instead, so here that is a NAMED DEVIATION (OME-1938).

INVARIANT: the pins, the template and the row-to-Sample mapping are Benchmark identity (they sit
inside the Case Digest); ``tests/unit/inspect/test_local_task_btf3.py`` pins them.

References:
    - Diverse by Reasoning (the contributor's paper): https://arxiv.org/abs/2608.24001
    - Bench to the Future: https://arxiv.org/abs/2506.21558, Appendix A.1 (the source prompt)
    - Case Source: https://huggingface.co/datasets/futuresearch-ai/BTF-3 (CC-BY-NC-4.0)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import (
    Metric,
    SampleScore,
    Score,
    Scorer,
    Target,
    mean,
    metric,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState, generate

from screamingface_engine_inspect.local_tasks.btf3.vendor.study_btf_parse import btf_parse

# ── pins ────────────────────────────────────────────────────────────────────────────────────
DATASET: Final[str] = "futuresearch-ai/BTF-3"
#: The release the contributor's study downloaded (2026-08-06), the paper's version: 1,515 binary
#: questions. The 2026-09-15 audit release removed 119 questions (1,471 binary remain) and changed
#: 3 binary resolutions, and its card says aggregate scores are not comparable across that
#: boundary (spec §2). Issue #1868 asks for the paper's commit, so this is it.
DATASET_REVISION: Final[str] = "ad5a2165eea26a8a43592ba36ff15765199ddc71"
DATASET_FILE: Final[str] = "btf3_binary_questions_and_forecasts.parquet"
DATASET_SHA256: Final[str] = "50f01603ae5284e48b462ae8855a4b5e8c82004fd07f4a3c818c0e88e9b91c2b"

#: The contributor's study prompt, with ONLY its answer line reworded. The study sent
#: ``bench_formats.btf_render(forecast_prompts.BTF, "tight")`` (3,325 bytes);
#: ``forecast_prompts.BTF`` is a shortened copy of Bench to the Future's Appendix A.1 "No
#: Evidence Forecaster" prompt (the worked examples, one tip and the parentheticals under (11)
#: dropped; ``<research>`` empty), and the study swapped A.1's closing line for its
#: ``Final answer:`` line at send time. WHY the rewording (contributor's decision, 2026-11-18):
#: the study's line named the answer only "a number between 0 and 1"; ours keeps A.1's "final
#: answer as a probability between 0 and 1" and the study's exact ``Final answer:`` format, so
#: the reader is unchanged. Putting the study's line back gives its prompt as sent, byte for
#: byte (tests pin both); ``{today}`` is the date part of ``present_date`` (spec §12).
PROMPT_TEMPLATE: Final[str] = """You are a professional forecaster interviewing for a job.

Your interview question is:

You are tasked with giving a probabilistic forecast for the following question:
<question>
{question}
</question>

Here is some background on the question that you may find helpful:
<background>
{background}
</background>

The following criteria specify precisely how the question's resolution will be determined:
<resolution-criteria>
{resolution_criteria}
</resolution-criteria>

Please use the information and research gathered by your trusted assistant below:
<research>
</research>

Today is {today}.

Here are top tips from good forecasters:

If an event was anticipated to happen in a certain timeframe, but 80% of that time has passed and there is no recent news or updates about it happening soon, then you should be skeptical that it will happen in the originally stated timeframe. It probably means that it will be delayed or plans have changed.

Think about base rates for similar events in the past. Sometimes a base rate is the best you can do, if you can't find much information about the question.

Sometimes finding a good base rate is difficult, especially when the events are relatively unique. In these cases, you need to put more weight on the "inside view" which means weighing considerations that appear specific to the situation that lead to a very different forecast than base rates would dictate. You will need to use your own judgment.

Put extra weight on the status quo outcome since the world changes slowly most of the time. This is especially true when coordination or agreement between people or organizations is required.

Think about if there are seasonal effects.

Think about what the current trend is and if it makes sense to extrapolate, or not.

Think about the scope of the question.

Think about the incentives and power of any influential people involved in the situation.

(10) Pre-mortem. Think about how you are most likely to be wrong. Imagine that you are writing a letter to your future self that you will open and read once the outcome is known. In the letter you try to explain to your future self the most likely way that your forecast will be deemed to be a poor forecast. Are you most worried about missing a key piece of information? What is the biggest uncertainty and would keep you awake at night?

(11) More general advice:
 - Even if something seems impossible, think twice before forecasting less than 3%.
 - Even if something seems certain, think twice before forecasting more than 97%.
 - Pay close attention to the exact wording and resolution source in the resolution criteria.
 - Like a good forecaster, you should use your own judgment to come to the most accurate forecast!

Before answering, as part of your reasoning, you write:
(a) The time left until the outcome to the question is known.
(b) The status quo outcome if nothing changed.
(c) Think about answering the question with different scopes to help ensure that you have a self consistent view and have considered the broader context.
(d) A brief description of a scenario that results in a No outcome.
(e) A brief description of a scenario that results in a Yes outcome.

The last thing you write is your final answer as a probability between 0 and 1, on its own line in this format: `Final answer: <probability between 0 and 1>`. Do not write anything after that line.
"""  # noqa: E501


# ── the Case ────────────────────────────────────────────────────────────────────────────────


def record_to_sample(row: dict[str, Any]) -> Sample:
    """One dataset row → the Case: the filled prompt, the outcome, and reference metadata.

    WHY ``present_date[:10]``: the study filled ``Today is`` with the date part of the
    dataset's ISO ``present_date`` (``%Y-%m-%d``, A.1's format); its 100 prompts show it.
    """

    if row["resolution"] not in (0.0, 1.0):
        # INVARIANT: a binary question resolves 0 or 1; int() would silently floor 0.5 to No.
        raise ValueError(f"{row['question_id']}: resolution {row['resolution']!r} is not 0 or 1")
    return Sample(
        id=str(row["question_id"]),
        input=PROMPT_TEMPLATE.format(
            question=row["question"],
            background=row["background"],
            resolution_criteria=row["resolution_criteria"],
            today=str(row["present_date"])[:10],
        ),
        target=str(int(row["resolution"])),
        metadata={
            # WHY the outcome here as well as in the target: the scorer reads it from metadata
            # and fails loudly without it, never parsing a stand-in's placeholder target.
            "outcome": int(row["resolution"]),
            "present_date": str(row["present_date"]),
            "expected_resolution_date": str(row["expected_resolution_date"]),
            # FutureSearch's own forecast (0-100, nullable): reference only, never scored.
            "sota_forecast_probability": row["sota_forecast_probability"],
        },
    )


def load_btf3(*, revision: str = DATASET_REVISION, sha256: str = DATASET_SHA256) -> MemoryDataset:
    """Download the pinned parquet, refuse a wrong sha256, turn each row into a Sample."""

    import pyarrow.parquet as parquet  # the `datasets` dependency the inspect extra installs
    from huggingface_hub import hf_hub_download  # recorded by the importer's Case Source recorder

    path: str = hf_hub_download(
        repo_id=DATASET, filename=DATASET_FILE, revision=revision, repo_type="dataset"
    )
    actual: str = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if actual != sha256:
        raise ValueError(f"{DATASET_FILE} has sha256 {actual}, expected {sha256}")
    samples: list[Sample] = [record_to_sample(row) for row in parquet.read_table(path).to_pylist()]
    seen: set[str] = set()
    for sample in samples:
        # INVARIANT: one Case per id; a duplicate would grade one reply twice.
        if str(sample.id) in seen:
            raise ValueError(f"two rows share the Case id {sample.id}")
        seen.add(str(sample.id))
    return MemoryDataset(samples=samples, name="btf3")


# ── the reply ───────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Reading:
    """One reply as the study read it.

    Attributes:
        forecast: the probability of Yes, in [0, 1], or None when the reply gives none.
        compliant: True when the reply ENDS with the probability, as the prompt asks.
        source: ``final_line``, ``number_not_final`` or None: which of the reader's rules matched.
    """

    forecast: float | None
    compliant: bool
    source: str | None


def read_forecast(reply: str) -> Reading:
    """The study's ``btf_parse``: the probability ending the last line; else the last number in
    [0, 1] anywhere; else none. A percentage's own digits (``65%``) are never read, but a
    stray ``0`` or ``1`` elsewhere in the reply then is (spec §3)."""

    parsed: dict[str, Any] = btf_parse(reply)
    return Reading(
        forecast=parsed["prob"], compliant=bool(parsed["compliant"]), source=parsed["source"]
    )


# ── the mark ────────────────────────────────────────────────────────────────────────────────


def case_outcome(state: TaskState) -> int:
    """The Case's resolution, 1 for Yes and 0 for No, from its metadata.

    Raises:
        KeyError: a Case without it is broken, never "resolved No" (the scorer adapter records
            a ``scorer_error``, as inspect_evals' bbeh scorer does).
        ValueError: an outcome other than 0 or 1.
    """

    metadata: dict[str, Any] = state.metadata or {}
    if "outcome" not in metadata:
        raise KeyError("Sample is missing 'outcome' in its metadata")
    raw: Any = metadata["outcome"]
    if raw not in (0, 1):
        # INVARIANT: checked BEFORE int(), which would silently floor 0.5 to "resolved No".
        raise ValueError(f"outcome must be 0 or 1, got {raw!r}")
    return int(raw)


#: The study's rules (``committee_kit/metrics.py``): a probability of exactly 0.5 counts as Yes,
#: and a crowd with no decision reads as 0.5 for Brier, ``(0.5 - y)^2 = 0.25`` either way. This
#: Benchmark applies that to every reply with no forecast (a named deviation for one model).
THRESHOLD: Final[float] = 0.5
ABSTAIN_BRIER: Final[float] = 0.25


@scorer(metrics=[mean(), stderr()])
def btf3_accuracy() -> Scorer:
    """One Case: 1.0 when ``f >= 0.5`` matches the outcome, else 0.0; the Brier ``(f - y)^2`` on
    the metadata. A reply with no forecast is a miss (``forecast: None``, Brier 0.25): issue
    #1868's "Case scores 0", the study's rule for a crowd with no decision. The paper drops one
    model's unreadable reply instead: a named deviation (spec §12)."""

    async def score(state: TaskState, target: Target) -> Score:
        outcome: int = case_outcome(state)
        reading: Reading = read_forecast(state.output.completion)
        if reading.forecast is None:
            correct: bool = False
            brier: float = ABSTAIN_BRIER
        else:
            correct = (reading.forecast >= THRESHOLD) == bool(outcome)
            brier = (reading.forecast - outcome) ** 2
        return Score(
            value=1.0 if correct else 0.0,
            answer="" if reading.forecast is None else f"{reading.forecast:g}",
            metadata={
                "forecast": reading.forecast,
                "outcome": outcome,
                "brier": brier,
                "compliant": reading.compliant,
                "source": reading.source,
            },
        )

    return score


def _has_forecast(sample: SampleScore) -> bool:
    """False for a reply with no forecast, and for a Candidate that abstained (the Engine's bare
    ``candidate_abstained`` mark, which carries none of this scorer's metadata)."""

    metadata: dict[str, Any] = sample.score.metadata or {}
    if metadata.get("candidate_abstained"):
        return False
    return metadata.get("forecast") is not None


def _brier(sample: SampleScore) -> float:
    """The Case's Brier; a Case without one (the Engine's bare abstain mark) gave no forecast,
    so it costs the study's 0.25."""

    metadata: dict[str, Any] = sample.score.metadata or {}
    value: Any = metadata.get("brier")
    return ABSTAIN_BRIER if value is None else float(value)


@metric
def btf3_headline() -> Metric:
    """Accuracy over every Case (the headline), the mean Brier, and the counts it rests on.

    Returns ``{"accuracy", "brier", "forecasts", "no_forecast", "compliant"}``; the row names
    ``accuracy`` its ``whole_run_headline`` and the Engine publishes the rest beside it as run
    metrics. Every Case is in both means: one with no forecast is a miss and costs Brier 0.25,
    issue #1868's rule (F1: "count shown in the report"; the study's rule for a crowd, a named
    deviation for one model's unreadable reply, which the paper drops). WHY Brier beside accuracy:
    always answering No already scores about two thirds on accuracy (issue #1868), and Brier is
    the benchmark's own measure. Lower Brier is better.
    """

    def compute(scores: list[SampleScore]) -> dict[str, float | int]:
        kept: list[SampleScore] = [s for s in scores if _has_forecast(s)]
        n: int = len(scores)
        return {
            "accuracy": sum(s.score.as_float() for s in scores) / n if n else 0.0,
            "brier": sum(_brier(s) for s in scores) / n if n else ABSTAIN_BRIER,
            "forecasts": len(kept),
            "no_forecast": n - len(kept),
            "compliant": sum(1 for s in kept if (s.score.metadata or {}).get("compliant")),
        }

    return compute


# ── the Task ────────────────────────────────────────────────────────────────────────────────


@task
def btf3() -> Task:
    """BTF-3 at ad5a2165: 1,515 resolved yes/no forecasting questions, closed-book, as the
    contributor's study ran them (one call per Case).

    WHY no ``GenerateConfig(temperature=0.0)`` although the study ran at temperature 0: the
    Engine never applies a Task's config (the Candidate answers with its own settings; see
    worldsense's Fidelity Record), so the row names it as a deviation instead.
    """

    return Task(
        dataset=load_btf3(),
        solver=generate(),
        scorer=btf3_accuracy(),
        metrics=[btf3_headline()],
    )
