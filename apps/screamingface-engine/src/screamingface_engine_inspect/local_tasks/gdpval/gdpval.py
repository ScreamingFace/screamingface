# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai, datasets),
# absent in the default (extra-less) install the typecheck gate runs against; it is loaded only
# behind `inspect_available()`, like every other module in this package.
"""GDPval-text as a LOCAL inspect Task — the hand-built folder in inspect's shape (OME-1527).

Think of it as the same exam, now printed by the shared press: a dataset loader that prints the
question booklet (each work request with its reference files already typed out), a scorer that
hands every rubric line to the judge one at a time and adds up the points, and one `@task` that
binds them. The importer seals the Cases by digest and the plugin's shared serving path does
the rest.

Execution order, as the importer and the Engine see it:

    1. `gdpval_text()` → `load_text_subset()`: load `openai/gdpval` at the pinned revision (the
       importer forces it at every build), keep the frozen 102 tasks in frozen order
       (`subset.py`), and render each into a Sample: `input` is the request followed by every
       reference file flattened to text (downloaded once, build time only, `references.py`);
       `metadata` carries the rubric after the container filter (`rubric_filter.py`).
    2. the importer replays that twice in a clean child and seals the Cases by digest; at
       build, prepare replays it once more and serves nothing unless the digest matches.
    3. at grading, `gdpval_rubric` asks the judge about each rubric line in turn, with the
       hand-built grader prompt; a reply with no strict JSON boolean is redrawn (twice at
       most) and then fails the Case as `judge_reply_invalid`, never as "not met".
    4. the Case score is points earned over points winnable; the run's headline is the plain
       mean over graded Cases (the row keeps the tally's mean, as the hand-built one did).

INVARIANT — the prompt bytes are Benchmark identity (they sit inside the Case Digest) and equal
the hand-built Benchmark's, Candidate prompt and grader prompt alike;
`test_local_task_gdpval.py` pins both.

INVARIANT — this score is NOT GDPval's published metric (an expert pairwise win rate against a
human deliverable); it is a rubric mean, and the row's description says so.

References:
    - Paper: https://arxiv.org/abs/2510.04374 (GDPval, Patwardhan et al., OpenAI, 2025)
    - Dataset: https://huggingface.co/datasets/openai/gdpval
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import get_model
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState, generate

from screamingface_engine.benchmarks.shared_grading.judge_evidence import extract_json_object
from screamingface_engine_inspect.judge_redraw import JudgedItem, judge_until_parsed
from screamingface_engine_inspect.local_tasks.gdpval.prompts import (
    build_grader_prompt,
    render_rubric_item,
)
from screamingface_engine_inspect.local_tasks.gdpval.references import (
    ReferenceReader,
    build_reader,
    default_reference_cache,
    reference_urls,
)
from screamingface_engine_inspect.local_tasks.gdpval.rubric_filter import strip_format_criteria
from screamingface_engine_inspect.local_tasks.gdpval.subset import TEXT_SUBSET_TASK_IDS

# ── pins (the hand-built revision_inputs.py) ─────────────────────────────────────────────
DATASET = "openai/gdpval"
# WHY THIS revision: "Release GDPval v2 (rubrics + deliverables)" (2026-02-10), the commit that
# ADDED `rubric_json`. Do NOT copy inspect_evals' pin (`a3848a2a…`, 2025-09-25): it predates the
# rubrics and carries `rubric_json: null` on all 220 rows.
DATASET_REVISION = "11e7900cdcac61bc4daf59e65feb238acda98fbf"

#: The judge, as the scorer calls it through the gateway provider. The row's JudgeSpec pins the
#: same model and its params (benchmark identity); see its WHY notes in `benchmarks.py`.
JUDGE_MODEL = "screamingface/openrouter/google/gemini-3.1-pro-preview"

# WHY a stable delimiter: the reference block is part of the Case input, so its exact bytes
# must not drift between builds (byte-identical to the hand-built prepare's).
REFERENCE_HEADER = "--- Reference file: {name} ---"


# ── dataset loader (the hand-built prepare.py, minus the bundle writing) ──────────────────
def load_text_subset() -> MemoryDataset:
    """Load the pinned dataset, keep the frozen 102 tasks in order, render each into a Sample."""

    import datasets  # recorded (and its revision forced) by the importer's Case Source recorder

    loaded: Any = datasets.load_dataset(DATASET, revision=DATASET_REVISION)
    rows: list[dict[str, Any]] = [dict(row) for split in loaded for row in loaded[split]]
    reader: ReferenceReader = build_reader(
        default_reference_cache(DATASET_REVISION), reference_urls(rows)
    )
    samples: list[Sample] = [record_to_sample(row, reader) for row in select_rows(rows)]
    return MemoryDataset(samples=samples, name="gdpval_text")


def select_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The frozen selection in frozen order — Case ids are positions in it, never upstream order.

    A dataset that dropped or renamed a frozen id fails the build rather than silently serving a
    smaller benchmark under the same identity.
    """

    by_id: dict[str, dict[str, Any]] = {str(row["task_id"]): row for row in rows}
    missing: list[str] = [task_id for task_id in TEXT_SUBSET_TASK_IDS if task_id not in by_id]
    if missing:
        raise ValueError(
            f"{len(missing)} frozen task id(s) are absent from {DATASET}@{DATASET_REVISION}, "
            f"first {missing[0]!r} — refusing to prepare a different benchmark under this identity"
        )
    return [by_id[task_id] for task_id in TEXT_SUBSET_TASK_IDS]


