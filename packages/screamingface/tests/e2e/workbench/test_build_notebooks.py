from __future__ import annotations

import json
from typing import Any

import nbformat
import pytest
from harness._gating import GOLDENS_DIR
from harness.goldens import GoldenReport, build_candidate, load_golden

import screamingface as sf
from workbench.build_notebooks import (
    NOTEBOOK_DIR,
    _code,  # pyright: ignore[reportPrivateUsage]
    _notebook,  # pyright: ignore[reportPrivateUsage]
    build,
    main,
    render_golden_candidate,
    serialize,
)
from workbench.image_matrix import Cell, verdict
from workbench.image_notebook import (
    Budget,
    coverage_failures,
    html_table,
    matrix_rows,
    reported_trace_ids,
    upstream_calls,
)
from workbench.redaction import redact
from workbench.runner import RESULT_PREFIX


@pytest.mark.parametrize("path", sorted(GOLDENS_DIR.glob("*.golden.json")), ids=lambda p: p.name)
def test_rendered_golden_recipe_equals_the_harness_builder(path) -> None:
    golden = load_golden(path)
    namespace: dict[str, Any] = {}
    exec("import screamingface as sf\n" + render_golden_candidate(golden), namespace)
    assert namespace["candidate"] == build_candidate(golden)


def test_committed_notebooks_match_the_builder_and_are_output_free() -> None:
    built = build()
    assert "quickstart" in built
    for stem, nb in built.items():
        committed = (NOTEBOOK_DIR / f"{stem}.ipynb").read_text(encoding="utf-8")
        assert committed == serialize(nb), f"{stem}.ipynb is stale; run build_notebooks.py"
        for cell in nbformat.reads(committed, as_version=4).cells:
            assert not cell.get("outputs"), f"{stem}.ipynb has committed outputs"


def test_every_notebook_has_parameters_result_and_target_metadata() -> None:
    for stem, nb in build().items():
        tags = [t for c in nb.cells for t in c.metadata.get("tags", [])]
        assert "parameters" in tags and "workbench-result" in tags, stem
        assert nb.metadata["workbench"]["targets"], stem
        # Every notebook reports trace ids; a notebook may declare more (image_input_matrix).
        assert "trace_ids" in nb.metadata["workbench"]["required_result"], stem
    assert build()["quickstart"].metadata["workbench"]["required_result"] == ["trace_ids"]


def test_every_code_cell_compiles() -> None:
    for stem, nb in build().items():
        for i, cell in enumerate(nb.cells):
            if cell.cell_type == "code":
                compile(cell.source, f"{stem}[{i}]", "exec")


def test_rebuild_is_byte_identical() -> None:
    first = {stem: serialize(nb) for stem, nb in build().items()}
    second = {stem: serialize(nb) for stem, nb in build().items()}
    assert first == second


def test_check_mode_passes_on_committed_notebooks_and_fails_on_drift(tmp_path) -> None:
    assert main(["--check"]) == 0
    for stem in build():
        (tmp_path / f"{stem}.ipynb").write_text("stale", encoding="utf-8")
    assert main(["--check", "--out", str(tmp_path)]) == 1
    assert main(["--out", str(tmp_path)]) == 0
    assert main(["--check", "--out", str(tmp_path)]) == 0


def test_model_golden_and_long_strings_round_trip() -> None:
    ifeval = load_golden(GOLDENS_DIR / "ifeval.golden.json").model_dump(by_alias=True)
    for field in ("member_specs", "judge_spec", "max_rounds"):
        ifeval.pop(field)
    golden = GoldenReport.model_validate(
        ifeval | {"kind": "model", "models": ["openrouter/microsoft/phi-4"]}
    )
    namespace: dict[str, Any] = {}
    exec("import screamingface as sf\n" + render_golden_candidate(golden), namespace)
    assert namespace["candidate"] == build_candidate(golden)

    prompt = "line one\nline\ttwo  " + "word " * 40 + "x" * 90
    looped = load_golden(GOLDENS_DIR / "ifeval.golden.json")
    spec = looped.member_specs[0].model_copy(update={"prompt": prompt})
    long = looped.model_copy(update={"member_specs": (spec, looped.member_specs[1])})
    namespace = {}
    exec("import screamingface as sf\n" + render_golden_candidate(long), namespace)
    assert namespace["candidate"].members[0].prompt == prompt


