# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the default
# (extra-less) install the typecheck gate runs against; it is loaded only behind
# `inspect_available()`, like every other module in this package.
"""FutureX-Past scored the crowd-wisdom study's way, so the study's numbers can be replicated.

FEATURE: replication of the study "behavior-aware LLM crowds for future prediction" (spec
docs/spec/2026-11-16-futurex-past-local-task.md §10). STORY: as a reader of that study, I rerun
its models on ScreamingFace and get its numbers (all 27 stored models reproduce exactly).

NAMED DEVIATION: an empty answer leaves the score whoever wrote it. The study scored a COMMITTEE
with no majority 0 and kept it; this scorer sees one reply per Case and cannot tell a committee
from a model. So the study's stored fused-medoids answers, empty on 2 of the 100 questions,
score 0.306 here with ``excluded`` 2, where the study reports 0.302.

Think of it as the same archive of questions marked by a second, stricter marker: no judge, and
an answer counts only when its text equals the key after case-folding. That is how the study
marked FutureX-Past, so its numbers sit below ``futurex_past``'s on levels 3-4 by design.

Execution order:

    1. ``futurex_past_study()`` → the shared ``load_futurex_past`` at commit 3c2e3969 (2026-08-02),
       the latest commit that holds all 100 of the study's questions with the study's exact keys.
    2. ``futurex_study_score`` reads the reply with the study's own ``futurex_parse`` and its
       comma split, checks it with the study's ``interpret_answer`` (vendored), case-folds both
       sides (the study's ``corpus.normalise``) and calls the study's ``item_score`` (vendored).
    3. ``study_tier_weighted`` leaves out every Case with no usable answer, as the study's
       ``rank.score_entry`` drops such a cell from both sides of the fraction, then rolls up with
       the study's own ``tier_weighted``.

INVARIANT: ``vendor/study_metrics.py`` and ``vendor/study_formats.py`` are the study's code byte
for byte; a test pins each sha256.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from inspect_ai import Task, task
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

from screamingface_engine_inspect.local_tasks.futurex_past.futurex_past import (
    case_key,
    leveled,
    load_futurex_past,
)
from screamingface_engine_inspect.local_tasks.futurex_past.grading import answer_tokens
from screamingface_engine_inspect.local_tasks.futurex_past.vendor.study_formats import (
    futurex_parse,
    interpret_answer,
)
from screamingface_engine_inspect.local_tasks.futurex_past.vendor.study_metrics import (
    item_score,
    tier_weighted,
)

# ── pins ────────────────────────────────────────────────────────────────────────────────────
STUDY_REVISION: Final[str] = "3c2e39690de35eb1fcc621251f56343c72bae8c4"
STUDY_SHA256: Final[str] = "55ecf4f11909d412d515eeeab5b5891012adde4ff4353d35204179728704ad50"

#: The study's 100 questions as Case positions (1-based, file order at 3c2e3969), to pass as
#: ``cases=[...]``. ``test_local_task_futurex_past_study.py`` proves each is the study's item.
STUDY_CASES: Final[tuple[int, ...]] = (
    172, 182, 188, 189, 202, 212, 234, 242, 261, 266, 273, 276, 284, 289, 291, 293, 297, 311,
    338, 341, 365, 378, 386, 397, 401, 403, 427, 431, 438, 439, 454, 468, 494, 501, 507, 515,
    518, 527, 543, 560, 578, 600, 603, 609, 615, 622, 630, 663, 664, 707, 713, 731, 738, 749,
    759, 762, 763, 764, 783, 785, 789, 794, 799, 810, 812, 814, 826, 834, 836, 839, 847, 852,
    878, 887, 896, 906, 909, 923, 957, 959, 971, 976, 979, 989, 991, 993, 1006, 1013, 1021,
    1035, 1040, 1045, 1056, 1058, 1065, 1068, 1070, 1075, 1107, 1114,
)  # fmt: skip


def normalise(token: object) -> str:
    """Case-fold and collapse whitespace, on BOTH sides of every comparison.

    WHY a rewrite, not a copy: this one line is the study's ``committee_kit/corpus.py:27``
    ``normalise``; the rest of that file loads CSVs this Benchmark never reads.
    """

    return " ".join(str(token).strip().lower().split())


def study_item_score(level: int, gold: Sequence[Any], tokens: Sequence[str]) -> float:
    """One Case, the study's way: its ``item_score`` over normalised key and answer."""

    return float(item_score(level, [normalise(t) for t in gold], [normalise(t) for t in tokens]))


