"""Install MedXpertQA's private assets and deterministic functions into one Runner world.

If `definition.py` writes the recipe, this module is the kitchen: a handler behind each of the
five routes so the recipe can resolve.

    /cases           → the question booklet (public: ids and questions, never the key)
    /check           → the Candidate committed: extract the letter, compare to the private key
    /check-surface   → mid-run correctness for the corrective loop
    /case-evaluation → collect the checked attempt into the per-Case artifact
    /aggregate       → reduce every Case into accuracy

INVARIANT: everything here is deterministic and spends no tokens. The model calls live in the
expression, not in these handlers — which is the whole reason this board's grading is free.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.evaluation import (
    aggregate_endpoint,
    candidate_answer,
    case_evaluation_endpoint,
    compact_json,
    json_object,
    positive_case_id,
)
from screamingface_engine.benchmarks.evaluation import benchmark_unavailable as _unavailable
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
    AGGREGATE_ROUTE,
    BENCHMARK_ID,
    CASE_EVALUATION_ROUTE,
    CASES_ROUTE,
    CHECK_ROUTE,
    REVISION,
)
from url4.peer.server import Request, Url4Node


def install(node: Url4Node, root: Path) -> None:
    """Register every route this board's expression references."""

    if CASES_ROUTE not in getattr(node, "_data", {}):
        node.data(CASES_ROUTE, _cases(root), media_type="application/json")
    installed = frozenset(node.processor_routes())
    endpoints = (
        (CHECK_ROUTE, _check(root)),
        (
            CASE_EVALUATION_ROUTE,
            case_evaluation_endpoint(
                label="MedXpertQA Case evaluation",
                item_name="Attempt",
                bind=bind_case_evaluation,
                error_context_head=300,
            ),
        ),
        (
            AGGREGATE_ROUTE,
            aggregate_endpoint(
                label="MedXpertQA",
                available_case_count=_case_count(root),
                aggregate=_aggregate(root),
            ),
        ),
    )
    for route, handler in endpoints:
        if route not in installed:
            node.endpoint(route)(handler)


def preflight(root: Path, case_ids: tuple[int, ...]) -> None:
    """Fail before the FIRST paid call when the baked assets cannot serve this exam."""

    problems: list[str] = []
    if not (root / "cases.json").is_file():
        problems.append(f"cases.json missing under {root}")
    for case_id in case_ids:
        if reducing.load_answer(root, case_id) is None:
            problems.append(f"answer record for case {case_id} missing or invalid")
    if problems:
        raise _unavailable("MedXpertQA assets failed preflight: " + "; ".join(problems[:8]))


def _cases(root: Path):
    def cases() -> str:
        """The public booklet, with each row's ready-made turn-1 prompt and turn-2 trigger.

        WHY the prompt and trigger are baked rather than assembled in the expression: prompt
        bytes are exam identity on a judge-free board, and an expression that composed them would
        put that identity outside the revision hash.
        """

        raw = _read(root / "cases.json", "MedXpertQA cases")
        rows = json.loads(raw)
        enriched = []
        for row in rows:
            case_id = int(row["id"])
            answer = reducing.load_answer(root, case_id)
            if answer is None:
                raise _unavailable(f"answer record for case {case_id} missing or invalid")
            enriched.append(
                {
                    "id": case_id,
                    "case_id": str(case_id),
                    "input": row["input"],
                    "cot_prompt": _cot_prompt(row["input"]),
                    "trigger": format_trigger(int(answer["options_count"])),
                }
            )
        return json.dumps(enriched, ensure_ascii=False, separators=(",", ":"))

    return cases


def _cot_prompt(question: str) -> str:
    from screamingface_engine.benchmarks.medxpert.prompts import COT_PROMPT_TEMPLATE

    return COT_PROMPT_TEMPLATE.format(question=question)


def _check(root: Path):
    """The gate between "the Candidate said something" and "we have a committed letter"."""

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
            raise _unavailable(str(exc)) from exc
        record: dict[str, Any] = {
            "schema": CHECK_SCHEMA,
            "case_id": case_id,
            "attempt": 1,
            # INVARIANT: no letter → "" → scored wrong. Never rescued by a lenient re-parse of
            # the raw text: that would save rows the official harness kills and inflate scores.
            "answer": letter or "",
            "answered": letter is not None,
            "status": commit.status,
            "refusal": commit.refusal,
            "finish_reason": commit.finish_reason,
            "commit_output": commit.text,
            # D8: the reasoning has no home in the shared candidate envelope, so it rides here.
            # A letter with no reasoning is unauditable.
            "reasoning": _reasoning_text(payload["reasoning"]),
            "execution": (
                None if commit.execution is None else commit.execution.model_dump(by_alias=True)
            ),
            **(
                {}
                if commit.operations is None
                else {
                    "operations": [
                        operation.model_dump(by_alias=True) for operation in commit.operations
                    ]
                }
            ),
        }
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


def _aggregate(root: Path):
    def aggregate_handler(case_evaluations: str, selected_case_count: int) -> dict[str, Any]:
        case_ids = tuple(range(1, selected_case_count + 1))
        return reducing.aggregate(
            case_evaluations,
            root,
            benchmark_id=BENCHMARK_ID,
            benchmark_revision=REVISION,
            case_ids=case_ids,
        )

    return aggregate_handler


def _case_count(root: Path) -> int:
    try:
        return len(json.loads((root / "cases.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        # The board's declared count stands in when assets are absent at install time; preflight
        # is what refuses a broken bundle, and it does so before any paid call.
        from screamingface_engine.benchmarks.medxpert.definition import CASE_COUNT

        return CASE_COUNT


def _read(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _unavailable(f"could not read {label} at {str(path)!r}: {exc}") from exc


__all__ = ["install", "preflight"]