def test_the_result_cell_runs_before_any_assertion() -> None:
    """Review Focus 1: a failing assert must still leave trace ids in the bundle, so the
    ``workbench-result`` cell runs before every cell that asserts."""
    for stem, nb in build().items():
        code = [c for c in nb.cells if c.cell_type == "code"]
        at = next(i for i, c in enumerate(code) if "workbench-result" in c.metadata.get("tags", []))
        assert not [c for c in code[:at] if "assert " in c.source], stem
        assert any("assert " in c.source for c in code[at + 1 :]), stem


def test_quickstart_reports_right_after_evaluate() -> None:
    cells = [c for c in build()["quickstart"].cells if c.cell_type == "code"]
    at = next(i for i, c in enumerate(cells) if "workbench-result" in c.metadata.get("tags", []))
    assert "client.evaluate(" in cells[at - 1].source


def _quickstart_code(tag: str | None = None, contains: str | None = None) -> str:
    for cell in build()["quickstart"].cells:
        if cell.cell_type != "code":
            continue
        if tag and tag in cell.metadata.get("tags", []):
            return cell.source
        if contains and contains in cell.source:
            return cell.source
    raise AssertionError(f"no quickstart cell with tag={tag} contains={contains}")


def test_quickstart_always_passes_an_explicit_scoreboard() -> None:
    """Spec §3.1: scoreboard_url is always explicit, never the SDK's hosted default."""
    client_cell = _quickstart_code(contains="sf.Client(")
    assert client_cell.count("sf.Client(") == 1
    assert "sf.Client(engine_url=ENGINE_URL, scoreboard_url=SCOREBOARD_URL)" in client_cell
    namespace: dict[str, Any] = {}
    exec(_quickstart_code(tag="parameters"), namespace)
    assert namespace["SCOREBOARD_URL"].startswith("http://127.0.0.1:")


def test_quickstart_refuses_a_missing_scoreboard() -> None:
    namespace: dict[str, Any] = {}
    exec(_quickstart_code(tag="parameters"), namespace)
    namespace["SCOREBOARD_URL"] = None
    with pytest.raises(ValueError, match="SCOREBOARD_URL"):
        exec(_quickstart_code(contains="sf.Client("), namespace)


# Gap (a) (PR #1455 review): `client.evaluate()` raising after a run was minted must still
# report that run's trace id (`sf.ScreamingFaceError.trace_id`), so the bundle correlates logs.

_TID = "4bf92f3577b34da6a3ce929d0e0e4736"
_TID2 = "00f067aa0ba902b7aaaaaaaaaaaaaaaa"


class _Candidate:
    def __init__(self, trace_id: str | None) -> None:
        self.name = "c"
        self.trace_id = trace_id
        self.run_id = "r1"
        self.score = 0.5
        self.cache_hits = 0
        self.cache_saved_cost_usd = "0"


class _Report:
    def __init__(self, *trace_ids: str | None) -> None:
        self.candidates = [_Candidate(t) for t in trace_ids]


class _Client:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome

    def evaluate(self, *_: Any, **__: Any) -> Any:
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


def _evaluate_then_report(outcome: Any, capsys: pytest.CaptureFixture[str]) -> tuple[dict, Any]:
    ns: dict[str, Any] = {"sf": sf, "json": json, "client": _Client(outcome)}
    exec(_quickstart_code(tag="parameters"), ns)
    ns["candidate"] = object()
    exec(_quickstart_code(contains="client.evaluate("), ns)
    exec(_quickstart_code(tag="workbench-result"), ns)
    (line,) = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(RESULT_PREFIX)]
    return json.loads(line[len(RESULT_PREFIX) :]), ns


def test_quickstart_reports_the_trace_id_of_a_failed_evaluate(capsys) -> None:
    error = sf.ScreamingFaceError("run failed", code="run_failed", trace_id=_TID)
    payload, ns = _evaluate_then_report(error, capsys)
    assert payload["trace_ids"] == [_TID]
    assert payload["evaluate_error"] == {"type": "ScreamingFaceError", "code": "run_failed"}
    # The notebook still fails: the captured error is re-raised by the first assert cell.
    with pytest.raises(sf.ScreamingFaceError) as raised:
        exec(_quickstart_code(contains="(result,) ="), ns)
    assert raised.value is error


