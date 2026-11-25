"""MedXpertQA's benchmark declaration — the serving spine runs the kitchen (OME-1236).

If `definition.py` writes the recipe, this module now only declares what makes this
benchmark different: booklet rows enriched with each Case's ready-made CoT prompt and
trigger, the two-field check that extracts the committed letter, and the accuracy
reducer. The routes, memoized preflight, case serving and aggregate wiring live in
`shared_grading/serving.py` — one kitchen for every hand-built deterministic benchmark.

INVARIANT: everything here is deterministic and spends no tokens. The model calls
live in the expression, not in these handlers — which is the whole reason this
benchmark's grading is free.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.case_grading_report import report_case_grading
from screamingface_engine.benchmarks.contract import (
    OperationOutput,
    decode_candidate_invocation_record,
)
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_definition_error as _definition_error,
)
from screamingface_engine.benchmarks.grading_endpoints import (
    CandidateAnswer,
    candidate_answer,
    compact_json,
    json_object,
    positive_case_id,
)
from screamingface_engine.benchmarks.grading_endpoints import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.medxpert import aggregate as reducing
from screamingface_engine.benchmarks.medxpert.answering import (
    extract_choice_letter,
    format_trigger,
)
from screamingface_engine.benchmarks.medxpert.case_grade import (
    CHECK_SCHEMA,
    build_case_grade,
)
from screamingface_engine.benchmarks.medxpert.commit import commit_chat, commit_recipe
from screamingface_engine.benchmarks.medxpert.definition import (
    BENCHMARK_ID,
    CASE_COUNT,
    COMMIT_CHAT_ROUTE,
    COMMIT_RECIPE_ROUTE,
    REVISION,
)
from screamingface_engine.benchmarks.phases import observe_phase
from screamingface_engine.benchmarks.picture_admission import node_model_routes
from screamingface_engine.benchmarks.shared_grading.serving import (
    ServedBenchmark,
    benchmark_preflight,
    candidate_record,
    install_benchmark,
    serve_cases,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

_LOG = logging.getLogger(__name__)


def install(node: Url4Node, root: Path) -> None:
    """Register every route this benchmark's expression references."""

    install_benchmark(node, root, BENCHMARK)
    # WHY the guard: local mode installs one node for many runs (see `install_benchmark`).
    if COMMIT_CHAT_ROUTE not in node.processor_routes():
        node.endpoint(COMMIT_CHAT_ROUTE)(_commit_chat)
    if COMMIT_RECIPE_ROUTE not in node.processor_routes():
        node.endpoint(COMMIT_RECIPE_ROUTE)(_commit_recipe_endpoint(node))


def preflight(root: Path, case_ids: tuple[int, ...]) -> None:
    """Fail before the FIRST paid call when the prepared assets cannot serve this benchmark."""

    benchmark_preflight(
        root,
        case_ids,
        label="MedXpertQA",
        load_answer=reducing.load_answer,
        # Per-benchmark deviation: a broken MedXpertQA bundle is a definition error,
        # not an unavailable asset — the class the reducer's callers key on.
        error=_definition_error,
    )


def _cases(root: Path):
    """The public booklet, served by the shared grading code with this benchmark's declaration."""

    return serve_cases(root, BENCHMARK)


def _build_public_cases(root: Path, rows: list[Any]) -> list[dict[str, Any]]:
    """Enrich each row with its ready-made turn-1 prompt and turn-2 trigger.

    WHY the prompt and trigger are prepared rather than assembled in the expression:
    prompt bytes are benchmark identity on a judge-free benchmark, and an expression that
    composed them would put that identity outside the revision hash.
    """

    enriched: list[dict[str, Any]] = []
    for row in rows:
        case_id = int(row["id"])
        answer = reducing.load_answer(root, case_id)
        if answer is None:
            raise _definition_error(f"answer record for case {case_id} missing or invalid")
        enriched.append(
            {
                "id": case_id,
                "case_id": str(case_id),
                "input": row["input"],
                "cot_prompt": _cot_prompt(row["input"]),
                "trigger": format_trigger(int(answer["options_count"])),
            }
        )
    return enriched


def _cot_prompt(question: str) -> str:
    from screamingface_engine.benchmarks.medxpert.prompts import COT_PROMPT_TEMPLATE

    return COT_PROMPT_TEMPLATE.format(question=question)


