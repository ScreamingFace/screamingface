# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai,
# huggingface_hub, pyarrow), absent in the default (extra-less) install the typecheck gate runs
# against; it is loaded only behind `inspect_available()`, like every other module in this package.
"""FutureX-Past as a LOCAL inspect Task, scored the way the FutureX authors score it today.

FEATURE: forecasting Benchmarks for fused LLM committees (spec
docs/spec/2026-11-16-futurex-past-local-task.md). STORY: as a researcher whose committees were
scored on FutureX-Past, I run the same exam on ScreamingFace and get a number on the FutureX
authors' own scale.

Think of it as an archive of resolved forecasting questions handed out unchanged: each question
is the dataset's own prompt, which already tells the model to end with ``\\boxed{...}``. The
marking (``grading.py``) follows the authors' current scorer, Futurex-Eval@2626f7a2.

Execution order, as the importer and the Engine see it:

    1. ``futurex_past()`` → ``load_futurex_past()``: fetch the pinned parquet from the Hub (commit
       pin + sha256, refused on mismatch); each row becomes a Sample whose ``input`` is the row's
       ``prompt`` byte for byte, whose id is ``<id>|<end_time>`` (the dataset reuses ids for
       recurring questions), and whose metadata carries the level and the typed answer key.
    2. the importer replays that twice in a clean child and seals the 2,036 Cases by digest.
    3. at grading, ``futurex_score`` reads the last box: levels 1-2 by rule, levels 3-4 through
       the judge. ``futurex_tier_weighted`` rolls the Cases up with the paper's 10/20/30/40
       weights, honoured as the whole-run headline.

INVARIANT: the pins and the row-to-Sample mapping are Benchmark identity (they sit inside the
Case Digest); ``tests/unit/inspect/test_local_task_futurex_past.py`` pins them.

References:
    - Paper: https://arxiv.org/abs/2508.11987 (Zeng et al., 2025), §3.4.3 for the metrics
    - Reference scorer: https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5
    - Case Source: https://huggingface.co/datasets/futurex-ai/Futurex-Past (Apache-2.0)
"""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import Model, get_model
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

from screamingface_engine_inspect.judge_redraw import (
    JudgedItem,
    JudgeReplyUnparseable,
    judge_until_parsed,
)
from screamingface_engine_inspect.local_tasks.futurex_past.grading import (
    Ask,
    Graded,
    grade_level_34,
    label_score,
    last_boxed,
    reply_tokens,
)

# ── pins ────────────────────────────────────────────────────────────────────────────────────
DATASET: Final[str] = "futurex-ai/Futurex-Past"
DATASET_REVISION: Final[str] = "8299bfa1609dec30f267891a74d76e62902c9d71"
DATASET_FILE: Final[str] = "data/train-00000-of-00001.parquet"
DATASET_SHA256: Final[str] = "a385ef5e6d9f120afcf495450db702ef1e7575e2c21c77b293fc7cba933336bb"

#: The judge, as the scorer calls it through the gateway provider: the house judge every judged
#: Benchmark here pins (frames, healthbench). Futurex-Eval uses DeepSeek V4 Flash or GPT-4.1;
#: the row's JudgeSpec pins the same model as this default (benchmark identity).
JUDGE_MODEL: Final[str] = "screamingface/openrouter/openai/gpt-5.4"

#: The paper's tier weights (§4.1; Futurex-Eval ``run_weekly_leaderboard.LEVEL_WEIGHTS``).
LEVEL_WEIGHTS: Final[dict[int, float]] = {1: 0.1, 2: 0.2, 3: 0.3, 4: 0.4}


# ── the answer key ──────────────────────────────────────────────────────────────────────────


def parse_ground_truth(raw: object) -> list[Any]:
    """A ``ground_truth`` cell as a list: a Python literal read safely, never evaluated.

    NAMED DEVIATION (spec §2): one key at 8299bfa1 is the bare ``[Yes]``, which is not a
    literal. Futurex-Eval keeps it as the label ``[Yes]``, which nothing can match; it is read
    here as ``["Yes"]``.
    """

    if not isinstance(raw, str):
        return list(raw) if isinstance(raw, list | tuple) else [raw]
    try:
        value: object = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        inner: str = raw.strip()
        bracketed: bool = inner.startswith("[") and inner.endswith("]")
        parts: list[str] = [part.strip() for part in inner[1:-1].split(",") if part.strip()]
        value = parts if bracketed else raw
    return list(value) if isinstance(value, list | tuple) else [value]


# ── the dataset loader ──────────────────────────────────────────────────────────────────────


def record_to_sample(row: dict[str, Any]) -> Sample:
    """One dataset row → the Case: the prompt verbatim, the key, and what the scorer reads.

    WHY the key twice: inspect's Target holds text, while the level-3/4 rules need a number key
    as a float (``normalize_gold``), so the typed list rides the metadata.
    """

    gold: list[Any] = parse_ground_truth(row["ground_truth"])
    return Sample(
        # WHY <id>|<end_time>: 21 ids recur on other dates (119 rows at 8299bfa1); this pair is
        # unique and is the crowd-wisdom study's own item_id, so its results line up unmapped.
        id=f"{row['id']}|{row['end_time']}",
        input=row["prompt"],
        target=[str(item) for item in gold],
        metadata={
            "level": int(row["level"]),
            "title": row["title"],
            "end_time": str(row["end_time"]),
            "ground_truth": gold,
            # The paper's σ column; kept for the record, unused (spec §4.3). Absent at 3c2e3969.
            "std": row.get("std"),
        },
    )


