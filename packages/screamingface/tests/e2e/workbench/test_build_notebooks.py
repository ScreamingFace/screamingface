from __future__ import annotations

import json
from decimal import Decimal
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
        assert nb.metadata["workbench"]["required_result"] == ["trace_ids"], stem


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


class _Usage:
    def __init__(self, cost_usd: Decimal | None) -> None:
        self.cost_usd = cost_usd


class _Candidate:
    def __init__(
        self,
        trace_id: str | None,
        cost_usd: Decimal | None = Decimal("0.0123"),
        cache_saved_cost_usd: Decimal | None = Decimal("0"),
    ) -> None:
        self.name = "c"
        self.trace_id = trace_id
        self.run_id = "r1"
        self.score = 0.5
        self.cache_hits = 0
        self.cache_saved_cost_usd = cache_saved_cost_usd
        self.usage = _Usage(cost_usd)


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


def test_quickstart_reports_each_candidates_spend_and_cache_savings(capsys) -> None:
    payload, _ = _evaluate_then_report(_Report(_TID), capsys)
    assert payload["candidates"]["c"] == {
        "score": 0.5,
        "cost_usd": "0.0123",
        "cache_hits": 0,
        "cache_saved_cost_usd": "0",
    }


def test_quickstart_reports_unknown_money_as_null_never_the_string_none(capsys) -> None:
    # The SDK's None means "nothing priceable was observed", which is not zero (report.py).
    report = _Report()
    report.candidates = [_Candidate(_TID, cost_usd=None, cache_saved_cost_usd=None)]
    payload, _ = _evaluate_then_report(report, capsys)
    candidate = payload["candidates"]["c"]
    assert candidate["cost_usd"] is None and candidate["cache_saved_cost_usd"] is None


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


# Unit 6 Task 4: with EVENTS_PATH set (the workbench sets it), every SDK event is recorded,
# redacted, as one JSON line, and the result cell writes report.json + accounting.json.

_KEY = "sk-or-v1-" + "f0e1d2c3" * 4  # fake, assembled at runtime (secret scanners)


def _log_event(seq: int) -> Any:
    from datetime import UTC, datetime

    from screamingface import events as ev

    return ev.Log(
        id=f"e{seq}",
        run_id="r1",
        sequence=seq,
        timestamp=datetime(2026, 10, 22, tzinfo=UTC),
        source="engine",
        severity_number=17,
        severity_text="ERROR",
        body=f"upstream refused key {_KEY}",
        attributes={"x-api-key": "opaque-value-123", "attempt": seq},
    )


class _RecordingClient:
    """Emits two events through ``on_event`` before returning ``outcome``."""

    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome
        self.on_event: Any = "unset"

    def evaluate(self, *_: Any, on_event: Any = None, **__: Any) -> Any:
        self.on_event = on_event
        if on_event is not None:
            on_event(_log_event(1))
            on_event(_log_event(2))
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


class _DictReport(_Report):
    def to_dict(self) -> dict[str, Any]:
        return {"schema": "screamingface.report.v1", "candidates": [{"name": "c"}]}


def _run_recorded(outcome: Any, events_path: str, capsys: pytest.CaptureFixture[str]) -> Any:
    client = _RecordingClient(outcome)
    ns: dict[str, Any] = {"sf": sf, "json": json, "client": client}
    exec(_quickstart_code(tag="parameters"), ns)
    ns["EVENTS_PATH"] = events_path
    ns["candidate"] = object()
    exec(_quickstart_code(contains="client.evaluate("), ns)
    exec(_quickstart_code(tag="workbench-result"), ns)
    assert [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(RESULT_PREFIX)]
    return client


def test_quickstart_records_nothing_unless_the_workbench_sets_events_path(capsys) -> None:
    namespace: dict[str, Any] = {}
    exec(_quickstart_code(tag="parameters"), namespace)
    assert namespace["EVENTS_PATH"] == ""
    client = _run_recorded(_DictReport(_TID), "", capsys)
    assert client.on_event is None