def test_quickstart_reports_partial_report_ids_and_the_error_id_once(capsys) -> None:
    error = sf.ExecutionError(
        "one candidate failed",
        code="candidates_failed",
        trace_id=_TID,
        partial_report=_Report(_TID2, _TID),  # pyright: ignore[reportArgumentType]
    )
    payload, _ = _evaluate_then_report(error, capsys)
    assert payload["trace_ids"] == [_TID2, _TID]


def test_quickstart_reports_no_id_when_the_failure_minted_none(capsys) -> None:
    payload, _ = _evaluate_then_report(sf.ScreamingFaceError("refused"), capsys)
    assert payload["trace_ids"] == []
    assert payload["evaluate_error"]["type"] == "ScreamingFaceError"


def test_quickstart_success_path_reports_the_report_ids(capsys) -> None:
    payload, ns = _evaluate_then_report(_Report(_TID), capsys)
    assert payload["trace_ids"] == [_TID]
    assert payload["evaluate_error"] is None
    assert ns["evaluate_error"] is None


def test_quickstart_does_not_swallow_non_sdk_errors(capsys) -> None:
    with pytest.raises(KeyError):
        _evaluate_then_report(KeyError("bug"), capsys)


# Review finding 6: the runner fails closed on anything but one result cell printing one marker,
# so the builder guarantees that shape at build time.


def test_every_notebook_has_exactly_one_result_cell_and_one_marker() -> None:
    for stem, nb in build().items():
        tagged = [c for c in nb.cells if "workbench-result" in c.metadata.get("tags", [])]
        assert len(tagged) == 1, stem
        assert sum(c.source.count(RESULT_PREFIX) for c in nb.cells) == 1, stem
        assert tagged[0].source.count(RESULT_PREFIX) == 1, stem


@pytest.mark.parametrize(
    ("sources", "why"),
    [
        ([("print(1)", ())], "found 0"),
        ([(f"print('{RESULT_PREFIX}')", ("workbench-result",))] * 2, "found 2"),
        ([(f"print('{RESULT_PREFIX}' + '{RESULT_PREFIX}')", ("workbench-result",))], "marker"),
        ([("print(1)", ("workbench-result",))], "marker"),
        (
            [
                (f"print('{RESULT_PREFIX}')", ("workbench-result",)),
                (f"print('{RESULT_PREFIX}')", ()),
            ],
            "marker",
        ),
    ],
    ids=["no-cell", "two-cells", "two-markers", "no-marker", "marker-elsewhere"],
)
def test_the_builder_refuses_a_notebook_without_one_result_cell_and_marker(
    sources: list[tuple[str, tuple[str, ...]]], why: str
) -> None:
    cells = [_code(src, *tags) for src, tags in sources]
    with pytest.raises(ValueError, match=why):
        _notebook("bad", cells, {"targets": ["replay"], "required_result": ["trace_ids"]})


# --- image_input_matrix (image input matrix plan Task 5) ---------------------------------------


def _matrix_code(tag: str | None = None, contains: str | None = None) -> str:
    for cell in build()["image_input_matrix"].cells:
        if cell.cell_type != "code":
            continue
        if tag and tag in cell.metadata.get("tags", []):
            return cell.source
        if contains and contains in cell.source:
            return cell.source
    raise AssertionError(f"no image_input_matrix cell with tag={tag} contains={contains}")


def test_image_input_matrix_is_local_only_and_requires_the_matrix() -> None:
    nb = build()["image_input_matrix"]
    assert nb.metadata["workbench"] == {
        "targets": ["local"],
        "required_result": ["trace_ids", "matrix"],
    }
    assert (NOTEBOOK_DIR / "image_input_matrix.ipynb").is_file()
    tagged = [c for c in nb.cells if "workbench-result" in c.metadata.get("tags", [])]
    assert len(tagged) == 1


