"""One factory turns an imported single-shot eval into a complete Engine board.

Think of it as the plugin's own assembly line: hand it a board's identity, its pinned
dataset facts, and its scorer, and it stamps out everything the engine expects — the
url4 protocol, the runtime routes, the ScoredPath binding, and the registration. The
per-board modules (`gsm8k.py`, `mmlu.py`) shrink to declarations — the spec §5 "≤150
lines per board" budget made structural.

The load-bearing move (spec §4): when a board declares a check surface, the SAME
wrapped scorer serves both the grading route (after the exam) and the mid-run check
(during it). MCQ boards get NO check surface — pass/fail feedback over a handful of
options is an elimination attack (OME-796), and the client preflight's refusal of a
loop recipe there is correct behavior.

FEATURE: imported inspect_evals benchmarks run in our product like any board
(OME-1115, parent OME-1111).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.contract import CANDIDATE_RESULT_SCHEMA, CaseResult
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    CheckSurface,
    candidate,
)
from screamingface_engine.benchmarks.deployment import (
    BenchmarkAssetBundle,
    BenchmarkAssetPreparer,
    BenchmarkRegistration,
)
from screamingface_engine.benchmarks.ensemble.policy import CHECK_SURFACE_SCHEMA
from screamingface_engine.benchmarks.evaluation import (
    aggregate_endpoint,
    attempt_records_endpoint,
    candidate_answer,
    compact_json,
    json_object,
    positive_case_id,
)
from screamingface_engine.benchmarks.evaluation import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    build_evaluation_protocol,
    preserve_candidate_outcome,
)
from screamingface_engine.benchmarks.spine.payloads import TextPayload
from screamingface_engine.benchmarks.spine.rows import RowReader, read_selected_cases
from screamingface_engine.benchmarks.spine.scored import (
    CaseGradeOutcome,
    GradeRequest,
    ScoredPath,
)
from screamingface_engine.benchmarks.stages import BenchmarkStage, observe_stage
from screamingface_engine_inspect.envelopes import (
    CHECK_SCHEMA,
    bind_case_evaluation,
    decode_case_evaluation,
)
from screamingface_engine_inspect.pins import (
    PREPARER_REVISION,
    PROTOCOL_REVISION,
    pinned_inspect_packages,
)
from url4 import Node, RelExpr, Text, expr, render, src, struct
from url4.peer.server import Request, Url4Node

# INVARIANT: imported grading is retrieval-free — their scorers compare text to a
# pinned target; a model that searched would answer a different question.
_CANDIDATE_WEB_SEARCH = False

# INVARIANT: failure wording is this plugin's published voice; no rubric-flavored
# codes may leak into an imported board's result.
_FAILURE_MESSAGES: Mapping[str, str] = {
    "scorer_error": "the inspect scorer raised while grading this Case",
    "invalid_score_value": "the inspect scorer returned a value this board cannot map to a score",
    "missing_target_asset": "the baked target record for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
}

# WHY this text and nothing richer: mid-run feedback crosses into the candidate's
# context, so it must never carry the target or the scorer's explanation (which may
# quote it). Wrong-ness is the entire message; the sealed envelope holds.
_CHECK_FEEDBACK = (
    "The committed answer does not match the expected solution. "
    "Re-derive the result step by step and commit a corrected final answer."
)


class AggregateError(ValueError):
    """An imported board's reducer input is unusable — raised before any scoring."""


@dataclass(frozen=True, slots=True)
class ImportedBoard:
    """One assembled imported board — the benchmark plus its plugin-side bindings."""

    benchmark: Benchmark
    registration: BenchmarkRegistration
    scorer_factory: Callable[[], Any]
    multiple_correct: bool
    cases_route: str
    check_route: str
    check_surface_route: str
    case_evaluation_route: str
    aggregate_route: str

    def scored_path(self) -> ScoredPath:
        """This board's spine binding — built on demand so the scorer stays lazy."""

        # WHY lazy: the shim imports inspect_ai (which drags in a web stack and the
        # OTel SDK). Board REGISTRATION happens at engine import in every mode; the
        # shim is needed only when a Runner world actually grades, so the run entry
        # point's cold-start import budget stays untouched (test_cli /
        # test_span_export_wiring pin this).
        from screamingface_engine_inspect.shim import inspect_grade_case

        return ScoredPath(
            reader=RowReader(
                benchmark_label=self.benchmark.title,
                error_type=AggregateError,
                decode_case_evaluation=_decode,
            ),
            grade_case=inspect_grade_case(
                self.scorer_factory(), multiple_correct=self.multiple_correct
            ),
            failure_messages=_FAILURE_MESSAGES,
            method="inspect_scorer",
            grading_failure_code="inspect_grading_failed",
            grading_failure_message="the inspect scorer pipeline could not grade this Case",
            missing_material_code="missing_target_asset",
        )