def test_quickstart_records_redacted_events_report_and_accounting(tmp_path, capsys) -> None:
    events = tmp_path / "events.jsonl"
    client = _run_recorded(_DictReport(_TID), str(events), capsys)
    assert client.on_event is not None
    text = events.read_text(encoding="utf-8")
    assert _KEY not in text and "opaque-value-123" not in text
    rows = [json.loads(line) for line in text.splitlines()]
    assert [(r["kind"], r["attributes"]["attempt"]) for r in rows] == [("log", 1), ("log", 2)]
    assert json.loads((tmp_path / "report.json").read_text())["candidates"] == [{"name": "c"}]
    recorder = json.loads((tmp_path / "recorder.json").read_text())
    assert recorder["events"]["recorded"] == 2
    assert recorder["files"]["report.json"] == "written"
    # The fake candidates carry no accounting view: recorded as an error, never raised.
    assert recorder["files"]["accounting.json"].startswith("error: AttributeError")


def test_quickstart_records_events_of_a_failed_evaluate_too(tmp_path, capsys) -> None:
    events = tmp_path / "events.jsonl"
    error = sf.ScreamingFaceError("run failed", code="run_failed", trace_id=_TID)
    _run_recorded(error, str(events), capsys)
    assert len(events.read_text().splitlines()) == 2
    recorder = json.loads((tmp_path / "recorder.json").read_text())
    assert recorder["files"] == {"report.json": "no report", "accounting.json": "no report"}


def test_the_result_cell_prints_its_marker_before_it_writes_the_files() -> None:
    """The trace ids reach the evidence even if writing the report files misbehaves."""
    source = _quickstart_code(tag="workbench-result")
    assert source.index(RESULT_PREFIX) < source.index(".finish(")


# Unit 7 Task 3: `debug_failing_run` fails ON PURPOSE (spec §3.7). Its declaration and its
# failure shape are the ones discovered on replay (ledger, Task 2), never guessed.

_DEBUG_HEALTHY = "openrouter/mistralai/ministral-3b-2512"
_DEBUG_UNSERVABLE = "openrouter/openai/gpt-5.5"


def _debug_code(tag: str | None = None, contains: str | None = None) -> str:
    for cell in build()["debug_failing_run"].cells:
        if cell.cell_type != "code":
            continue
        if tag and tag in cell.metadata.get("tags", []):
            return cell.source
        if contains and contains in cell.source:
            return cell.source
    raise AssertionError(f"no debug cell with tag={tag} contains={contains}")


def test_debug_notebook_declares_the_discovered_expected_failure() -> None:
    from workbench.expectation import parse_expect

    meta = build()["debug_failing_run"].metadata["workbench"]
    assert meta["expect"] == {
        "outcome": "fail",
        "failure_codes": ["upstream_error"],
        "stage": "candidate",
    }
    expect, problems = parse_expect(meta["expect"])
    assert expect is not None and problems == []
    assert meta["required_result"] == ["trace_ids"]
    # Replay only: on `local` the unservable route is a real, billed model (ledger, Task 2).
    assert meta["targets"] == ["replay"]
    params: dict[str, Any] = {}
    exec(_debug_code(tag="parameters"), params)
    assert params["EXPECTED_CODE"] == "upstream_error"
    assert params["EXPECTED_STAGE"] == "candidate"
    assert params["UNSERVABLE_MODEL"] == _DEBUG_UNSERVABLE


def test_debug_recipe_pairs_the_golden_member_with_a_route_the_tape_never_recorded() -> None:
    from harness.goldens import spec_model

    golden = load_golden(GOLDENS_DIR / "ifeval.golden.json")
    ns: dict[str, Any] = {"sf": sf}
    exec(_debug_code(tag="parameters"), ns)
    exec(_debug_code(contains="candidate = sf.Fusion("), ns)
    candidate = ns["candidate"]
    healthy, unservable = candidate.members
    assert healthy == spec_model(golden.member_specs[0])  # the recorded request: a cache hit
    assert ns["HEALTHY_MODEL"] == _DEBUG_HEALTHY == golden.member_specs[0].model
    assert unservable.model == _DEBUG_UNSERVABLE
    taped = {spec.model for spec in golden.member_specs} | {golden.judge_spec.model}  # type: ignore[union-attr]
    assert _DEBUG_UNSERVABLE not in taped


