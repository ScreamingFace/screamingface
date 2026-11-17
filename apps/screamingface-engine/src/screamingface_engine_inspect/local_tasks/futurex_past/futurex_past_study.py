# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the default
# (extra-less) install the typecheck gate runs against; it is loaded only behind
# `inspect_available()`, like every other module in this package.
"""FutureX-Past scored the crowd-wisdom study's way, so the study's numbers can be replicated.

FEATURE: replication of the study "behavior-aware LLM crowds for future prediction" (spec
docs/spec/2026-11-16-futurex-past-local-task.md §10). STORY: as a reader of that study, I rerun
its committees on ScreamingFace and get its numbers, 0.302 for the fused-medoids committee.

Think of it as the same archive of questions marked by a second, stricter marker: no judge, and
an answer counts only when its text equals the key after case-folding. That is how the study
marked FutureX-Past, so its numbers sit below ``futurex_past``'s on levels 3-4 by design.

Execution order:

    1. ``futurex_past_study()`` → the shared ``load_futurex_past`` at commit 3c2e3969 (2026-08-02),
       the latest commit that holds all 100 of the study's questions with the study's exact keys.
    2. ``futurex_study_score`` reads the last box, splits it on commas, case-folds both sides
       (the study's ``corpus.normalise``) and calls the study's own ``item_score`` (vendored).
    3. ``study_tier_weighted`` rolls up with the study's own ``tier_weighted``.

INVARIANT: ``vendor/study_metrics.py`` is the study's code byte for byte; a test pins its sha256.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
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
    load_futurex_past,
)
from screamingface_engine_inspect.local_tasks.futurex_past.grading import answer_tokens, last_boxed
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

    WHY a rewrite, not a copy: this one line is the study's ``committee_kit/corpus.py:28``
    ``normalise``; the rest of that file loads CSVs this Benchmark never reads.
    """

    return " ".join(str(token).strip().lower().split())


def study_item_score(level: int, gold: Sequence[Any], tokens: Sequence[str]) -> float:
    """One Case, the study's way: its ``item_score`` over normalised key and answer."""

    return float(item_score(level, [normalise(t) for t in gold], [normalise(t) for t in tokens]))


@scorer(metrics=[mean(), stderr()])
def futurex_study_score() -> Scorer:
    """Level 1 exact list, level 2 set F1, levels 3-4 ordered overlap; no judge, no σ."""

    async def score(state: TaskState, target: Target) -> Score:
        level, gold = case_key(state)
        box: str | None = last_boxed(state.output.completion)
        # WHY the raw box: the study split its stored box text on commas without unwrapping.
        value: float = study_item_score(level, gold, answer_tokens(box))
        return Score(value=value, answer=box or "", metadata={"level": level})

    return score


@metric
def study_tier_weighted() -> Metric:
    """The study's ``tier_weighted``: level means weighted 10/20/30/40 over the levels present.
    Cases without a level (the no-network lane's stand-ins) give the plain mean."""

    def compute(scores: list[SampleScore]) -> float:
        by_level: dict[int, list[float]] = defaultdict(list)
        for sample in scores:
            level: object = (sample.sample_metadata or {}).get("level")
            if level is None:
                return sum(s.score.as_float() for s in scores) / len(scores)
            by_level[int(str(level))].append(sample.score.as_float())
        weighted: float | None = tier_weighted(by_level)
        # None only for an empty run: no level holds a Case.
        return 0.0 if weighted is None else float(weighted)

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