def single_shot_board(
    *,
    board_key: str,
    title: str,
    description: str,
    focus: str,
    dataset_url: str,
    case_count: int,
    revision_pins: Sequence[str],
    scorer_factory: Callable[[], Any],
    prepare: BenchmarkAssetPreparer,
    install: Callable[[Url4Node, Path], None],
    with_check_surface: bool,
    multiple_correct: bool = False,
) -> ImportedBoard:
    """Assemble one imported single-shot board from its declarations.

    Stage 1 — identity: benchmark id ``inspect-<key>`` (flat, OME-836) and the §6
              revision — sha over the pinned inspect packages + the dataset pins +
              the protocol constants, 16 hex chars.
    Stage 2 — protocol: the canonical one-invocation expression (ifeval's shape) —
              candidate answers ``$item.input``, the check route records the attempt,
              the aggregate grades everything engine-side through the shim.
    Stage 3 — runtime: an installer registering cases/check/case-evaluation/aggregate,
              plus the check-surface port iff declared.
    Stage 4 — registration: benchmark + asset bundle, ready for the entry point.

    Args:
        board_key: the flat identity tail ("gsm8k" → benchmark id "inspect-gsm8k").
        title, description, focus, dataset_url: leaderboard display fields (OME-904).
        case_count: rows in the pinned split — the board's declared exam size.
        revision_pins: every dataset fact that participates in exam identity.
        scorer_factory: zero-arg callable returning the imported eval's scorer.
        prepare: the board's build-time asset baker (its snapshot of the dataset).
        install: the board module's OWN installer wrapper (defined beside its
            ``ASSET_BUNDLE_ID`` constant, per the deployment conformance rule), which
            delegates to :func:`install_imported_board`.
        with_check_surface: §4 dual registration; False for MCQ boards (OME-796).
        multiple_correct: inspect's MCQ multi-answer flag, passed to the shim.

    Returns:
        The assembled board, its registration ready for the plugin's entry point.
    """

    benchmark_id: str = f"inspect-{board_key}"
    # WHY: pins are newline-joined below; a pin containing "\n" would make two
    # different pin lists hash identically — refused, never coerced.
    if any("\n" in pin for pin in revision_pins):
        raise ValueError(f"{benchmark_id}: revision_pins must not contain newlines")
    revision: str = hashlib.sha256(
        "\n".join(
            (
                *pinned_inspect_packages(),
                *revision_pins,
                PREPARER_REVISION,
                PROTOCOL_REVISION,
                EVALUATION_PROTOCOL_REVISION,
                CANDIDATE_RESULT_SCHEMA,
                # WHY hashed HERE, not left to revision_pins: the factory owns
                # identity math (§6 — the case subset rides the revision); a board
                # author forgetting a pin must not get a subset change with an
                # unchanged exam identity.
                f"case_count={case_count}",
                f"check_surface={with_check_surface}",
            )
        ).encode()
    ).hexdigest()[:16]
    prefix: str = f"/benchmarks/{benchmark_id}/{revision}"
    routes: dict[str, str] = {
        "cases": f"{prefix}/cases",
        "check": f"{prefix}/check",
        "check_surface": f"{prefix}/check-surface",
        "case_evaluation": f"{prefix}/case-evaluation",
        "aggregate": f"{prefix}/aggregate",
    }

    benchmark = Benchmark(
        id=benchmark_id,
        title=title,
        description=description,
        revision=revision,
        case_count=case_count,
        build=_build(routes, case_count),
        install=install,
        focus=focus,
        dataset_url=dataset_url,
        declaration=BenchmarkDeclaration(
            # WHY "coverage_declare": imported boards reduce through the shared
            # finalize_candidate_result, which scores the gradeable subset and
            # publishes coverage — the declaration matches the code (OME-1039).
            failure_policy="coverage_declare",
            interaction="single_shot",
        ),
        check_surface=(
            CheckSurface(
                check_route=routes["check_surface"],
                feedback_intent="feedback",
                # Free: both proof scorers are deterministic. No cost knob exists
                # yet (YAGNI) — OME-1116 adds one when the first model-graded
                # import lands.
                expected_check_cost="free",
            )
            if with_check_surface
            else None
        ),
    )
    board = ImportedBoard(
        benchmark=benchmark,
        registration=BenchmarkRegistration(
            benchmark=benchmark,
            asset_bundle=BenchmarkAssetBundle(id=benchmark_id, prepare=prepare),
        ),
        scorer_factory=scorer_factory,
        multiple_correct=multiple_correct,
        cases_route=routes["cases"],
        check_route=routes["check"],
        check_surface_route=routes["check_surface"],
        case_evaluation_route=routes["case_evaluation"],
        aggregate_route=routes["aggregate"],
    )
    # WHY revision-compared, not presence-compared: re-assembling the identical
    # board is harmless (tests do it), but a copy-pasted board module that kept
    # the donor's key would resolve the WRONG board's routes at install time —
    # its differing pins give it a different revision, so it is refused here.
    existing: ImportedBoard | None = _BOARDS_BY_ID.get(benchmark_id)
    if existing is not None and existing.benchmark.revision != revision:
        raise ValueError(
            f"benchmark id {benchmark_id!r} is already assembled with a different "
            f"revision — duplicate board_key?"
        )
    _BOARDS_BY_ID[benchmark_id] = board
    return board


