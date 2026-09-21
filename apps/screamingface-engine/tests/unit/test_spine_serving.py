"""The serving spine — the plumbing every deterministic board used to re-type by hand.

WHY this file exists (OME-1236): contracteval's and medxpert's `runtime.py` carried the
same seven top-level functions name-for-name, and a hand-wired slot missed in one copy
("preflight defined, exported, invoked from nowhere" — PR #865 review) surfaces only
after paid inference. These tests pin the shared core's contract so a board declaration
is structurally served: routes built from identity, preflight that cannot be forgotten,
case serving memoized only on success, and a byte-stable check-record envelope.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.evaluation import candidate_answer, compact_json
from screamingface_engine.benchmarks.spine.serving import (
    ServedBoard,
    board_aggregate,
    board_case_count,
    board_preflight,
    board_routes,
    candidate_record,
    compute_board_revision,
    install_board,
    read_asset,
    serve_cases,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

# --- toy board -------------------------------------------------------------------

_REVISION = "0123456789abcdef"


def _emit_bundle(root: Path, *, case_ids: tuple[int, ...] = (1, 2)) -> Path:
    """Bake a minimal two-file bundle: the public booklet and the private key."""

    rows = [{"id": case_id, "input": f"question {case_id}"} for case_id in case_ids]
    root.mkdir(parents=True, exist_ok=True)
    (root / "cases.json").write_text(json.dumps(rows), encoding="utf-8")
    answers = {str(case_id): {"gold": f"gold {case_id}"} for case_id in case_ids}
    (root / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    return root


def _load_answer(root: Path, case_id: int) -> Mapping[str, Any] | None:
    try:
        answers = json.loads((root / "answers.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return answers.get(str(case_id))


def _build_rows(root: Path, rows: list[Any]) -> list[dict[str, Any]]:
    return [
        {"id": int(row["id"]), "case_id": str(int(row["id"])), "input": row["input"]}
        for row in rows
    ]


def _check(root: Path):
    def check(request: Request) -> str:
        reply = candidate_answer(request.context)
        record = candidate_record(
            reply,
            schema="screamingface.toy-check.v1",
            case_id=int(request.intent),
            verdict={"correct": True},
            tail={"output": reply.text},
        )
        return compact_json(record)

    return check


def _bind(case_id: int, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema": "toy-case", "case_id": case_id, "attempts": attempts}


class _Reduce:
    """Records what the aggregate adapter forwards, like each board's `reducing.aggregate`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        case_evaluations: str,
        root: Path,
        *,
        benchmark_id: str,
        benchmark_revision: str,
        case_ids: tuple[int, ...],
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "case_evaluations": case_evaluations,
                "root": root,
                "benchmark_id": benchmark_id,
                "benchmark_revision": benchmark_revision,
                "case_ids": case_ids,
            }
        )
        return {"score": 1.0}


def _preflight(root: Path, case_ids: tuple[int, ...]) -> None:
    board_preflight(root, case_ids, label="Toy", load_answer=_load_answer)


def _toy_board(*, reduce: _Reduce | None = None, declared: int = 2) -> ServedBoard:
    return ServedBoard(
        benchmark_id="toy",
        label="Toy",
        revision=_REVISION,
        declared_case_count=declared,
        preflight=_preflight,
        build_rows=_build_rows,
        check=_check,
        bind_case_evaluation=_bind,
        reduce=reduce or _Reduce(),
    )


# --- routes + revision -----------------------------------------------------------


class TestBoardRoutes:
    def test_routes_carry_id_and_revision(self) -> None:
        # INVARIANT: the route layout is exam identity — every migrated board must keep
        # resolving at exactly these addresses, so the layout is pinned byte-for-byte.
        routes = board_routes("toy", _REVISION)

        assert routes.prefix == f"/benchmarks/toy/{_REVISION}"
        assert routes.cases == f"/benchmarks/toy/{_REVISION}/cases"
        assert routes.check == f"/benchmarks/toy/{_REVISION}/check"
        assert routes.case_evaluation == f"/benchmarks/toy/{_REVISION}/case-evaluation"
        assert routes.aggregate == f"/benchmarks/toy/{_REVISION}/aggregate"