@dataclass(frozen=True, slots=True)
class StudyReading:
    """One reply as the study read it: its tokens, and whether the study would have scored it."""

    tokens: list[str]
    usable: bool
    why: str | None


def study_reading(reply: str, prompt: str) -> StudyReading:
    """The study's own reading: ``futurex_parse`` (the last box), ``build_data``'s comma split,
    and ``interpret_answer`` on the raw box against the question's own prompt.

    WHY the gate (fidelity audit D1/D2): the study excluded a cell with no answer or with an
    uninterpretable box (a hedge, every option, an option not offered) and dropped it from both
    sides of its score; it never scored such a reply.
    """

    raw: str | None = futurex_parse(reply)["raw_box"]
    tokens: list[str] = answer_tokens(raw)
    if not tokens:
        return StudyReading(tokens=tokens, usable=False, why="no answer in the box")
    verdict: dict[str, Any] = interpret_answer(raw, prompt)
    return StudyReading(tokens=tokens, usable=bool(verdict["interpretable"]), why=verdict["why"])


@scorer(metrics=[mean(), stderr()])
def futurex_study_score() -> Scorer:
    """Level 1 exact list, level 2 set F1, levels 3-4 ordered overlap; no judge, no σ.

    A reply with no usable answer is marked ``study_usable: False`` with the study's reason;
    its value is the study's mark of its tokens (0 when there are none), and the headline
    leaves it out.
    """

    async def score(state: TaskState, target: Target) -> Score:
        level, gold = case_key(state)
        reading: StudyReading = study_reading(state.output.completion, state.input_text)
        value: float = study_item_score(level, gold, reading.tokens)
        metadata: dict[str, Any] = {"level": level, "study_usable": reading.usable}
        if reading.why is not None:
            metadata["unusable_why"] = reading.why
        return Score(value=value, answer=", ".join(reading.tokens), metadata=metadata)

    return score


def _usable(sample: SampleScore) -> bool:
    """False for a Case the study would have dropped: an unusable reply, or a Candidate that
    abstained (the Engine's mark for an empty reply, ``candidate_abstained``)."""

    metadata: dict[str, Any] = sample.score.metadata or {}
    return metadata.get("study_usable") is not False and not metadata.get("candidate_abstained")


@metric
def study_tier_weighted() -> Metric:
    """The study's ``rank.score_entry``: its ``tier_weighted`` over the Cases with a usable
    answer, level means weighted 10/20/30/40 over the levels present. A run where no Case
    carries a level (the no-network lane's stand-ins) gives the plain mean."""

    def compute(scores: list[SampleScore]) -> float:
        return _study_score([sample for sample in scores if _usable(sample)])

    return compute


def _study_score(kept: list[SampleScore]) -> float:
    """``tier_weighted`` over the usable Cases; the plain mean when none carries a level."""

    by_level: dict[int, list[float]] | None = leveled(kept)
    if by_level is None:
        return sum(s.score.as_float() for s in kept) / len(kept) if kept else 0.0
    weighted: float | None = tier_weighted(by_level)
    # None only when no level holds a Case.
    return 0.0 if weighted is None else float(weighted)


@metric
def study_headline() -> Metric:
    """The row's whole-run metric: the study's score beside the counts it rests on.

    ``study_score`` is ``study_tier_weighted`` (the row's ``whole_run_headline``); ``answered``
    and ``excluded`` are published beside it as run metrics, so a Report shows how many
    Cases left the headline (an unusable reply or an abstain). WHY (maintainer review on
    ScreamingFace/screamingface#1897): the study drops those Cases, so 1 right answer and 99
    hedges score 1.0; the count makes that visible without changing the study's number.
    """

    def compute(scores: list[SampleScore]) -> dict[str, float | int]:
        kept: list[SampleScore] = [sample for sample in scores if _usable(sample)]
        return {
            "study_score": _study_score(kept),
            "answered": len(kept),
            "excluded": len(scores) - len(kept),
        }

    return compute


@task
def futurex_past_study() -> Task:
    """FutureX-Past at 3c2e3969 (1,118 questions), marked by the crowd-wisdom study's rules."""

    return Task(
        dataset=load_futurex_past(
            revision=STUDY_REVISION, sha256=STUDY_SHA256, name="futurex_past_study"
        ),
        solver=generate(),
        scorer=futurex_study_score(),
        metrics=[study_tier_weighted()],
    )