def test_debug_notebook_filters_logs_with_the_verdicts_exact_token_rule() -> None:
    """Review Focus 3: the tutorial teaches the rule the verdict enforces, never a substring."""
    from workbench.evidence import trace_id_tokens

    ns: dict[str, Any] = {"trace_id": _TID, "HEALTHY_MODEL": _DEBUG_HEALTHY, "GATEWAY_LOG": ""}
    cell = _debug_code(contains="TRACE_ID_TOKEN = re.compile(")
    exec("import re\nfrom pathlib import Path\n" + cell, ns)
    lines_of = ns["lines_of"]
    samples = [
        f"INFO x gateway_call_id=call_1 trace_id={_TID} ok",
        f"INFO x trace_id={_TID}",
        f"INFO x parent_trace_id={_TID} decoy",
        f"INFO x trace_id={_TID}ff decoy",
        f"INFO x trace_id=aa{_TID} decoy",
        f"INFO x trace_id={_TID.upper()} decoy",
        f"INFO x trace_id={_TID2} other run",
    ]
    for line in samples:
        assert bool(lines_of(_TID, line)) == (_TID in trace_id_tokens(line)), line


def test_debug_notebook_reads_this_runs_lines_from_a_gateway_log(tmp_path, capsys) -> None:
    log = tmp_path / "aigateway.log"
    log.write_text(
        f"INFO a gateway_call_id=call_x trace_id={_TID} mine\n"
        f"INFO a gateway_call_id=call_y parent_trace_id={_TID} not mine\n",
        encoding="utf-8",
    )
    ns: dict[str, Any] = {
        "trace_id": _TID,
        "HEALTHY_MODEL": _DEBUG_HEALTHY,
        "GATEWAY_LOG": str(log),
    }
    exec(
        "import re\nfrom pathlib import Path\n"
        + _debug_code(contains="TRACE_ID_TOKEN = re.compile("),
        ns,
    )
    out = capsys.readouterr().out
    assert "call_x" in out and "call_y" not in out


# A fake run in the discovered shape (ledger, Task 2): evaluate() returns; case 1 failed with
# upstream_error at candidate; ERROR Logs name the unservable model; the failing span names
# the healthy member; Usage proves the healthy member ran.


class _Case:
    def __init__(self, failures: tuple[Any, ...]) -> None:
        self.case_id = "1"
        self.status = "failed" if failures else "succeeded"
        self.output = None if failures else "ok"
        self.failures = failures


class _DebugCandidate(_Candidate):
    def __init__(self, code: str | None) -> None:
        super().__init__(_TID)
        self.name = "debug_unservable"
        self.score = None
        self.cache_hits = 1
        self.failures = ()
        failures = (
            ()
            if code is None
            else (
                sf.Failure(
                    stage="candidate",
                    code=code,
                    message="aigateway request failed with status 404",
                    retryable=False,
                    case_id="1",
                    metadata={
                        "source_error": {
                            "kind": "CandidateExecutionError",
                            "source_code": "profile_not_found",
                        }
                    },
                ),
            )
        )
        self.cases = [_Case(failures)]


class _DebugReport:
    def __init__(self, code: str | None) -> None:
        self.candidates = [_DebugCandidate(code)]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "screamingface.report.v1", "candidates": []}


def _debug_events() -> list[Any]:
    from datetime import UTC, datetime

    from screamingface import events as ev

    at = datetime(2026, 10, 22, tzinfo=UTC)
    base = {"run_id": "r1", "timestamp": at, "source": "engine"}
    return [
        ev.Log(
            id="e1",
            sequence=1,
            severity_number=17,
            severity_text="ERROR",
            body="Model call failed",
            attributes={
                "sf.activity.model_id": _DEBUG_UNSERVABLE,
                "sf.activity.failure_code": "internal_error",
            },
            **base,
        ),
        ev.Span(
            id="e2",
            sequence=2,
            name="/benchmarks/candidate",
            operation="RelUrlNode",
            start=at,
            end=at,
            status="error",
            provider="openrouter",
            request_model=_DEBUG_HEALTHY,
            response_model=_DEBUG_HEALTHY,
            finish_reasons=("stop",),
            cache_status="hit",
            **base,
        ),
        ev.Usage(
            id="e3",
            sequence=3,
            scope="self",
            provider="openrouter",
            model=_DEBUG_HEALTHY,
            pricing_version="v1",
            usage=sf.Usage(input_tokens=0, output_tokens=0, cost_usd="0"),
            **base,
        ),
    ]


