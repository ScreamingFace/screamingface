# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai, datasets),
# absent in the default (extra-less) install the typecheck gate runs against; it is loaded only
# behind `inspect_available()`, like every other module in this package.
"""HealthBench as a LOCAL inspect Task — the hand-built folder in inspect's shape (OME-1527).

Think of it as the same exam, now printed by the shared press: a dataset loader that prints the
question booklet (physician-reviewed clinical chats, each with its points rubric kept private),
a scorer that has the judge tick each rubric line once and adds up the points, and two
`@task`s over the same booklet — `healthbench_worst30` (the frozen hardest 157, scored by the
plain mean, negatives kept) and `healthbench_professional` (all 525, scored by the official
clipped mean).

Execution order, as the importer and the Engine see it:

    1. `healthbench_worst30()` / `healthbench_professional()` → `load_rows()`: load
       `openai/healthbench-professional` at the pinned revision (the importer forces it at every
       build), in file order; worst-30 keeps the frozen selection in its frozen order. Each row
       becomes a Sample whose `input` is the chat as inspect messages and whose metadata carries
       the points rubric (private Grading Material).
    2. the importer replays that twice in a clean child and seals the Cases by digest; capture
       writes a one-message chat as its text and a longer chat as the candidate-input envelope.
       The row serves the Candidate every input in that envelope, as the hand-built Benchmark
       did, so the Candidate's bytes (and the recorded worst-30 golden) do not move.
    3. the Candidate answers once per Case, with the next assistant turn, no web search.
    4. at grading, `healthbench_rubric` sends the judge the reference grader prompt once per
       rubric line; a reply with no verdict is redrawn (twice at most), and a line that never
       parses fails the Case (`judge_reply_invalid`), as the hand-built grader failed it.
    5. the Case score is earned over winnable points, unclamped. worst-30's headline is the
       plain mean over graded Cases; professional's is `healthbench_clipped_mean`, the
       reference's `np.clip(mean, 0, 1)` over the run.

INVARIANT — the Candidate's and the judge's bytes are the hand-built Benchmark's, so the
recorded healthbench-worst30 golden still replays against this Task;
`test_local_task_healthbench.py` pins them.

References:
    - simple-evals (protocol authority): https://github.com/openai/simple-evals
    - Dataset: https://huggingface.co/datasets/openai/healthbench-professional
    - Paper: https://arxiv.org/abs/2604.27470 (HealthBench Professional, Hicks et al., 2026)
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessage, ChatMessageAssistant, ChatMessageUser, get_model
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

from screamingface_engine.benchmarks.shared_grading.judge_evidence import (
    JudgeEvidence,
    JudgeReplyFormat,
    parse_judge_evidence,
)
from screamingface_engine_inspect.judge_redraw import JudgedItem, judge_until_parsed
from screamingface_engine_inspect.local_tasks.healthbench.prompts import (
    build_grader_prompt,
    render_rubric_item,
)
from screamingface_engine_inspect.local_tasks.healthbench.scoring import case_score, clipped_mean
from screamingface_engine_inspect.local_tasks.healthbench.subset import WORST30_HF_IDS

# ── pins (the hand-built revision_inputs.py) ─────────────────────────────────────────────
DATASET = "openai/healthbench-professional"
DATASET_REVISION = "349962fd46dd02343a0d8a606491baf59154ea1a"
#: The pinned revision holds exactly this many rows; a dataset that grew or shrank would
#: otherwise ship a differently-sized Benchmark under the professional identity.
PROFESSIONAL_CASE_COUNT = 525

#: The judge, as the scorer calls it through the gateway provider. The official professional
#: judge is an OpenAI-internal gpt-5.4 snapshot we cannot reach; OpenRouter routes the floating
#: slug (a named deviation). The row's JudgeSpec pins the same model and its params.
JUDGE_MODEL = "screamingface/openrouter/openai/gpt-5.4"

#: The judge's reply dialect, the hand-built `verdict.py` SHAPE. INVARIANT: only a REAL JSON
#: boolean counts (statuses=None) — a string "true" or a 1 is no verdict, so it is redrawn;
#: the reference loops until `label is True or label is False`.
VERDICT_FORMAT = JudgeReplyFormat(
    schema="screamingface.healthbench-rubric-verdict.v1",
    status_field="criteria_met",
    statuses=None,
    explanation_required=False,
    reasons={
        "empty": "empty",
        "not_json": "invalid_json",
        "not_object": "invalid_shape",
        "missing_status": "invalid_criteria_met",
        "bad_status": "invalid_criteria_met",
    },
)

#: The chat roles a HealthBench conversation holds. The pinned revision has no system turn,
#: and a Benchmark could not hand one to the Candidate anyway (capture refuses it).
_ROLES: Mapping[str, type[ChatMessageUser | ChatMessageAssistant]] = {
    "user": ChatMessageUser,
    "assistant": ChatMessageAssistant,
}


# ── dataset loader (the hand-built prepare.py, minus the bundle writing) ──────────────────
def load_rows() -> list[dict[str, Any]]:
    """Load the pinned dataset and return its rows in file order, all 525 of them."""

    import datasets  # recorded (and its revision forced) by the importer's Case Source recorder

    loaded: Any = datasets.load_dataset(DATASET, revision=DATASET_REVISION)
    rows: list[dict[str, Any]] = [dict(row) for split in loaded for row in loaded[split]]
    if len(rows) != PROFESSIONAL_CASE_COUNT:
        raise ValueError(
            f"{DATASET}@{DATASET_REVISION} holds {len(rows)} rows, but the professional "
            f"Benchmark declares {PROFESSIONAL_CASE_COUNT} Cases; refusing to prepare a "
            "differently-sized Benchmark under that identity"
        )
    return rows


def select_worst30(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The frozen worst-30% selection in its frozen order (hardest first).

    Case k is the k-th frozen id. A dataset that dropped a frozen id fails the build rather
    than silently serving a smaller Benchmark under the same identity.
    """

    by_id: dict[str, Mapping[str, Any]] = {str(row.get("id")): row for row in rows}
    missing: list[str] = [hf_id for hf_id in WORST30_HF_IDS if hf_id not in by_id]
    if missing:
        raise ValueError(
            f"{len(missing)} frozen worst-30% id(s) are absent from {DATASET}@"
            f"{DATASET_REVISION}, first {missing[0]!r}; refusing to prepare a different "
            "Benchmark under this identity"
        )
    return [by_id[hf_id] for hf_id in WORST30_HF_IDS]