#: Board-module installers resolve their board here at install time —
#: `Benchmark.install` is a plain callable created BEFORE the ImportedBoard exists,
#: so it looks its board up by id instead of capturing a forward reference.
_BOARDS_BY_ID: dict[str, ImportedBoard] = {}


def install_imported_board(node: Url4Node, assets: Path, benchmark_id: str) -> None:
    """Register one imported board's routes — called by the board module's installer.

    WHY the indirection: the deployment conformance rule wants each board's installer
    defined in the module that exports its ``ASSET_BUNDLE_ID``; this function is the
    shared kitchen those thin wrappers delegate to.
    """

    board: ImportedBoard = _BOARDS_BY_ID[benchmark_id]
    root: Path = assets / benchmark_id
    routes: dict[str, str] = {
        "cases": board.cases_route,
        "check": board.check_route,
        "check_surface": board.check_surface_route,
        "case_evaluation": board.case_evaluation_route,
        "aggregate": board.aggregate_route,
    }
    if routes["cases"] not in getattr(node, "_data", {}):
        node.data(routes["cases"], _cases(root), media_type="application/json")
    installed = frozenset(node.processor_routes())
    endpoints: list[tuple[str, Callable[[Request], str]]] = [
        (routes["check"], _check(root)),
        (
            routes["case_evaluation"],
            attempt_records_endpoint(
                label=f"{board.benchmark.title} Case evaluation",
                item_name="Attempt",
                bind=bind_case_evaluation,
            ),
        ),
        (
            routes["aggregate"],
            aggregate_endpoint(
                label=board.benchmark.title,
                available_case_count=board.benchmark.case_count,
                aggregate=_aggregate(board, root),
            ),
        ),
    ]
    if board.benchmark.check_surface is not None:
        # Spec §4 — the SAME scorer, second office hour: the advertised
        # check-surface port for the corrective loop.
        endpoints.append((routes["check_surface"], _check_surface(board, root)))
    for route, handler in endpoints:
        if route not in installed:
            node.endpoint(route)(handler)


def _build(routes: Mapping[str, str], available: int) -> Callable[[int], Node]:
    """The canonical one-invocation expression — one answer per Case, graded once."""

    def build(case_count: int) -> Node:
        candidate_invocation = candidate(
            "$item.input",
            web_search=_CANDIDATE_WEB_SEARCH,
            case_id="$item.id",
            case_position="$item._sf_case_position",
            case_count="$item._sf_case_count",
        )
        checked = expr(
            src(
                RelExpr(
                    path=routes["check"],
                    context="$candidate_invocation",
                    intent=Text("$item.case_id"),
                ),
                name="record",
                weight=0.0,
            ),
            src(
                RelExpr(
                    path=routes["case_evaluation"],
                    context=render(struct({"attempt_1": "$record"})),
                    intent=Text("$item.case_id"),
                ),
                name="case_evaluation",
                weight=0.0,
            ),
            intent=Text("$case_evaluation"),
        )
        return build_evaluation_protocol(
            cases_route=routes["cases"],
            case_evaluation=preserve_candidate_outcome(
                candidate_invocation=candidate_invocation,
                grading=checked,
                case_id="$item.id",
            ),
            selected_case_count=case_count,
            available_case_count=available,
            aggregate_route=routes["aggregate"],
        )

    return build