def _check(root: Path):
    """The gate between "the Candidate said something" and "we have a committed letter"."""

    @observe_phase(ActivityKind.GRADING)
    def check(request: Request) -> str:
        try:
            case_id = positive_case_id(request.intent)
            report_case_grading(case_id, "started")
            payload = json_object(request.context, "MedXpertQA check")
            if tuple(payload) != ("reasoning", "commit"):
                raise ValueError("MedXpertQA check fields must be reasoning, commit")
            answer = reducing.load_answer(root, case_id)
            if answer is None:
                raise ValueError(f"answer record for case {case_id} missing or invalid")
            commit = _with_turn_one_rows(candidate_answer(payload["commit"]), payload["reasoning"])
            trigger = format_trigger(int(answer["options_count"]))
            letter = extract_choice_letter(
                commit.text, int(answer["options_count"]), trigger=trigger
            )
        except (OSError, TypeError, ValueError) as exc:
            # AIDEV-NOTE (OME-1234): deliberate leftover on the catch-all — this except
            # clause mixes asset-IO and payload/definition causes; classifying needs a
            # try-body split.
            raise _unavailable(str(exc)) from exc
        record = candidate_record(
            commit,
            schema=CHECK_SCHEMA,
            case_id=case_id,
            verdict={
                # INVARIANT: no letter → "" → scored wrong. Never rescued by a lenient
                # re-parse of the raw text: that would save rows the official harness
                # kills and inflate scores.
                "answer": letter or "",
                "answered": letter is not None,
            },
            tail={
                "commit_output": commit.text,
                # D8: the reasoning has no home in the shared candidate envelope, so it
                # rides here. A letter with no reasoning is unauditable.
                "reasoning": _reasoning_text(payload["reasoning"]),
            },
        )
        return compact_json(record)

    return check


# WHY "answering": every installed route declares its stage, and this one builds the prompt of
# the Candidate's second turn; nothing is graded here.
@observe_phase(ActivityKind.ANSWERING)
def _commit_chat(request: Request) -> str:
    """Turn 1's prompt, result record and the trigger in; the chat turn 2 continues out.

    WHY a route (OME-1786): turn 2's prompt is built inside the expression, where turn 1 exists
    only as its whole record. The record's accounting differs between a live call and a cache
    hit, so passing it on made the same Case send different turn-2 bytes on a rerun. Only the
    record's answer text reaches the chat (``commit.commit_chat``).

    A turn 1 with no answer text (refused, empty, or a Fusion that abstained) is a valid record
    with an empty ``output``; the chat then has no assistant message and turn 2 still commits.

    WHY the contract's strict decoder and not ``_reasoning_text``: that reader is lenient, for
    the audit trail, and hands back whatever it was given when it cannot read a record. Here a
    record that is not exactly a Candidate's result must fail the Case: a lenient read would put
    the raw record, accounting included, back into the prompt, or let the model commit on a
    reasoning it never wrote.
    """

    # The prompt and trigger come from this Benchmark's own Case rows: a fault there is the
    # Benchmark's, never the Candidate's.
    try:
        payload: dict[str, Any] = json_object(request.context, "MedXpertQA commit chat")
        if tuple(payload) != ("prompt", "reasoning", "trigger"):
            raise ValueError("commit chat fields must be prompt, reasoning, trigger")
        prompt, record, trigger = payload["prompt"], payload["reasoning"], payload["trigger"]
        if not isinstance(prompt, str) or not isinstance(trigger, str) or not prompt or not trigger:
            raise ValueError("commit chat prompt and trigger must be non-empty text")
    except (TypeError, ValueError) as exc:
        raise _definition_error(f"MedXpertQA commit chat: {exc}") from exc
    try:
        answer: str = decode_candidate_invocation_record(record).output
    except (TypeError, ValueError) as exc:
        # The same code the Engine gives a Candidate whose record it cannot encode.
        raise ResolutionError(
            f"MedXpertQA turn-1 record is not a Candidate result: {exc}",
            code="candidate_contract_error",
            permanent=True,
        ) from exc
    return commit_chat(prompt, answer, trigger)