class TestComputeBoardRevision:
    def test_sixteen_hex_characters(self) -> None:
        revision = compute_board_revision("a", "b", "c")

        assert len(revision) == 16
        assert set(revision) <= set("0123456789abcdef")

    def test_any_changed_part_changes_the_revision(self) -> None:
        # WHY: a changed prompt or pin is a changed exam and must re-address every route.
        assert compute_board_revision("a", "b") != compute_board_revision("a", "c")

    def test_parts_are_joined_not_concatenated(self) -> None:
        # WHY newline joining is pinned: ("ab","c") and ("a","bc") must not collide,
        # and the join rule participates in every existing board's baked revision.
        assert compute_board_revision("ab", "c") != compute_board_revision("a", "bc")


# --- the check-record envelope ---------------------------------------------------


class TestCandidateRecord:
    def test_field_order_is_byte_stable(self) -> None:
        # INVARIANT: the record's field ORDER is part of the served bytes — migrated
        # boards must produce byte-identical check records through this helper.
        reply = candidate_answer(encode_candidate_invocation("hello", "stop", None))

        record = candidate_record(
            reply,
            schema="s",
            case_id=3,
            verdict={"correct": False, "jaccard": 0.5},
            tail={"output": "hello", "reasoning": "because"},
        )

        assert list(record) == [
            "schema",
            "case_id",
            "attempt",
            "correct",
            "jaccard",
            "status",
            "refusal",
            "finish_reason",
            "output",
            "reasoning",
            "execution",
        ]
        assert record["schema"] == "s"
        assert record["case_id"] == 3
        assert record["attempt"] == 1
        assert record["status"] == "completed"
        assert record["execution"] is None

    def test_operations_appear_only_when_present(self) -> None:
        reply = candidate_answer(encode_candidate_invocation("hi", "stop", None))

        record = candidate_record(reply, schema="s", case_id=1, verdict={}, tail={})

        assert "operations" not in record


# --- preflight -------------------------------------------------------------------


class TestBoardPreflight:
    def test_passes_on_a_complete_bundle(self, tmp_path: Path) -> None:
        root = _emit_bundle(tmp_path / "toy")

        board_preflight(root, (1, 2), label="Toy", load_answer=_load_answer)

    def test_missing_cases_file_fails(self, tmp_path: Path) -> None:
        root = tmp_path / "toy"
        root.mkdir()

        with pytest.raises(ResolutionError, match="cases.json missing"):
            board_preflight(root, (), label="Toy", load_answer=_load_answer)

    def test_missing_answer_record_fails_before_any_paid_call(self, tmp_path: Path) -> None:
        root = _emit_bundle(tmp_path / "toy", case_ids=(1,))

        with pytest.raises(ResolutionError, match="answer record for case 9"):
            board_preflight(root, (9,), label="Toy", load_answer=_load_answer)

    def test_problem_list_is_capped_at_eight(self, tmp_path: Path) -> None:
        # WHY the cap: the message travels in a public failure row; an exam with
        # thousands of broken cases must not ship a megabyte of diagnostics.
        root = _emit_bundle(tmp_path / "toy", case_ids=(1,))

        with pytest.raises(ResolutionError) as caught:
            board_preflight(root, tuple(range(10, 30)), label="Toy", load_answer=_load_answer)

        assert str(caught.value).count("answer record") == 8

    def test_board_error_class_is_used(self, tmp_path: Path) -> None:
        # Per-board deviation preserved: medxpert raises benchmark_definition_error,
        # contracteval benchmark_unavailable — the core takes the board's factory.
        def custom(detail: str) -> ResolutionError:
            return ResolutionError(detail, code="custom_code", permanent=True)

        root = tmp_path / "toy"
        root.mkdir()

        with pytest.raises(ResolutionError) as caught:
            board_preflight(root, (), label="Toy", load_answer=_load_answer, error=custom)

        assert caught.value.code == "custom_code"


# --- case serving ----------------------------------------------------------------