def _cases(root: Path) -> Callable[[], str]:
    @observe_stage(BenchmarkStage.CASE_LOADING)
    def cases() -> str:
        try:
            return (root / "cases.json").read_text(encoding="utf-8")
        except OSError as exc:
            raise _unavailable(f"imported board cases are unavailable: {exc}") from exc

    return cases


def _check(root: Path) -> Callable[[Request], str]:
    """Record the Candidate's attempt verbatim — grading waits for the aggregate.

    WHY no grading here: the scorer is the aggregate's job (through the shim), so a
    scorer bug can never poison the collected row — the Candidate's answer is always
    preserved for re-grading.
    """

    @observe_stage(BenchmarkStage.GRADING_CHECK)
    def check(request: Request) -> str:
        try:
            case_id: int = positive_case_id(request.intent)
            if _target(root, case_id) is None:
                # Refuse early: an attempt recorded against an unusable target
                # could never be graded — fail the call, not the aggregate later.
                raise ValueError(f"the private target record for case {case_id} is unusable")
            answer = candidate_answer(request.context)
        except (OSError, TypeError, ValueError) as exc:
            raise _unavailable(str(exc)) from exc
        record: dict[str, Any] = {
            "schema": CHECK_SCHEMA,
            "case_id": case_id,
            "attempt": 1,
            "answer": answer.text,
            "status": answer.status,
            "refusal": answer.refusal,
            "finish_reason": answer.finish_reason,
            "execution": (
                None if answer.execution is None else answer.execution.model_dump(by_alias=True)
            ),
            # INVARIANT: absence stays absence (OME-843).
            **(
                {}
                if answer.operations is None
                else {
                    "operations": [
                        operation.model_dump(by_alias=True) for operation in answer.operations
                    ]
                }
            ),
        }
        return compact_json(record)

    return check


def _check_surface(board: ImportedBoard, root: Path) -> Callable[[Request], str]:
    @observe_stage(BenchmarkStage.GRADING_CHECK)
    def check_surface(request: Request) -> str:
        if request.intent == "feedback":
            return _surface_feedback(request.context)
        if request.intent != "check":
            raise _unavailable(f"unsupported check-surface operation {request.intent!r}")
        try:
            payload = json_object(request.context, "imported board check surface")
            if set(payload) != {"input", "invocation"}:
                raise ValueError("check surface context must carry exactly input and invocation")
            input_text, invocation = payload["input"], payload["invocation"]
            if not isinstance(input_text, str) or not isinstance(invocation, str):
                raise ValueError("check surface input and invocation must be text")
            verdict = check_surface_verdict(
                board, root, input_text=input_text, invocation=invocation
            )
        except (OSError, TypeError, ValueError) as exc:
            raise _unavailable(str(exc)) from exc
        return compact_json(verdict)

    return check_surface


def _surface_feedback(record_json: object) -> str:
    record = json_object(record_json, "imported board check-surface feedback")
    if record.get("schema") != CHECK_SURFACE_SCHEMA:
        raise _unavailable(f"feedback input must be a {CHECK_SURFACE_SCHEMA} check-surface record")
    feedback = record.get("feedback")
    if not isinstance(feedback, str):
        raise _unavailable("check-surface record feedback must be text")
    return feedback


def check_surface_verdict(
    board: ImportedBoard, root: Path, *, input_text: str, invocation: str
) -> dict[str, Any]:
    """Run the board's own scorer mid-run — the §4 dual registration, second office.

    Input-addressed (the OME-796 port rule): a black-box ``$candidate`` only ever sees
    ``$input``, so the case resolves by exact prompt text. The verdict record is the
    sealed-envelope boundary — it carries pass/fail and sanitized feedback, NEVER the
    target or the scorer's explanation (which may quote it).

    AIDEV-NOTE: each call re-reads cases.json (linear scan) and rebuilds the
    ScoredPath + scorer + a fresh executor — fine at proof-board scale, but cache a
    per-root case→id index and the scored path before a bulk import lands.
    """

    case_id: int = _case_by_input(root, input_text)
    material: Mapping[str, Any] | None = _target(root, case_id)
    if material is None:
        # INVARIANT: failure wording is this plugin's published voice — refuse
        # here, or the shim's internal TypeError vocabulary reaches the candidate.
        raise ValueError(_FAILURE_MESSAGES["missing_target_asset"])
    answer: str = candidate_answer(invocation).text
    outcome: CaseGradeOutcome = _run_sync(
        board.scored_path().grade_case(
            GradeRequest(
                case_id=case_id,
                input=TextPayload(text=input_text),
                answer=TextPayload(text=answer),
                row={},
                material=material,
            )
        )
    )
    if outcome.failure_code is not None:
        # .get(code, code): an unknown future shim code stays a clean refusal,
        # never a KeyError swallowing the real cause.
        raise ValueError(_FAILURE_MESSAGES.get(outcome.failure_code, outcome.failure_code))
    assert outcome.score is not None
    passed: bool = outcome.score >= 1.0
    return {
        "schema": CHECK_SURFACE_SCHEMA,
        "passed": passed,
        "satisfaction": outcome.score,
        "feedback": "" if passed else _CHECK_FEEDBACK,
        "answer": answer,
        "invocation": invocation,
    }