def record_to_sample(row: Mapping[str, Any], case_id: int) -> Sample:
    """One HealthBench row → its chat (the Candidate's whole prompt) and its points rubric.

    The chat's turns keep their order, roles and text, so capture writes the hand-built
    `cases.json` input byte for byte. The rubric and the dataset's row id ride the metadata,
    private Grading Material.
    """

    return Sample(
        id=case_id,
        input=case_messages(row, case_id),
        # No answer key: the judge grades against the rubric in the metadata.
        target="",
        metadata={"hf_id": str(row.get("id")), "rubric": rubric_items(row, case_id)},
    )


def case_messages(row: Mapping[str, Any], case_id: int) -> list[ChatMessage]:
    """Decode one row's conversation into inspect messages, refusing a damaged turn."""

    conversation: object = row.get("conversation")
    if isinstance(conversation, str):
        try:
            conversation = json.loads(conversation)
        except ValueError as exc:
            raise ValueError(f"case {case_id}: conversation is not JSON: {exc}") from None
    raw: object = conversation.get("messages") if isinstance(conversation, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"case {case_id}: conversation must carry a non-empty messages list")
    messages: list[ChatMessage] = []
    for index, message in enumerate(raw):
        role: object = message.get("role") if isinstance(message, dict) else None
        content: object = message.get("content") if isinstance(message, dict) else None
        if role not in _ROLES or not isinstance(content, str) or not content.strip():
            raise ValueError(f"case {case_id}: message {index} must be a user or assistant turn")
        assert isinstance(role, str)
        messages.append(_ROLES[role](content=content))
    return messages


