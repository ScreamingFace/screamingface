from __future__ import annotations

import json
from pathlib import Path

import nbformat

from workbench.bundle import write_bundle
from workbench.evidence import Hop, TraceChain
from workbench.redaction import redact
from workbench.runner import NotebookRun

JWT = "eyJhbGciOi.eyJleHAiOjF9.c2ln"
KEY = "sk-or-v1-abcdefghijklmnop0123"
TID = "t" * 32


def _run(
    text: str, *, result: dict[str, object] | None = None, error: str | None = None
) -> NotebookRun:
    cell = nbformat.v4.new_code_cell("print(KEY)")
    cell.outputs = [nbformat.v4.new_output("stream", name="stdout", text=text)]
    return NotebookRun(nbformat.v4.new_notebook(cells=[cell]), result, error)


def test_redaction_covers_keys_jwts_and_bearer_headers() -> None:
    text = f"key {KEY} tok {JWT} hdr Bearer abc.def"
    out = redact(text)
    assert KEY not in out
    assert JWT not in out
    assert "abc.def" not in out
    assert out.count("[REDACTED]") == 3


def test_bundle_layout_and_secrets_stripped_from_notebook_outputs(tmp_path: Path) -> None:
    run = _run(f"{KEY}\n", result={"trace_ids": ["t"]})
    chain = TraceChain((TID,), (Hop("engine", True, (f"trace_id={TID} {JWT}",)),))

    out = write_bundle(
        tmp_path,
        target="replay",
        notebook="quickstart",
        run=run,
        chain=chain,
        passed=True,
        reasons=[],
    )

    assert out == tmp_path / "replay" / "quickstart"
    assert "sk-or-v1" not in (out / "executed.ipynb").read_text()
    assert JWT not in (out / "logs" / "engine.txt").read_text()
    trace = json.loads((out / "trace.json").read_text())
    assert trace["passed"] is True and trace["hops"][0]["name"] == "engine"
    assert trace["result"] == {"trace_ids": ["t"]}
    assert "| replay | quickstart | PASS |" in (tmp_path / "summary.md").read_text()


def test_a_bearer_header_in_an_output_leaves_a_valid_notebook(tmp_path: Path) -> None:
    """Redacting the serialised JSON with ``bearer\\s+\\S+`` would eat the closing quote."""
    run = _run('Authorization: Bearer abc.def"\n')
    chain = TraceChain((), ())

    out = write_bundle(
        tmp_path, target="replay", notebook="nb", run=run, chain=chain, passed=False, reasons=["x"]
    )

    executed = nbformat.read(out / "executed.ipynb", as_version=4)
    text = executed.cells[0].outputs[0]["text"]
    assert "abc.def" not in text and "[REDACTED]" in text


def test_secrets_in_result_error_and_reasons_are_redacted(tmp_path: Path) -> None:
    run = _run("ok\n", result={"echo": f"Bearer {JWT}"}, error=f"assert failed with {KEY}")
    chain = TraceChain((), ())

    out = write_bundle(
        tmp_path,
        target="local",
        notebook="nb",
        run=run,
        chain=chain,
        passed=False,
        reasons=[f"saw {KEY}"],
    )

    for path in (out / "trace.json", tmp_path / "summary.md"):
        body = path.read_text()
        assert KEY not in body and JWT not in body, path
    trace = json.loads((out / "trace.json").read_text())
    assert trace["error"] == "assert failed with [REDACTED]"
    assert trace["passed"] is False


def test_a_failing_run_without_a_trace_id_still_writes_every_file(tmp_path: Path) -> None:
    run = _run("boom\n", error="Traceback: band")
    out = write_bundle(
        tmp_path,
        target="replay",
        notebook="nb",
        run=run,
        chain=TraceChain((), ()),
        passed=False,
        reasons=["no trace id reported"],
    )
    assert (out / "executed.ipynb").is_file()
    assert json.loads((out / "trace.json").read_text())["trace_ids"] == []
    summary = (tmp_path / "summary.md").read_text()
    assert "| replay | nb | FAIL | — | no trace id reported |" in summary


def test_summary_accumulates_rows_and_escapes_pipes(tmp_path: Path) -> None:
    for name in ("a", "b"):
        write_bundle(
            tmp_path,
            target="replay",
            notebook=name,
            run=_run("ok\n"),
            chain=TraceChain((), ()),
            passed=True,
            reasons=["x|y"],
        )
    summary = (tmp_path / "summary.md").read_text()
    assert summary.count("| target |") == 1
    assert "| replay | a | PASS | — | x\\|y |" in summary
    assert "| replay | b | PASS |" in summary


def test_a_result_matrix_is_written_redacted_with_capped_answers(tmp_path: Path) -> None:
    """Image input matrix spec §3.5: ``matrix.json`` holds one row per cell, answers ≤ 200
    characters, redacted like every other sink (a model may echo anything)."""
    rows = [
        {"path": "url4", "model": "m", "observed": "answered", "answer": "7392 " + "x" * 400},
        {"path": "url4", "model": "m", "observed": "wrong", "answer": f"saw {KEY}"},
        {"path": "benchmark", "model": "m", "observed": "refused", "answer": None},
    ]
    run = _run("ok\n", result={"trace_ids": [TID], "matrix": rows})

    out = write_bundle(
        tmp_path,
        target="local",
        notebook="image_input_matrix",
        run=run,
        chain=TraceChain((), ()),
        passed=True,
        reasons=[],
    )

    body = (out / "matrix.json").read_text()
    assert KEY not in body
    matrix = json.loads(body)
    assert [row["observed"] for row in matrix] == ["answered", "wrong", "refused"]
    assert len(matrix[0]["answer"]) == 200 and matrix[0]["answer"].startswith("7392 ")
    assert "[REDACTED]" in matrix[1]["answer"]
    assert matrix[2]["answer"] is None


def test_no_matrix_file_without_a_result_matrix(tmp_path: Path) -> None:
    out = write_bundle(
        tmp_path,
        target="replay",
        notebook="quickstart",
        run=_run("ok\n", result={"trace_ids": [TID]}),
        chain=TraceChain((), ()),
        passed=True,
        reasons=[],
    )
    assert not (out / "matrix.json").exists()


def test_a_malformed_matrix_is_kept_as_reported_not_dropped(tmp_path: Path) -> None:
    """A notebook bug that reports a non-list still leaves evidence; ``check_result`` and the
    notebook's own verdict decide the outcome, the bundle only records."""
    out = write_bundle(
        tmp_path,
        target="local",
        notebook="image_input_matrix",
        run=_run("ok\n", result={"trace_ids": [TID], "matrix": f"oops {KEY}"}),
        chain=TraceChain((), ()),
        passed=False,
        reasons=["x"],
    )
    body = (out / "matrix.json").read_text()
    assert KEY not in body and json.loads(body) == "oops [REDACTED]"