def load_futurex_past(
    *,
    revision: str = DATASET_REVISION,
    sha256: str = DATASET_SHA256,
    name: str = "futurex_past",
) -> MemoryDataset:
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
    return MemoryDataset(samples=samples, name=name)


# ── the scorer ──────────────────────────────────────────────────────────────────────────────


def case_key(state: TaskState) -> tuple[int, list[Any]]:
    """The Case's level and typed answer key from its metadata.

    Raises:
        KeyError: a Case without them is broken, never "level 0" (the scorer adapter records a
            ``scorer_error``, as inspect_evals' bbeh scorer does).
    """

    metadata: dict[str, Any] = state.metadata or {}
    if "level" not in metadata or "ground_truth" not in metadata:
        raise KeyError("Sample is missing 'level' or 'ground_truth' in its metadata")
    return int(metadata["level"]), list(metadata["ground_truth"])


def _asker(judge: Model, case: object, redraws: list[int]) -> Ask:
    """The ``Ask`` the level-3/4 rules call: one judge question through the shared redraw loop,
    its redraw count kept for the Score's evidence."""

    def ask[V](prompt: str, parse: Callable[[str], V | None], purpose: str) -> Awaitable[V]:
        async def asked() -> V:
            try:
                judged: JudgedItem[V] = await judge_until_parsed(
                    judge, prompt, parse, item=f"case {case} {purpose}"
                )
            except JudgeReplyUnparseable as exc:
                # WHY: the router falls back on this error; its spent redraws stay in evidence.
                redraws.append(exc.redraws)
                raise
            redraws.append(judged.redraws)
            return judged.verdict

        return asked()

    return ask


@scorer(metrics=[mean(), stderr()])
def futurex_score(judge_model: str = JUDGE_MODEL) -> Scorer:
    """One Case in [0, 1]: levels 1-2 by the label rule, levels 3-4 through the judge.

    The Score's metadata carries the level and the route, so a run can be cut per level
    (Futurex-Eval reports ``level1Score`` … ``level4Score``).

    Args:
        judge_model: the gateway judge, ``screamingface/<model>``; the row pins the same one.
    """

    async def score(state: TaskState, target: Target) -> Score:
        level, gold = case_key(state)
        box: str | None = last_boxed(state.output.completion)
        if level <= 2:
            # WHY reply_tokens: ``\boxed{\text{B, C}}`` and ``\boxed{\text{B}, \text{C}}`` are
            # both the options B and C (spec §3; fidelity audit U1, U7).
            value: float = label_score(gold, reply_tokens(box))
            return Score(value=value, answer=box or "", metadata={"level": level})
        redraws: list[int] = []
        ask: Ask = _asker(get_model(judge_model), state.sample_id, redraws)
        graded: Graded = await grade_level_34(ask, state.input_text, gold, box)
        metadata: dict[str, Any] = {
            "level": level,
            "route": graded.route,
            "route_fallback": graded.route_fallback,
            "judge_redraws": sum(redraws),
        }
        return Score(value=graded.score, answer=box or "", metadata=metadata)

    return score


# ── the headline ────────────────────────────────────────────────────────────────────────────


def leveled(scores: list[SampleScore]) -> dict[int, list[float]] | None:
    """The marks by level, or None when no Case carries a level (the stand-in lane).

    AIDEV-NOTE: a Case without a level beside leveled ones is left out. It is an abstained Case
    whose grading failed, filed as a bare 0.0 with no metadata (``single_shot._metric_sample``);
    it cannot be placed in a level, and the run must not stop after every call is paid.
    """

    by_level: dict[int, list[float]] = defaultdict(list)
    for sample in scores:
        level: object = (sample.sample_metadata or {}).get("level")
        if level is not None:
            by_level[int(str(level))].append(sample.score.as_float())
    return dict(by_level) if by_level else None


def tier_weighted_mean(scores: list[SampleScore], weights: dict[int, float]) -> float:
    """Σ w_L · mean(level L) / Σ w_L over the levels present.

    NAMED DEVIATION (spec §4.4): Futurex-Eval counts an absent level as 0; the weights
    renormalise here, which equals upstream whenever all four levels are present (every full
    run). A run where no Case carries a level (the no-network lane's stand-ins) gives the plain
    mean.
    """

    by_level: dict[int, list[float]] | None = leveled(scores)
    if by_level is None:
        return sum(s.score.as_float() for s in scores) / len(scores)
    total: float = sum(weights[level] for level in by_level)
    weighted: float = sum(
        weights[level] * sum(values) / len(values) for level, values in by_level.items()
    )
    return weighted / total


@metric
def futurex_tier_weighted() -> Metric:
    """The paper's overall score: the four level means weighted 10/20/30/40."""

    def compute(scores: list[SampleScore]) -> float:
        return tier_weighted_mean(scores, LEVEL_WEIGHTS)

    return compute


# ── the Task ────────────────────────────────────────────────────────────────────────────────


@task
def futurex_past() -> Task:
    """FutureX-Past at 8299bfa1: 2,036 resolved forecasting questions, levels 1 to 4."""

    return Task(
        dataset=load_futurex_past(),
        solver=generate(),
        scorer=futurex_score(),
        metrics=[futurex_tier_weighted()],
    )