def rubric_items(row: Mapping[str, Any], case_id: int) -> list[dict[str, Any]]:
    """One row's flat rubric: ``rubric_id`` 1.., the criterion text, integer points.

    INVARIANT: points are integers (the judge must see "[7]", never "[7.0]"), and a rubric with
    no positive-points line fails the build: its score would divide by zero.
    """

    raw: object = row.get("rubric_items")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise ValueError(f"case {case_id}: rubric_items is not JSON: {exc}") from None
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"case {case_id}: rubric_items must be a non-empty list")
    items: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        criterion: object = item.get("criterion_text") if isinstance(item, dict) else None
        points: object = item.get("points") if isinstance(item, dict) else None
        if not isinstance(criterion, str) or not criterion.strip():
            raise ValueError(f"case {case_id}: rubric item {index} lacks criterion_text")
        if isinstance(points, bool) or not isinstance(points, int):
            raise ValueError(
                f"case {case_id}: rubric item {index} points must be an integer, got {points!r}"
            )
        items.append({"rubric_id": index, "criterion": criterion, "points": points})
    if not any(item["points"] > 0 for item in items):
        raise ValueError(f"case {case_id}: no positive-points rubric item")
    return items


# ── the judge's reply ─────────────────────────────────────────────────────────────────────
def parse_verdict(reply: str) -> tuple[bool, str] | None:
    """The judge's verdict and its words, or None when the reply carries no verdict.

    The hand-built rule, through the same shared parser: the JSON is recovered however the
    judge presented it (fenced, prose-prefixed, bare), and only a REAL JSON boolean
    `criteria_met` counts.
    """

    evidence: JudgeEvidence = parse_judge_evidence(
        reply, shape=VERDICT_FORMAT, identity=(), producer_id=JUDGE_MODEL
    )
    if not evidence.valid:
        return None
    fields: dict[str, object] = dict(evidence.payload)
    explanation: object = fields.get("explanation")
    return fields["criteria_met"] is True, explanation if isinstance(explanation, str) else ""


def transcript(state: TaskState) -> str:
    """The reference's judge view of the chat: ``role: content`` turns joined by blank lines.

    A one-message chat reaches the scorer as its text, a longer one as inspect messages; both
    read as the hand-built route read its envelope (``runtime._transcript``), e.g.
    ``"user: My knee hurts.\\n\\nassistant: Since when?\\n\\nuser: Two days."``.
    """

    if isinstance(state.input, str):
        return f"user: {state.input}"
    return "\n\n".join(f"{message.role}: {message.text}" for message in state.input)


