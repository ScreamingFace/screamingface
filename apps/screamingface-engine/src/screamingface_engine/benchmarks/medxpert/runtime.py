"""MedXpertQA's exam declaration — the serving spine runs the kitchen (OME-1236).

If `definition.py` writes the recipe, this module now only declares what makes this
exam different: booklet rows enriched with each Case's ready-made CoT prompt and
trigger, the two-field check that extracts the committed letter, and the accuracy
reducer. The routes, memoized preflight, case serving and aggregate wiring live in
`spine/serving.py` — one kitchen for every hand-built deterministic board.

INVARIANT: everything here is deterministic and spends no tokens. The model calls
live in the expression, not in these handlers — which is the whole reason this
board's grading is free.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.evaluation import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.evaluation import (
    candidate_answer,
    compact_json,
    json_object,
    positive_case_id,
)
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_definition_error as _definition_error,
)
from screamingface_engine.benchmarks.medxpert import aggregate as reducing
from screamingface_engine.benchmarks.medxpert.answering import (
    extract_choice_letter,
    format_trigger,
)
from screamingface_engine.benchmarks.medxpert.case_evaluation import (
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine.benchmarks.medxpert.definition import (
    BENCHMARK_ID,
    CASE_COUNT,
    REVISION,
)
from screamingface_engine.benchmarks.spine.serving import (
    ServedBoard,
    board_preflight,
    candidate_record,
    install_board,
    serve_cases,
)
from screamingface_engine.benchmarks.stages import BenchmarkStage, observe_stage
from url4.peer.server import Request, Url4Node


def install(node: Url4Node, root: Path) -> None:
    """Register every route this board's expression references."""

    install_board(node, root, BOARD)


def preflight(root: Path, case_ids: tuple[int, ...]) -> None:
    """Fail before the FIRST paid call when the baked assets cannot serve this exam."""

    board_preflight(
        root,
        case_ids,
        label="MedXpertQA",
        load_answer=reducing.load_answer,
        # Per-board deviation: a broken MedXpertQA bundle is a definition error,
        # not an unavailable asset — the class the reducer's callers key on.
        error=_definition_error,
    )


def _cases(root: Path):
    """The public booklet, served by the spine with this board's declaration."""

    return serve_cases(root, BOARD)


def _build_rows(root: Path, rows: list[Any]) -> list[dict[str, Any]]:
    """Enrich each row with its ready-made turn-1 prompt and turn-2 trigger.

    WHY the prompt and trigger are baked rather than assembled in the expression:
    prompt bytes are exam identity on a judge-free board, and an expression that
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

    @observe_stage(BenchmarkStage.GRADING_CHECK)
    def check(request: Request) -> str:
        try:
            case_id = positive_case_id(request.intent)
            payload = json_object(request.context, "MedXpertQA check")
            if tuple(payload) != ("reasoning", "commit"):
                raise ValueError("MedXpertQA check fields must be reasoning, commit")
            answer = reducing.load_answer(root, case_id)
            if answer is None:
                raise ValueError(f"answer record for case {case_id} missing or invalid")
            commit = candidate_answer(payload["commit"])
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


BOARD = ServedBoard(
    benchmark_id=BENCHMARK_ID,
    label="MedXpertQA",
    revision=REVISION,
    declared_case_count=CASE_COUNT,
    # AIDEV-NOTE: late-bound through the module global for parity with contracteval's
    # seam (whose prepare-test assigns `runtime.preflight` directly); a direct
    # reference here would freeze the original against any such replacement.
    preflight=lambda root, case_ids: preflight(root, case_ids),
    build_rows=_build_rows,
    check=_check,
    bind_case_evaluation=bind_case_evaluation,
    reduce=reducing.aggregate,
)

__all__ = ["BOARD", "install", "preflight"]