def test_image_input_matrix_parameters_are_complete_and_carry_no_secret() -> None:
    source = _matrix_code(tag="parameters")
    assert redact(source) == source
    assert "OPENROUTER_API_KEY" not in source and "sk-" not in source
    ns: dict[str, Any] = {}
    exec(source, ns)
    params = {k: v for k, v in ns.items() if not k.startswith("__")}
    assert set(params) == {
        "MODELS",
        "MEDIA",
        "PATHS",
        "FIXTURE_REF",
        "BUDGET_USD",
        "ENGINE_URL",
        "SCOREBOARD_URL",
        "GATEWAY_URL",
        "EVENTS_PATH",
    }
    assert len(params["MODELS"]) == 5
    assert params["MEDIA"] == [
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
    ]
    assert params["PATHS"] == ["url4", "benchmark"]
    assert params["FIXTURE_REF"].strip()
    assert params["BUDGET_USD"] == 0.5


def test_image_input_matrix_reads_the_key_from_env_only() -> None:
    setup = _matrix_code(contains="client.connect(")
    assert 'os.environ["OPENROUTER_API_KEY"]' in setup


def test_image_input_matrix_result_cell_reports_ids_and_matrix(capsys) -> None:
    """The result cell reports only ids that reached a model (the chain can find them) and the
    whole matrix, before the verdict cell asserts anything."""
    answered = Cell("url4", "m", "image/png", "answer", "answered", "7392", None, _TID, None, None)
    refused = Cell(
        "url4", "t", "image/png", "refuse", "refused", None, "intent_error", _TID2, None, None
    )
    ns: dict[str, Any] = {
        "json": json,
        "cells": [answered, refused],
        "reported_trace_ids": reported_trace_ids,
        "matrix_rows": matrix_rows,
    }
    exec(_matrix_code(tag="workbench-result"), ns)
    (line,) = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(RESULT_PREFIX)]
    payload = json.loads(line[len(RESULT_PREFIX) :])
    assert payload["trace_ids"] == [_TID]
    assert [row["observed"] for row in payload["matrix"]] == ["answered", "refused"]


def test_image_input_matrix_verdict_cell_fails_on_any_failure() -> None:
    wrong = Cell("url4", "m", "image/png", "answer", "wrong", "1111", None, _TID, None, None)
    ns: dict[str, Any] = {
        "cells": [wrong],
        "media_failures": [],
        "verdict": verdict,
        "coverage_failures": coverage_failures,
    }
    with pytest.raises(AssertionError, match="picture was not read"):
        exec(_matrix_code(contains="assert not failures"), ns)
    ns["cells"] = [
        Cell("url4", "m", "image/png", "answer", "answered", "7392", None, _TID, None, None)
    ]
    ns["media_failures"] = ["benchmark m b#1: fetched media digest differs"]
    with pytest.raises(AssertionError, match="digest differs"):
        exec(_matrix_code(contains="assert not failures"), ns)


def test_image_input_matrix_evidence_cell_fills_chat_calls_so_the_verdict_sees_them(
    tmp_path,
) -> None:
    """Review Focus 1 hinges on this cell: a refused cell whose trace shows a provider dispatch
    must fail the verdict. Dropping the ``replace(chat_calls=...)`` would leave every count at
    ``None`` and pass any refusal, so the cell itself is executed here, not only compiled."""
    from dataclasses import replace
    from decimal import Decimal
    from pathlib import Path

    log = tmp_path / "runtime.log"
    log.write_text(
        f"2026-11-17T10:00:00Z [gateway] INFO: dispatch failed provider=openrouter status=400 "
        f"trace_id={_TID2} gateway_call_id=c1\n",
        encoding="utf-8",
    )
    refused = Cell(
        "url4", "t", "image/png", "refuse", "refused", None, "intent_error", _TID2, None, None
    )
    unrun = Cell("url4", "s", "image/png", "answer", "skipped", None, None, None, None, "budget")
    ns: dict[str, Any] = {
        "EVENTS_PATH": str(log),
        "Path": Path,
        "replace": replace,
        "cells": [refused, unrun],
        "upstream_calls": upstream_calls,
        "html_table": html_table,
        "display": lambda _obj: None,
        "HTML": str,
        "budget": Budget(Decimal("0.5")),
    }
    exec(_matrix_code(contains="Path(EVENTS_PATH).read_text("), ns)
    assert [c.chat_calls for c in ns["cells"]] == [1, None]
    assert any("1 gateway chat call(s) ran" in f for f in verdict(ns["cells"]))