def _commit_recipe_endpoint(node: Url4Node) -> Callable[[Request], str]:
    """The route that names who answers turn 2, reading this node's model routes at call time."""

    # WHY "answering": it decides which model answers the Candidate's second turn.
    @observe_phase(ActivityKind.ANSWERING)
    def endpoint(request: Request) -> str:
        """The Candidate's recipe text in, the recipe turn 2 runs out (``commit.commit_recipe``).

        WHY the model routes are read per call, not at install: the world may register its
        gateway after this Benchmark is installed. A node with no gateway has no model routes,
        so every recipe runs whole: the safe answer.
        """

        if not request.context or not request.context.strip():
            raise ResolutionError(
                "MedXpertQA commit turn has no Candidate recipe",
                code="candidate_contract_error",
                permanent=True,
            )
        models: frozenset[str] = node_model_routes(node)
        recipe: str = commit_recipe(request.context, lambda path: path in models)
        # WHY a log line: a recipe the shortcut cannot lift runs whole with no error, which for a
        # Fusion means members billed twice again. This says which path ran, never the recipe.
        # WHY debug: it fires once per Case (2,450 lines a run at info).
        _LOG.debug(
            "MedXpertQA commit turn: %s",
            "one model" if recipe != request.context else "whole recipe",
        )
        return recipe

    return endpoint


def _with_turn_one_rows(commit: CandidateAnswer, turn_one: object) -> CandidateAnswer:
    """The commit's per-step rows, plus turn 1's rows for steps the commit did not run.

    FEATURE (OME-1980): when one model writes the commit (a Fusion's synthesizer), the members
    are not called on turn 2, so the commit's record holds only ``op_synthesis_1``. The members'
    turn-1 rows are copied in, in turn 1's order, so the graded record still shows every member
    and what its one call cost (the SDK's per-member and per-Case cost views read "unknown" for
    a row with no accounting).

    INVARIANT: a copied row carries its output, finish reason and accounting, never budget
    charges or combine/decision evidence. Copying the accounting counts nothing twice: the run's
    cost comes from its own usage total, not from these rows, and each member made exactly one
    call. A row the commit ran itself is never replaced.

    AIDEV-NOTE: the writer's row is the commit's own, so ``op_synthesis_1`` carries only its
    turn-2 call. Its turn-1 call (for a Fusion, the costliest one) is in no row: the SDK shows
    it in the run's unattributed remainder (run total minus the rows), so it is still counted,
    once.

    Worked example: turn 1 [op_model_1 "A", op_model_2 "D", op_synthesis_1 "...D"], commit
    [op_synthesis_1 "D."] → [op_model_1 "A", op_model_2 "D", op_synthesis_1 "D."].
    """

    earlier: list[OperationOutput] | None = _turn_one_operations(turn_one)
    if commit.operations is None or not earlier:
        return commit
    ran: dict[str, OperationOutput] = {row.operation_id: row for row in commit.operations}
    merged: list[OperationOutput] = [
        ran.pop(row.operation_id, None)
        or OperationOutput(
            operation_id=row.operation_id,
            output=row.output,
            finish_reason=row.finish_reason,
            accounting=row.accounting,
        )
        for row in earlier
    ]
    return replace(commit, operations=(*merged, *ran.values()))


def _turn_one_operations(turn_one: object) -> list[OperationOutput] | None:
    """Turn 1's per-step rows; None when the value is not a Candidate result record.

    WHY lenient here: the commit-chat route already refused a malformed turn 1 before turn 2
    ran, so this only reads evidence for the audit trail and never fails the check.
    """

    if not isinstance(turn_one, str):
        return None
    try:
        return decode_candidate_invocation_record(turn_one).operations
    except ValueError:
        return None


def _reasoning_text(value: object) -> str:
    """The turn-1 text, however the invocation envelope wrapped it."""

    if not isinstance(value, str):
        return ""
    try:
        decoded = json.loads(value)
    except ValueError:
        decoded = None
    output = decoded.get("output") if isinstance(decoded, Mapping) else None
    return output if isinstance(output, str) else value


BENCHMARK = ServedBenchmark(
    benchmark_id=BENCHMARK_ID,
    label="MedXpertQA",
    revision=REVISION,
    declared_case_count=CASE_COUNT,
    # AIDEV-NOTE: late-bound through the module global for parity with contracteval's
    # seam (whose prepare-test assigns `runtime.preflight` directly); a direct
    # reference here would freeze the original against any such replacement.
    preflight=lambda root, case_ids: preflight(root, case_ids),
    build_public_cases=_build_public_cases,
    check=_check,
    build_case_grade=build_case_grade,
    reduce=reducing.aggregate_result,
    scoring=reducing.scoring,
)

__all__ = ["BENCHMARK", "install", "preflight"]
