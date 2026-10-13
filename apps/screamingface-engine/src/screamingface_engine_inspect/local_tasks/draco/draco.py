# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai, datasets),
# absent in the default (extra-less) install the typecheck gate runs against; it is loaded only
# behind `inspect_available()`, like every other module in this package.
"""DRACO as a LOCAL inspect Task — the hand-built folder in inspect's shape (OME-1527).

Think of it as the same exam, now printed by the shared press: a dataset loader that prints the
question booklet (100 deep-research questions, each with its weighted rubric kept private), a
scorer that has the judge mark every rubric line several times over (the judge passes) and
averages the passes, and two `@task`s — `draco` (five passes, the paper's protocol) and
`draco_3pass` (three) — that differ only in that count.

Execution order, as the importer and the Engine see it:

    1. `draco()` / `draco_3pass()` → `load_draco()`: load `perplexity-ai/draco` at the pinned
       revision (the importer forces it at every build), in dataset order; each row becomes a
       Sample whose `input` is the research question, byte for byte, and whose metadata
       carries the weighted rubric and the domain (private Grading Material).
    2. the importer replays that twice in a clean child and seals the Cases by digest; at
       build, prepare replays it once more and serves nothing unless the digest matches.
    3. the Candidate answers once per Case, searching the web under the row's retrieval
       policy (search on, the sites that host DRACO's answers banned).
    4. at grading, `draco_rubric` asks the judge about each rubric line once per pass, pass
       ``k`` stamped ``seed=k`` so the passes are separate requests; a reply with no verdict is
       redrawn (twice at most), then that one line is left out of that pass.
    5. each pass is scored on its own (weighted MET over positive weight, clamped to 0..1), the
       Case score is the mean over passes to 4 places, and the run's headline is the mean over
       graded Cases to 4 places — the paper's normalized score.

INVARIANT — the judge's bytes are the hand-built Benchmark's (`prompts.py`), so the recorded
draco-3pass golden still replays against this Task; `test_local_task_draco.py` pins them.

References:
    - Paper: https://arxiv.org/abs/2602.11685 (DRACO, Zhong et al., Perplexity, 2026)
    - Dataset: https://huggingface.co/datasets/perplexity-ai/draco
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessage, ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState, generate

from screamingface_engine.benchmarks.shared_grading.judge_evidence import (
    JudgeEvidence,
    JudgeReplyFormat,
    parse_judge_evidence,
)
from screamingface_engine_inspect.judge_redraw import (
    MAX_JUDGE_REDRAWS,
    JudgedItem,
    JudgeReplyUnparseable,
    judge_until_parsed,
)
from screamingface_engine_inspect.local_tasks.draco.prompts import JUDGE_SYSTEM, judge_context
from screamingface_engine_inspect.local_tasks.draco.scoring import flatten_criteria, score_case

# ── pins (the hand-built variant.py) ─────────────────────────────────────────────────────
DATASET = "perplexity-ai/draco"
DATASET_REVISION = "ce076749809027649ebd331bcb70f42bf720d387"
CASE_COUNT = 100

#: The judge, as the scorer calls it through the gateway provider. The paper pins
#: Gemini-3-Pro Preview, which Google shut down on 2026-03-09; Google named Gemini-3.1-Pro
#: Preview its replacement, so this reproduction uses the successor. The row's JudgeSpec pins
#: the same model and its params (benchmark identity); see its WHY notes in `benchmarks.py`.
JUDGE_MODEL = "screamingface/openrouter/google/gemini-3.1-pro-preview"

#: The paper's stability protocol judges every answer five times; draco-3pass judges three.
OFFICIAL_JUDGE_PASSES = 5
THREE_PASSES = 3

#: The judge's reply dialect, the hand-built `verdict.py` SHAPE: a `criterion_status` of
#: exactly MET or UNMET, and an explanation it must give.
VERDICT_FORMAT = JudgeReplyFormat(
    schema="screamingface.criterion-verdict.v1",
    status_field="criterion_status",
    statuses=("MET", "UNMET"),
    explanation_required=True,
    reasons={
        "empty": "empty",
        "not_json": "invalid_json",
        "not_object": "invalid_shape",
        "bad_explanation": "invalid_shape",
        "missing_status": "invalid_shape",
        "bad_status": "invalid_status",
    },
)

COLUMN_QUESTION = "problem"
COLUMN_RUBRIC = "answer"
COLUMN_DOMAIN = "domain"


# ── dataset loader (the hand-built prepare.py, minus the bundle writing) ──────────────────
def load_draco() -> MemoryDataset:
    """Load the pinned dataset in its own order and render each row into a Sample."""

    import datasets  # recorded (and its revision forced) by the importer's Case Source recorder

    loaded: Any = datasets.load_dataset(DATASET, revision=DATASET_REVISION)
    rows: list[dict[str, Any]] = [dict(row) for split in loaded for row in loaded[split]]
    if len(rows) != CASE_COUNT:
        raise ValueError(
            f"expected {CASE_COUNT} DRACO rows at {DATASET}@{DATASET_REVISION}, got {len(rows)}"
        )
    samples: list[Sample] = [
        record_to_sample(row, case_id) for case_id, row in enumerate(rows, start=1)
    ]
    return MemoryDataset(samples=samples, name="draco")


def record_to_sample(row: Mapping[str, Any], case_id: int) -> Sample:
    """One DRACO row → the research question (the Candidate's whole prompt) and its rubric.

    The input is the `problem` column untouched — the hand-built `cases.json` input byte for
    byte. The rubric and the domain ride the metadata, private Grading Material.
    """

    question: object = row.get(COLUMN_QUESTION)
    if not isinstance(question, str) or not question:
        raise ValueError(f"case {case_id}: empty {COLUMN_QUESTION!r} column")
    return Sample(
        id=case_id,
        input=question,
        # No answer key: the judge grades against the rubric in the metadata.
        target="",
        metadata={
            "domain": row.get(COLUMN_DOMAIN) or "unknown",
            "rubric": parse_rubric(row.get(COLUMN_RUBRIC), case_id),
        },
    )


def parse_rubric(raw: object, case_id: int) -> dict[str, Any]:
    """Decode the `answer` column into the sectioned, weighted rubric the scorer walks.

    INVARIANT: every criterion has an id and a requirement, and the rubric has at least one —
    a rubric with no criteria would score every answer 0.0 while looking like a clean run.
    """

    rubric: object = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(rubric, dict) or "sections" not in rubric:
        raise ValueError(f"case {case_id}: rubric has no 'sections' key")
    criteria: list[dict[str, Any]] = list(flatten_criteria(rubric))
    if not criteria:
        raise ValueError(f"case {case_id}: rubric flattened to 0 criteria")
    for criterion in criteria:
        for field in ("id", "requirement"):
            value: object = criterion.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"case {case_id}: a criterion lacks its {field}")
    return rubric


def judge_criteria(rubric: Mapping[str, Any]) -> list[dict[str, str]]:
    """The criteria as the JUDGE sees them, in rubric order: id, requirement, and its type.

    INVARIANT: the judge never sees a weight. It is told only whether a criterion is
    positive or negative (the sign of its weight), so it can read MET correctly without
    learning how much the criterion is worth (the paper's official grading mode).
    """

    return [
        {
            "id": str(criterion["id"]),
            "requirement": str(criterion["requirement"]),
            "criterion_type": "negative" if float(criterion["weight"]) < 0 else "positive",
        }
        for criterion in flatten_criteria(rubric)
    ]


# ── the judge's reply ─────────────────────────────────────────────────────────────────────
def parse_verdict(reply: str) -> tuple[bool, str] | None:
    """The judge's verdict (True = MET) and its words, or None when the reply has no verdict.

    The hand-built rule, through the same shared parser: the JSON is recovered however the
    judge presented it, the status must be exactly MET or UNMET, and an explanation is
    required.
    """

    evidence: JudgeEvidence = parse_judge_evidence(
        reply, shape=VERDICT_FORMAT, identity=(), producer_id=JUDGE_MODEL
    )
    if not evidence.valid:
        return None
    fields: dict[str, object] = dict(evidence.payload)
    explanation: object = fields["explanation"]
    return fields["criterion_status"] == "MET", explanation if isinstance(explanation, str) else ""


# ── the scorer ────────────────────────────────────────────────────────────────────────────
@scorer(metrics=[mean(), stderr()])
def draco_rubric(
    judge_model: str = JUDGE_MODEL, judge_passes: int = OFFICIAL_JUDGE_PASSES
) -> Scorer:
    """Grade one research report against its rubric: every line, judged once per pass.

    Think of it as an examiner who marks the same script several times on separate days and
    reports the average mark, because one marking is noisy. Each rubric line goes to the judge
    alone, with the question and the answer, and the judge says whether the thing the line
    describes is in the answer. The weights come from the private rubric, never from the judge.

    Stages, in execution order:

    1. For each rubric line, in rubric order, and each pass ``k`` from 1: send the paper's
       instructions and that line through :func:`judge_until_parsed`, naming pass ``k`` so the
       call carries ``seed=k`` (the hand-built seeds). One call at a time, on purpose: the
       aggregate already grades 4 Cases at once, which is what the gateway admits per provider.
    2. A reply with no verdict is redrawn, at most twice, each a fresh sample outside the
       gateway cache. If it still has none, that line is left out of THAT pass (out of both
       the earned and the winnable weight), as the hand-built grader left out an invalid
       verdict. A Case with no valid verdict at all fails by name (``judge_reply_invalid``);
       it is never scored 0.
    3. Score each pass on its own: earned = the weights of the met lines (a met negative line
       subtracts), winnable = the positive weights, clamped to 0..1. The Case score is the mean
       over the passes, to 4 places.

    Worked example, weights ``[+3, +1, -2]``, two passes, the judge says
    pass 1: met, not met, not met; pass 2: met, met, met:

        pass 1 = 3 / 4           = 0.75
        pass 2 = (3 + 1 - 2) / 4 = 0.5
        score  = (0.75 + 0.5)/2  = 0.625

    Each line's verdicts per pass and the paper's other numbers (pass rate, per-axis scores,
    verdict coverage) ride ``Score.metadata`` into the Case's one Check — the thinner Report the
    owner accepted (OME-1527 decision 1). The criterion text stays out: it is Grading Material.

    Args:
        judge_model: the gateway judge, ``screamingface/<model>``; the row pins the same one.
        judge_passes: how many times each line is judged; the row's ``JudgeSpec`` declares
            ``seed_per_pass`` so each pass is its own request.

    Returns:
        The inspect scorer. Its Score's value is the Case score, 0..1.

    Raises:
        JudgeReplyUnparseable: no line got a valid verdict in any pass.
        KeyError: the Sample carries no rubric (a broken Case, never "nothing to meet").
    """

    if isinstance(judge_passes, bool) or not isinstance(judge_passes, int) or judge_passes < 1:
        raise ValueError(f"judge_passes must be a positive integer, got {judge_passes!r}")

    async def score(state: TaskState, target: Target) -> Score:
        judge: Any = get_model(judge_model)
        rubric: dict[str, Any] = dict(state.metadata["rubric"])
        criteria: list[dict[str, str]] = judge_criteria(rubric)
        # One dict per pass: criterion id → MET, for the lines that pass judged validly.
        passes: list[dict[str, bool]] = [{} for _ in range(judge_passes)]
        items: list[dict[str, Any]] = []
        redraws: int = 0
        # Stage 1-2 — every line, every pass; a line with no verdict drops out of that pass.
        for criterion in criteria:
            verdicts, line_redraws = await _judge_line(
                judge, criterion, state.input_text, state.output.completion, judge_passes
            )
            redraws += line_redraws
            for verdict in verdicts:
                if verdict["valid"]:
                    passes[verdict["pass"] - 1][criterion["id"]] = verdict["met"]
            items.append({"id": criterion["id"], "verdicts": verdicts})
        # A pass that judged nothing validly at the END drops out, as the hand-built grouping
        # did (its run list stopped at the last valid pass); an empty pass between valid ones
        # stays and scores 0, as it did there.
        while passes and not passes[-1]:
            passes.pop()
        if not passes:
            raise JudgeReplyUnparseable(
                f"the judge gave no valid verdict for any of {len(criteria)} criteria in "
                f"{judge_passes} passes"
            )
        # Stage 3 — each pass on its own, then the mean over passes (the paper's arithmetic).
        scored: dict[str, Any] = score_case(rubric, passes, criteria_expected=len(criteria))
        accepted: int = sum(len(judged_pass) for judged_pass in passes)
        expected: int = len(criteria) * judge_passes
        return Score(
            value=scored["normalized_score"],
            explanation=f"mean over {scored['n_runs']} judge passes",
            metadata={
                "items": items,
                "judge_redraws": redraws,
                "pass_rate": scored["pass_rate"],
                "normalized_score_sd": scored["normalized_score_sd"],
                "accuracy": scored["accuracy"],
                "axis_scores": scored["axis_scores"],
                "verdicts_expected": expected,
                "verdicts_accepted": accepted,
            },
        )

    return score


async def _judge_line(
    judge: Any, criterion: Mapping[str, str], question: str, answer: str, judge_passes: int
) -> tuple[list[dict[str, Any]], int]:
    """Ask the judge about one rubric line once per pass; its verdict per pass and the redraws.

    Each pass names its number, so its call carries ``seed=<pass>``; a pass whose reply never
    parses, even after its redraws, comes back ``valid: False`` instead of raising, so the
    line drops out of that pass alone.
    """

    prompt: list[ChatMessage] = [
        ChatMessageSystem(content=JUDGE_SYSTEM),
        ChatMessageUser(
            content=judge_context(
                criterion_type=criterion["criterion_type"],
                criterion=criterion["requirement"],
                question=question,
                answer=answer,
            )
        ),
    ]
    verdicts: list[dict[str, Any]] = []
    redraws: int = 0
    for judge_pass in range(1, judge_passes + 1):
        try:
            judged: JudgedItem[tuple[bool, str]] = await judge_until_parsed(
                judge,
                prompt,
                parse_verdict,
                item=f"criterion {criterion['id']} pass {judge_pass}",
                judge_pass=judge_pass,
            )
        except JudgeReplyUnparseable:
            redraws += MAX_JUDGE_REDRAWS
            verdicts.append({"pass": judge_pass, "valid": False})
            continue
        met, explanation = judged.verdict
        redraws += judged.redraws
        verdicts.append({"pass": judge_pass, "valid": True, "met": met, "explanation": explanation})
    return verdicts, redraws


# ── the Tasks ─────────────────────────────────────────────────────────────────────────────
@task
def draco() -> Task:
    """DRACO: 100 deep-research questions, each answer judged five times on its rubric."""

    return Task(
        dataset=load_draco(),
        solver=generate(),
        scorer=draco_rubric(judge_passes=OFFICIAL_JUDGE_PASSES),
    )


@task
def draco_3pass() -> Task:
    """DRACO with three judge passes instead of five; the same Cases and the same judge."""

    return Task(
        dataset=load_draco(),
        solver=generate(),
        scorer=draco_rubric(judge_passes=THREE_PASSES),
    )