class TestServeCases:
    def test_serves_compact_rows_from_the_board_builder(self, tmp_path: Path) -> None:
        root = _emit_bundle(tmp_path / "toy")
        cases = serve_cases(root, _toy_board())

        served = json.loads(cases())

        assert served == [
            {"id": 1, "case_id": "1", "input": "question 1"},
            {"id": 2, "case_id": "2", "input": "question 2"},
        ]
        # INVARIANT: served bytes are compact JSON — the payload participates in
        # recorded protocol, so formatting is not free to drift.
        assert cases() == json.dumps(served, ensure_ascii=False, separators=(",", ":"))

    def test_a_broken_bundle_refails_on_every_call(self, tmp_path: Path) -> None:
        # INVARIANT: only a SUCCESSFUL preflight is remembered — a bundle broken at
        # first call must not be served from a cache primed before the failure.
        root = _emit_bundle(tmp_path / "toy")
        (root / "answers.json").unlink()
        cases = serve_cases(root, _toy_board())

        with pytest.raises(ResolutionError):
            cases()
        with pytest.raises(ResolutionError):
            cases()

    def test_preflight_runs_once_after_success(self, tmp_path: Path) -> None:
        root = _emit_bundle(tmp_path / "toy")
        calls: list[int] = []

        def counting_load(bundle_root: Path, case_id: int) -> Mapping[str, Any] | None:
            calls.append(case_id)
            return _load_answer(bundle_root, case_id)

        def counting_preflight(bundle_root: Path, case_ids: tuple[int, ...]) -> None:
            board_preflight(bundle_root, case_ids, label="Toy", load_answer=counting_load)

        board = ServedBoard(
            benchmark_id="toy",
            label="Toy",
            revision=_REVISION,
            declared_case_count=2,
            preflight=counting_preflight,
            build_rows=_build_rows,
            check=_check,
            bind_case_evaluation=_bind,
            reduce=_Reduce(),
        )
        cases = serve_cases(root, board)

        cases()
        first_round = len(calls)
        cases()

        assert first_round == 2
        assert len(calls) == first_round

    def test_missing_cases_file_is_a_bounded_failure(self, tmp_path: Path) -> None:
        root = tmp_path / "toy"
        root.mkdir()
        cases = serve_cases(root, _toy_board())

        with pytest.raises(ResolutionError, match="Toy cases"):
            cases()


# --- case count + asset reads ----------------------------------------------------


class TestBoardCaseCount:
    def test_counts_the_baked_booklet(self, tmp_path: Path) -> None:
        root = _emit_bundle(tmp_path / "toy", case_ids=(1, 2, 3))

        assert board_case_count(root, declared=99) == 3

    def test_declared_count_stands_in_when_assets_are_absent(self, tmp_path: Path) -> None:
        # WHY: install happens on a resource-only control plane where assets may be
        # absent; preflight — not this count — is what refuses a run it cannot serve.
        assert board_case_count(tmp_path / "missing", declared=99) == 99


class TestReadAsset:
    def test_reads_text(self, tmp_path: Path) -> None:
        (tmp_path / "f.txt").write_text("body", encoding="utf-8")

        assert read_asset(tmp_path / "f.txt", "Toy cases") == "body"

    def test_missing_file_is_a_bounded_failure(self, tmp_path: Path) -> None:
        with pytest.raises(ResolutionError, match="Toy cases unavailable"):
            read_asset(tmp_path / "missing.txt", "Toy cases")


# --- aggregate adapter -----------------------------------------------------------


class TestBoardAggregate:
    def test_forwards_identity_and_the_selected_case_ids(self, tmp_path: Path) -> None:
        # INVARIANT: case_ids are 1..selected — the reducer scores exactly the exam
        # that was selected, and identity (id + revision) rides into the report.
        reduce = _Reduce()
        root = _emit_bundle(tmp_path / "toy")
        handler = board_aggregate(root, _toy_board(reduce=reduce))

        result = handler("[]", 2)

        assert result == {"score": 1.0}
        assert reduce.calls == [
            {
                "case_evaluations": "[]",
                "root": root,
                "benchmark_id": "toy",
                "benchmark_revision": _REVISION,
                "case_ids": (1, 2),
            }
        ]


# --- install ---------------------------------------------------------------------


class TestInstallBoard:
    def test_registers_every_route_the_expression_references(self, tmp_path: Path) -> None:
        # INVARIANT: a registered declaration is structurally served — no hand-wired
        # slot can be forgotten, which is the bug class this module deletes.
        root = _emit_bundle(tmp_path / "toy")
        node = Url4Node("test")
        board = _toy_board()

        install_board(node, root, board)

        routes = board_routes("toy", _REVISION)
        assert routes.cases in getattr(node, "_data", {})
        installed = frozenset(node.processor_routes())
        assert routes.check in installed
        assert routes.case_evaluation in installed
        assert routes.aggregate in installed

    def test_reinstall_is_idempotent(self, tmp_path: Path) -> None:
        root = _emit_bundle(tmp_path / "toy")
        node = Url4Node("test")
        board = _toy_board()

        install_board(node, root, board)
        install_board(node, root, board)

        assert frozenset(node.processor_routes()) >= {
            board_routes("toy", _REVISION).check,
            board_routes("toy", _REVISION).aggregate,
        }
