"""The run-scoped Case-result store and the case-execution route's reference rows.

FEATURE: memory fix 2 for the MMLU-Pro ``memory_budget_exceeded`` kill. Each Case's
case-execution envelope is parked as it finishes, and the per-Case fan-out carries only a
~100 B reference to it (spec ``docs/spec/2026-11-05-case-result-store.md``).

INVARIANT under test: a reference resolves to exactly the envelope the route validated, or it
fails closed with the typed ``CaseResultStoreError``. It never resolves to another row or to
an empty one.
"""

from __future__ import annotations

import json
import stat
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.case_result_store import (
    CaseResultStore,
    CaseResultStoreError,
    binding_case_results,
    bound_case_results,
)
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.graded_answer import (
    CASE_EXECUTION_REF_SCHEMA,
    GRADED_ANSWER_SCHEMA,
    _graded_answer_route,
    graded_answer,
    graded_answer_payload,
)
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from url4.core.errors import ResolutionError
from url4.peer.server import Request
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import LogData

_ROUTE = "/benchmarks/case-execution"


def _invocation(output: str = "ANSWER: B") -> str:
    return encode_candidate_invocation(output, "stop", None)


def _context(case_id: int, grading: Sequence[object], output: str = "ANSWER: B") -> str:
    return json.dumps(
        {"case_id": case_id, "candidate_invocation": _invocation(output), "grading": grading}
    )


def _route(context: str) -> str:
    return _graded_answer_route(Request(_ROUTE, context, "", {}))


# ── the store ────────────────────────────────────────────────────────────────