def board_aggregate(
    board: ImportedBoard,
    raw_rows: str,
    root: Path,
    *,
    case_ids: tuple[int, ...],
) -> dict[str, Any]:
    """Score every selected Case on the shared spine, then mean accuracy."""

    return board.scored_path().aggregate(
        raw_rows,
        benchmark_id=board.benchmark.id,
        benchmark_revision=board.benchmark.revision,
        selected_cases=read_selected_cases(
            root,
            case_ids,
            benchmark_label=board.benchmark.title,
            error_type=AggregateError,
        ),
        grading_material=lambda case_id: _target(root, case_id),
        scorer=_accuracy,
    )


def _aggregate(board: ImportedBoard, root: Path) -> Callable[[str, int], dict[str, Any]]:
    def aggregate_handler(case_evaluations: str, selected_case_count: int) -> dict[str, Any]:
        return board_aggregate(
            board, case_evaluations, root, case_ids=tuple(range(1, selected_case_count + 1))
        )

    return aggregate_handler


def _decode(grading: object, expected_case_id: int) -> dict[str, Any]:
    """Validate the envelope, then hoist attempt 1 into the spine's candidate shape."""

    envelope: dict[str, Any] = decode_case_evaluation(grading, expected_case_id)
    attempt: Mapping[str, Any] = envelope["attempts"][0]
    return {
        "case": {
            "status": attempt.get("status"),
            "output": attempt.get("answer"),
            "finish_reason": attempt.get("finish_reason"),
            "refusal": attempt.get("refusal"),
            "execution": attempt.get("execution"),
            "operations": attempt.get("operations"),
            "metadata": {},
        },
        "attempt": dict(attempt),
    }


def _target(root: Path, case_id: int) -> Mapping[str, Any] | None:
    """Read one Case's private target record; ``None`` when the asset is unusable."""

    try:
        decoded: object = json.loads(
            (root / "targets" / f"{case_id}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    if not isinstance(decoded, Mapping) or "target" not in decoded:
        return None
    return dict(decoded)


def _case_by_input(root: Path, prompt: str) -> int:
    """Resolve the case whose baked prompt is exactly ``prompt`` (prompts are unique)."""

    try:
        cases: object = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"imported board cases are unavailable: {exc}") from None
    if not isinstance(cases, list):
        raise ValueError("imported board cases must be a JSON array")
    matches: list[Any] = [
        case.get("id") for case in cases if isinstance(case, dict) and case.get("input") == prompt
    ]
    if len(matches) != 1 or not isinstance(matches[0], int):
        raise ValueError("the check surface input must match exactly one case")
    return matches[0]


def _accuracy(cases: Sequence[CaseResult]) -> CandidateScore:
    """Mean score over the graded Cases — the imported single-shot reduction."""

    values: list[float] = [
        float(case.grade.score)
        for case in cases
        if case.grade is not None and case.grade.score is not None
    ]
    if not values:  # pragma: no cover - a Benchmark always selects one Case
        raise AssertionError("an imported board's scorer requires at least one scored Case")
    return CandidateScore(
        score=round(sum(values) / len(values), 4),
        metrics={
            "correct": sum(1 for value in values if value >= 1.0),
            "scored_cases": len(values),
        },
    )


def _run_sync[T](coroutine: Awaitable[T]) -> T:
    """Drive the async shim from a sync route handler (the spine's own pattern).

    WHY a verbatim copy of spine ``scored._run_sync`` instead of an import: it is
    private there, and acceptance §8.2 demands ZERO spine edits in this ticket —
    exporting it is a one-line core follow-up when a third caller appears.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_awaited(coroutine))
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _awaited(coroutine)).result()


async def _awaited[T](coroutine: Awaitable[T]) -> T:
    return await coroutine


__all__ = [
    "AggregateError",
    "ImportedBoard",
    "board_aggregate",
    "install_imported_board",
    "single_shot_board",
]