class _DebugClient:
    def __init__(self, report: Any) -> None:
        self._report = report

    def evaluate(self, *_: Any, on_event: Any = None, **__: Any) -> Any:
        for event in _debug_events():
            on_event(event)
        return self._report


def _run_debug(
    code: str | None, events_path: str, capsys: pytest.CaptureFixture[str]
) -> tuple[dict, dict]:
    """Every debug code cell after the recipe, in order, against the fake run."""
    ns: dict[str, Any] = {"sf": sf, "client": _DebugClient(_DebugReport(code))}
    exec(_debug_code(tag="parameters"), ns)
    ns["EVENTS_PATH"] = events_path
    cells = [c for c in build()["debug_failing_run"].cells if c.cell_type == "code"]
    start = next(i for i, c in enumerate(cells) if "candidate = sf.Fusion(" in c.source)
    client_cell = _debug_code(contains="sf.Client(")
    exec("\n".join(ln for ln in client_cell.splitlines() if ln.startswith(("import", "from"))), ns)
    payload: dict[str, Any] = {}
    for cell in cells[start:]:
        if "client.close()" in cell.source:
            continue
        exec(cell.source, ns)
        if "workbench-result" in cell.metadata.get("tags", []):
            out = capsys.readouterr().out
            (line,) = [ln for ln in out.splitlines() if ln.startswith(RESULT_PREFIX)]
            payload = json.loads(line[len(RESULT_PREFIX) :])
    return payload, ns


@pytest.mark.parametrize("recorded", [True, False], ids=["workbench", "standalone"])
def test_debug_notebook_walks_the_discovered_failure_green(tmp_path, capsys, recorded) -> None:
    events = str(tmp_path / "events.jsonl") if recorded else ""
    payload, _ = _run_debug("upstream_error", events, capsys)
    assert payload["trace_ids"] == [_TID]
    assert payload["failure_codes"] == ["upstream_error"]
    out = capsys.readouterr().out
    assert _DEBUG_UNSERVABLE in out  # the ERROR Log names the failing model
    assert "upstream_error" in out and "404" not in out  # code shown; provider text never printed
    if recorded:
        assert (tmp_path / "report.json").exists()


@pytest.mark.parametrize(
    ("code", "why"),
    [(None, "unexpected pass"), ("provider_error", "provider_error")],
    ids=["unexpected-pass", "wrong-code"],
)
def test_debug_notebook_asserts_fail_on_any_other_outcome(tmp_path, capsys, code, why) -> None:
    with pytest.raises(AssertionError, match=why):
        _run_debug(code, str(tmp_path / "events.jsonl"), capsys)


def test_debug_fixed_recipe_is_markdown_only_and_servable() -> None:
    nb = build()["debug_failing_run"]
    fixed = [c.source for c in nb.cells if c.cell_type == "markdown" and "```python" in c.source]
    assert len(fixed) == 1
    golden = load_golden(GOLDENS_DIR / "ifeval.golden.json")
    assert golden.member_specs[1].model in fixed[0]
    assert _DEBUG_UNSERVABLE not in fixed[0].split("```python", 1)[1]


def test_notebooks_are_selected_by_their_declared_targets() -> None:
    """A notebook that does not declare a target is never collected for it, so it cannot turn
    into a skip that REQUIRE_ALL then fails (debug_failing_run is replay-only by owner decision,
    2026-10-26)."""
    from workbench.build_notebooks import notebooks_for

    replay = {p.stem for p in notebooks_for("replay")}
    local = {p.stem for p in notebooks_for("local")}
    assert {"quickstart", "debug_failing_run"} <= replay
    assert "quickstart" in local
    assert "debug_failing_run" not in local