# ── the scorer ────────────────────────────────────────────────────────────────────────────
@scorer(metrics=[mean(), stderr()])
def healthbench_rubric(judge_model: str = JUDGE_MODEL) -> Scorer:
    """Grade one answer against its rubric: one judge call per line, then the points.

    Think of it as an examiner with a physician's checklist who may only look at one line at a
    time: each line goes to the judge alone, inside the reference grader prompt with the whole
    chat and the answer as its last assistant turn, and the judge says met or not. The points
    come from the private rubric, never from the judge.

    Stages, in execution order:

    1. For each rubric line, in rubric order: render ``[points] criterion`` into the reference
       grader prompt and ask the judge through :func:`judge_until_parsed`, as one user message
       with no system message (the official judge sends none). One line at a time, on purpose:
       the aggregate already grades 4 Cases at once, which is what the gateway admits per
       provider, so a parallel fan-out here would only queue.
    2. A reply that won't parse is redrawn, at most twice, each a fresh sample outside the
       gateway cache (the hand-built ``;retry=2``); after that the line raises and the whole
       Case fails by name (``judge_reply_invalid``). A partly judged Case is never scored: a
       lost penalty line would silently raise its score.
    3. Score: earned = the points of every met line (penalties subtract), winnable = the sum
       of the positive points. No clamp: a harmful answer can rank below one that said nothing.

    Worked example, points ``[+5, +3, -3]``, the judge says met, not met, met:

        winnable = 5 + 3    = 8   # only positive points are winnable
        earned   = 5 + (-3) = 2   # met lines only — the penalty bites
        score    = 2 / 8    = 0.25

    The per-line verdicts (id, points, met, the judge's words) and the redraw count ride
    ``Score.metadata`` into the Case's one Check — the thinner Report the owner accepted
    (OME-1527 decision 1). So do the verdict counts, ``verdicts_expected`` (one box per line)
    and ``verdicts_accepted``, which the lane adds up for the Report's grading warning; on a
    graded Case they are equal, because a line with no verdict fails its Case instead. The
    criterion text stays out: it is private Grading Material.

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
        chat: str = transcript(state)
        items: list[dict[str, Any]] = []
        redraws: int = 0
        # Stage 1-2 — one judge call per line, redrawn on an unparseable reply.
        for line in rubric:
            prompt: str = build_grader_prompt(
                chat,
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
        # Stage 3 — earned over winnable, unclamped (the reference `calculate_score`).
        value: float | None = case_score(
            [item["points"] for item in items],
            {item["rubric_id"]: item["met"] for item in items},
        )
        if value is None:
            raise ValueError("the rubric has no positive-points line; its score is undefined")
        return Score(
            value=value,
            explanation=f"{len(items)} rubric lines judged",
            metadata={
                "items": items,
                "judge_redraws": redraws,
                "verdicts_expected": len(rubric),
                "verdicts_accepted": len(items),
            },
        )

    return score


# ── the run's tally sheet (professional only) ─────────────────────────────────────────────
@metric
def healthbench_clipped_mean() -> Metric:
    """The OFFICIAL HealthBench headline: the mean of the Case scores, then clipped to 0..1.

    WHY a whole-run metric and not a per-Case clamp: clipping the run's mean is not the mean of
    clipped Case scores. Worked example, Case scores ``[0.25, 0.5, -2.5, 1.0]``:

        clipped mean      = max(0, (0.25 + 0.5 - 2.5 + 1.0) / 4) = max(0, -0.1875) = 0.0
        mean of clamped   = (0.25 + 0.5 + 0.0 + 1.0) / 4                           = 0.4375

    The reference publishes the first. A Case whose grading failed never reaches the metric,
    as it never reached the hand-built mean.
    """

    def compute(scores: list[SampleScore]) -> float:
        values: list[float] = [sample_score.score.as_float() for sample_score in scores]
        clipped: float | None = clipped_mean(values)
        if clipped is None:
            raise ValueError("the clipped mean needs at least one graded Case")
        return clipped

    return compute


# ── the Tasks ─────────────────────────────────────────────────────────────────────────────
@task
def healthbench_worst30() -> Task:
    """HealthBench worst-30%: the frozen hardest 157 chats, scored by the plain mean."""

    samples: list[Sample] = [
        record_to_sample(row, case_id)
        for case_id, row in enumerate(select_worst30(load_rows()), start=1)
    ]
    return Task(
        dataset=MemoryDataset(samples=samples, name="healthbench_worst30"),
        solver=generate(),
        scorer=healthbench_rubric(),
    )


@task
def healthbench_professional() -> Task:
    """HealthBench Professional: all 525 chats, scored by the official clipped mean."""

    samples: list[Sample] = [
        record_to_sample(row, case_id) for case_id, row in enumerate(load_rows(), start=1)
    ]
    return Task(
        dataset=MemoryDataset(samples=samples, name="healthbench_professional"),
        solver=generate(),
        scorer=healthbench_rubric(),
        metrics=[healthbench_clipped_mean()],
    )