def test_append_then_read_returns_each_record_by_its_own_key(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    keys = [store.append({"case_id": index, "body": "x" * index}) for index in range(1, 51)]
    assert len(set(keys)) == 50
    assert len(store) == 50
    # Read out of order: the index maps each key to its own row.
    for index in (37, 1, 50, 2):
        assert store.read(keys[index - 1]) == {"case_id": index, "body": "x" * index}
    store.close()


def test_rows_are_ndjson_at_the_recorded_offsets(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    first = store.append({"a": 1})
    second = store.append({"b": "é"})
    data = store.path.read_bytes()
    # One compact JSON object per line, UTF-8, in append order.
    assert data == b'{"a":1}\n{"b":"\xc3\xa9"}\n'
    assert store.read(second) == {"b": "é"}
    assert store.read(first) == {"a": 1}
    store.close()


def test_the_store_directory_is_private_to_the_process_user(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    mode = stat.S_IMODE(store.path.parent.stat().st_mode)
    assert mode == 0o700
    store.close()


def test_two_stores_never_share_a_file_or_a_key_space(tmp_path: Path) -> None:
    first = CaseResultStore.create(tmp_path)
    second = CaseResultStore.create(tmp_path)
    key = first.append({"run": 1})
    assert first.path != second.path
    # The same key in another run's store is unknown there: fail closed, not a foreign row.
    with pytest.raises(CaseResultStoreError, match="unknown"):
        second.read(key)
    first.close()
    second.close()


def test_an_unknown_key_fails_closed(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    store.append({"a": 1})
    with pytest.raises(CaseResultStoreError, match="unknown"):
        store.read("999")
    store.close()


def test_a_tampered_row_fails_closed_on_its_digest(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    key = store.append({"answer": "B"})
    data = store.path.read_bytes()
    store.path.write_bytes(data.replace(b'"B"', b'"C"'))
    with pytest.raises(CaseResultStoreError, match="corrupt"):
        store.read(key)
    store.close()


def test_a_truncated_file_fails_closed(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    key = store.append({"answer": "B" * 100})
    store.path.write_bytes(store.path.read_bytes()[:20])
    with pytest.raises(CaseResultStoreError, match="corrupt"):
        store.read(key)
    store.close()


def test_a_missing_file_fails_closed(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    key = store.append({"a": 1})
    store.path.unlink()
    with pytest.raises(CaseResultStoreError):
        store.read(key)
    store.close()


def test_close_deletes_the_rows_and_is_idempotent(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    key = store.append({"a": 1})
    directory = store.path.parent
    store.close()
    store.close()
    assert not directory.exists()
    assert list(tmp_path.iterdir()) == []
    # A closed store answers nothing: fail closed, never an empty row.
    with pytest.raises(CaseResultStoreError, match="closed"):
        store.read(key)
    with pytest.raises(CaseResultStoreError, match="closed"):
        store.append({"b": 2})


def test_the_error_is_a_value_error_so_existing_contract_paths_catch_it() -> None:
    assert issubclass(CaseResultStoreError, ValueError)


def test_the_binding_never_leaks_past_its_block(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    assert bound_case_results() is None
    with binding_case_results(store):
        assert bound_case_results() is store
    assert bound_case_results() is None
    store.close()


# ── the route and its reader ───────────────────────────────────────────────


def test_unbound_the_route_returns_todays_envelope_byte_for_byte() -> None:
    grading = [{"attempts": [{"answer": "ANSWER: B"}]}]
    out = _route(_context(3, grading))
    expected = graded_answer_payload(3, _invocation(), grading)
    assert json.loads(out) == expected
    assert json.loads(out)["schema"] == GRADED_ANSWER_SCHEMA


def test_bound_the_route_returns_a_small_reference_and_parks_the_envelope(
    tmp_path: Path,
) -> None:
    grading = [{"attempts": [{"answer": "ANSWER: B", "pad": "p" * 5000}]}]
    store = CaseResultStore.create(tmp_path)
    with binding_case_results(store):
        out = _route(_context(7, grading))
        row = json.loads(out)
        assert set(row) == {"schema", "case_id", "key"}
        assert row["schema"] == CASE_EXECUTION_REF_SCHEMA
        assert row["case_id"] == 7
        assert len(out.encode()) < 120
        outcome = graded_answer(row)
        # The same outcome the inline envelope decodes to.
        assert outcome.case_id == 7
        assert outcome.error is None
        assert outcome.grading == grading[0]
        # A reference arriving as JSON text resolves the same way.
        assert graded_answer(out).grading == grading[0]
    store.close()


def test_a_graded_row_is_parked_without_the_duplicate_candidate_invocation(
    tmp_path: Path,
) -> None:
    grading = [{"attempts": [{"answer": "ANSWER: B"}]}]
    store = CaseResultStore.create(tmp_path)
    with binding_case_results(store):
        row = json.loads(_route(_context(1, grading)))
    parked = store.read(row["key"])
    assert "candidate_invocation" not in parked
    assert parked == {"schema": GRADED_ANSWER_SCHEMA, "case_id": 1, "grading": grading}
    store.close()


def test_a_grading_error_row_keeps_its_candidate_answer(tmp_path: Path) -> None:
    grading = [{"error": {"kind": "ResolutionError", "message": "judge down"}}]
    store = CaseResultStore.create(tmp_path)
    with binding_case_results(store):
        row = json.loads(_route(_context(2, grading, output="ANSWER: J")))
        outcome = graded_answer(row)
    assert outcome.error == grading[0]["error"]
    assert outcome.candidate is not None
    assert outcome.candidate.text == "ANSWER: J"
    store.close()


def test_a_reference_with_no_store_bound_fails_closed(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    with binding_case_results(store):
        row = json.loads(_route(_context(1, [{"ok": True}])))
    with pytest.raises(CaseResultStoreError, match="no Case-result store"):
        graded_answer(row)
    store.close()


def test_a_reference_claiming_another_case_fails_closed(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    with binding_case_results(store):
        row = json.loads(_route(_context(1, [{"ok": True}])))
        with pytest.raises(CaseResultStoreError, match="another Case"):
            graded_answer({**row, "case_id": 2})
    store.close()


def test_a_malformed_reference_is_refused(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    with binding_case_results(store):
        with pytest.raises(ValueError):
            graded_answer({"schema": CASE_EXECUTION_REF_SCHEMA, "case_id": 1})
        with pytest.raises(ValueError):
            graded_answer({"schema": CASE_EXECUTION_REF_SCHEMA, "case_id": 1, "key": 5})
    store.close()


def test_a_parked_row_with_a_foreign_shape_fails_closed(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    key = store.append({"schema": "something.else", "case_id": 1, "grading": [{}]})
    ref = {"schema": CASE_EXECUTION_REF_SCHEMA, "case_id": 1, "key": key}
    with binding_case_results(store), pytest.raises(CaseResultStoreError, match="shape"):
        graded_answer(ref)
    store.close()


def test_an_invalid_context_is_still_refused_before_anything_is_parked(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    with binding_case_results(store), pytest.raises(ResolutionError):
        _route(json.dumps({"case_id": 1, "candidate_invocation": _invocation()}))
    assert len(store) == 0
    store.close()


# ── one store per run, deleted with the run ───────────────────────────────


class _ParkingExecutor(Executor):
    """Parks one row from inside the run, as the case-execution route would."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.stores: list[CaseResultStore] = []

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        del url4, trace
        store = bound_case_results()
        assert store is not None
        self.stores.append(store)
        store.append({"case_id": 1})
        if self.fail:
            raise RuntimeError("the run failed")
        yield LogData.at("INFO", "parked")


@pytest.mark.asyncio
async def test_each_run_gets_its_own_store_and_it_is_deleted_with_the_run(
    tmp_path: Path,
) -> None:
    inner = _ParkingExecutor()
    executor = OperationCapturingExecutor(
        inner, case_results=lambda: CaseResultStore.create(tmp_path)
    )
    for _ in range(2):
        assert len([step async for step in executor.execute("'x'")]) == 1
        # Not bound outside the run's own steps.
        assert bound_case_results() is None
    first, second = inner.stores
    assert first is not second
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_failed_run_still_deletes_its_store(tmp_path: Path) -> None:
    inner = _ParkingExecutor(fail=True)
    executor = OperationCapturingExecutor(
        inner, case_results=lambda: CaseResultStore.create(tmp_path)
    )
    with pytest.raises(RuntimeError, match="the run failed"):
        _ = [step async for step in executor.execute("'x'")]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_without_a_factory_the_run_keeps_every_row_inline() -> None:
    seen: list[CaseResultStore | None] = []

    class _Probe(Executor):
        async def execute(
            self, url4: str, *, trace: TraceContext | None = None
        ) -> AsyncIterator[ExecStep]:
            del url4, trace
            seen.append(bound_case_results())
            yield LogData.at("INFO", "probed")

    _ = [step async for step in OperationCapturingExecutor(_Probe()).execute("'x'")]
    assert seen == [None]