def record_to_sample(row: Mapping[str, Any], reader: ReferenceReader) -> Sample:
    """One GDPval row → the Candidate-facing text and the private rubric.

    The input is the request, then for each reference file a header line and its flattened text,
    joined by blank lines — the hand-built `case_input` byte for byte.
    """

    task_id: str = str(row["task_id"])
    parts: list[str] = [str(row["prompt"]).strip()]
    for file_name in row.get("reference_files") or []:
        parts.append(REFERENCE_HEADER.format(name=str(file_name)))
        parts.append(reader(task_id, str(file_name)))
    return Sample(
        id=task_id,
        input="\n\n".join(parts),
        # No answer key: the judge grades against the rubric, which rides the metadata
        # (private Grading Material, never published).
        target="",
        metadata={"task_id": task_id, "rubric": rubric_items(row)},
    )


def rubric_items(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The scored criteria for one task: container checks removed, shapes validated.

    INVARIANT: `rubric_id` is the 1-based position after the filter, and points are integers
    (the judge must see "[7]", never "[7.0]"). A rubric left with no positive points fails the
    build: its score would divide by zero.
    """

    task_id: str = str(row["task_id"])
    raw: object = row.get("rubric_json")
    parsed: object = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, list) or not parsed:
        raise ValueError(f"task {task_id}: rubric_json must be a non-empty array")
    items: list[dict[str, Any]] = []
    for index, item in enumerate(strip_format_criteria(parsed), start=1):
        criterion: object = item.get("criterion")
        points: object = item.get("score")
        if not isinstance(criterion, str) or not criterion.strip():
            raise ValueError(f"task {task_id}: rubric item {index} lacks a criterion")
        if isinstance(points, bool) or not isinstance(points, int):
            raise ValueError(f"task {task_id}: rubric item {index} score must be an integer")
        items.append({"rubric_id": index, "criterion": criterion, "points": points})
    if not any(item["points"] > 0 for item in items):
        raise ValueError(f"task {task_id}: no positive-points criterion survives the filter")
    return items


# ── the judge's reply ─────────────────────────────────────────────────────────────────────
def parse_verdict(reply: str) -> tuple[bool, str] | None:
    """The judge's verdict and its words, or None when the reply carries no verdict.

    The hand-built rule, unchanged: the JSON is recovered however the judge presented it
    (fenced, prose-prefixed, bare), and only a REAL JSON boolean `criteria_met` counts —
    `"true"` or `1` is no verdict, so it is redrawn rather than read leniently.
    """

    decoded: object = extract_json_object(reply)
    if not isinstance(decoded, Mapping):
        return None
    met: object = decoded.get("criteria_met")
    if met is not True and met is not False:
        return None
    explanation: object = decoded.get("explanation")
    return met, explanation if isinstance(explanation, str) else ""


# ── the scorer ────────────────────────────────────────────────────────────────────────────
@scorer(metrics=[mean(), stderr()])
def gdpval_rubric(judge_model: str = JUDGE_MODEL) -> Scorer:
    """Grade one deliverable against its rubric: one judge call per line, then the points.

    Think of it as an examiner with a checklist who may only look at one line at a time: each
    line goes to the judge alone, with the request, the submission and that line, and the
    judge says met or not. The points come from the private rubric, never from the judge.

    Stages, in execution order:

    1. For each rubric line, in rubric order: render ``[points] criterion`` into the hand-built
       grader prompt and ask the judge through :func:`judge_until_parsed`. One line at a time,
       on purpose: the aggregate already grades 4 Cases at once, which is what the gateway
       admits per provider, so a parallel fan-out here would only queue.
    2. A reply that won't parse is redrawn, at most twice, each a fresh sample outside the
       gateway cache; after that the line raises and the whole Case fails by name
       (``judge_reply_invalid``). A partly judged Case is never scored: a lost penalty line
       would silently raise its score.
    3. Score: earned = the points of every met line (penalties subtract), winnable = the sum
       of the positive points. No clamp: a harmful answer can rank below one that said nothing.

    Worked example, points ``[+5, +3, -3]``, the judge says met, not met, met:

        winnable = 5 + 3    = 8   # only positive points are winnable
        earned   = 5 + (-3) = 2   # met lines only — the penalty bites
        score    = 2 / 8    = 0.25

    The per-line verdicts (id, points, met, the judge's words) ride ``Score.metadata`` into the
    Case's one Check — the thinner Report the owner accepted (OME-1527 decision 1): no Check per
    line, and judge cost booked per Case. The criterion text stays out: it is private Grading
    Material.

    Args:
        judge_model: the gateway judge, ``screamingface/<model>``; the row pins the same one.

    Returns:
        The inspect scorer. Its Score's value is the Case score (may be negative).

    Raises:
        JudgeReplyUnparseable: a line had no parseable reply after its redraws.
        KeyError: the Sample carries no rubric (a broken Case, never "nothing to meet").
    """

    async def score(state: TaskState, target: Target) -> Score:
        judge: Any = get_model(judge_model)
        rubric: list[dict[str, Any]] = list(state.metadata["rubric"])
        items: list[dict[str, Any]] = []
        redraws: int = 0
        # Stage 1-2 — one judge call per line, redrawn on an unparseable reply.
        for line in rubric:
            prompt: str = build_grader_prompt(
                state.input_text,
                state.output.completion,
                render_rubric_item(line["points"], line["criterion"]),
            )
            judged: JudgedItem[tuple[bool, str]] = await judge_until_parsed(
                judge, prompt, parse_verdict, item=f"rubric item {line['rubric_id']}"
            )
            met, explanation = judged.verdict
            redraws += judged.redraws
            items.append(
                {
                    "rubric_id": line["rubric_id"],
                    "points": line["points"],
                    "met": met,
                    "explanation": explanation,
                }
            )
        # Stage 3 — earned over winnable, unclamped.
        winnable: int = sum(item["points"] for item in items if item["points"] > 0)
        earned: int = sum(item["points"] for item in items if item["met"])
        if winnable <= 0:
            raise ValueError("the rubric has no positive-points line; its score is undefined")
        return Score(
            value=earned / winnable,
            explanation=f"{earned} of {winnable} winnable points",
            metadata={"items": items, "judge_redraws": redraws},
        )

    return score


# ── the Task ──────────────────────────────────────────────────────────────────────────────
@task
def gdpval_text() -> Task:
    """GDPval's prose-only slice: 102 professional work requests graded on expert rubrics."""

    return Task(dataset=load_text_subset(), solver=generate(), scorer=gdpval_rubric())
