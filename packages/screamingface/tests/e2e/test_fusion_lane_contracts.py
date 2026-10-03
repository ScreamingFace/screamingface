"""Contract tests for the pure seams of ``fixtures/fusion_lane.py`` (OME-1289 E4a, FR#13).

DEFAULT lane: no docker, no key, no recording. ``record`` is paid and ``bless`` needs docker and a
recording, so neither runs here. What does run is everything around them that needs no stack:

- the spend refusals of ``record`` (no opt-in flag, no key, a model without a usable ``seed``);
- the refusals of ``bless``: a recording that does not describe one run of this lane, a replay that
  does not reproduce the saved report (url4, statuses, score, coverage, failures, one Case output),
  and a block form that does not match the named form (FR-2);
- ``inspect_capture_stack``, the replay stack with a capture proxy, with its teardown order.

A mistake in any of them would otherwise first show after the user's paid recording.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fixtures import fusion_lane
from harness import inspect_stack
from harness.fusion_golden import RECIPES, FusionLaneSpec, body_digests
from harness.goldens import GoldenFailure, expression_sha
from test_reducer_lane_contracts import _FakeClient, _FakeReport, _seed

import screamingface as sf

_SPEC = FusionLaneSpec.model_validate({"model": "openrouter/x/y", "samples": 3, "temperature": 0.7})
_URL4 = "(rendered expression)"
_OUTPUTS: dict[str, str | None] = {"1": "so 42", "2": None}
_FAILURES = {"2": (GoldenFailure(stage="candidate", code="upstream_error"),)}


def _facts(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "board": "inspect-gsm8k",
        "kind": "fusion",
        "rendered_url4": _URL4,
        "expected_score": 0.5,
        "expected_coverage": 0.5,
        "case_statuses": {"1": "scored", "2": "failed"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _case(case_id: str, status: str, output: str | None, code: str | None = None) -> Any:
    failures = () if code is None else (SimpleNamespace(stage="candidate", code=code),)
    return SimpleNamespace(
        case_id=case_id, status=status, output=output, failures=failures, operations=None
    )


def _report(
    *,
    board: str = "inspect-gsm8k",
    url4: str = _URL4,
    score: float | None = 0.5,
    coverage: float = 0.5,
    cases: list[Any] | None = None,
) -> Any:
    default = [_case("1", "scored", "so 42"), _case("2", "failed", None, "upstream_error")]
    outcome = SimpleNamespace(
        url4=url4, score=score, coverage=coverage, cases=default if cases is None else cases
    )
    return SimpleNamespace(
        benchmark=SimpleNamespace(id=board, revision="rev-1"),
        candidates=SimpleNamespace(only=outcome),
    )


def _reproduce(report: Any, **facts: Any) -> dict[str, str]:
    return fusion_lane._refuse_unless_reproduced(report, _facts(**facts), _OUTPUTS, _FAILURES)


# -- bless: the replay must reproduce the saved report ------------------------------


def test_a_reproducing_replay_is_accepted_and_its_statuses_returned() -> None:
    assert _reproduce(_report()) == {"1": "scored", "2": "failed"}


@pytest.mark.parametrize(
    ("report", "reason"),
    [
        (_report(board="ifeval"), "not 'inspect-gsm8k'"),
        (_report(url4="(another expression)"), "different url4"),
        (_report(score=0.25), "score"),
        (_report(coverage=1.0), "coverage"),
        (
            _report(
                cases=[_case("1", "scored", "so 42"), _case("2", "failed", None, "other_code")]
            ),
            "failure codes",
        ),
        (
            _report(
                cases=[_case("1", "scored", "so 41"), _case("2", "failed", None, "upstream_error")]
            ),
            r"case '1'.*output",
        ),
    ],
    ids=["board", "url4", "score", "coverage", "failure codes", "one case output"],
)
def test_a_replay_that_does_not_reproduce_the_report_refuses_the_bless(
    report: Any, reason: str
) -> None:
    with pytest.raises(SystemExit, match=f"BLESS REFUSED.*{reason}"):
        _reproduce(report)


def test_a_replay_with_other_case_statuses_refuses_the_bless() -> None:
    with pytest.raises(SystemExit, match="case statuses diverge"):
        _reproduce(_report(), case_statuses={"1": "scored", "2": "scored"})


def test_a_replay_that_lost_a_case_refuses_the_bless() -> None:
    with pytest.raises(SystemExit, match="BLESS REFUSED"):
        _reproduce(_report(cases=[_case("1", "scored", "so 42")]))


# -- bless: the block form must match the named form (FR-2) -------------------------

_DIGESTS = body_digests([{"request_body": {"a": 1}}, {"request_body": {"b": 2}}])


def _match(block: Any, block_digests: tuple[str, ...] = _DIGESTS) -> None:
    fusion_lane._refuse_unless_block_matches(_report(), block, _DIGESTS, block_digests)


def test_a_block_form_that_matches_the_named_form_is_accepted() -> None:
    _match(_report())


@pytest.mark.parametrize(
    ("block", "digests", "reason"),
    [
        (_report(url4="(another expression)"), _DIGESTS, "different url4 than sf.Fusion"),
        (
            _report(cases=[_case("1", "scored", "so 41"), _case("2", "failed", None)]),
            _DIGESTS,
            "answered differently",
        ),
        (_report(), _DIGESTS[:1], "request bodies"),
    ],
    ids=["url4", "output", "digests"],
)
def test_a_block_form_that_differs_refuses_the_bless(
    block: Any, digests: tuple[str, ...], reason: str
) -> None:
    with pytest.raises(SystemExit, match=f"BLESS REFUSED.*{reason}.*FR-2"):
        _match(block, digests)


# -- bless: the recording must describe one run of this lane ------------------------


def _raw_report(*, kind: str = "fusion", board: str = "inspect-gsm8k") -> dict[str, Any]:
    scored = {"case_id": 1, "status": "scored", "failures": [], "output": "so 42"}
    failed = {
        "case_id": 2,
        "status": "failed",
        "failures": [{"stage": "candidate", "code": "upstream_error", "message": "boom"}],
        "output": None,
    }
    candidate = {
        "kind": kind,
        "url4": _URL4,
        "score": 0.5,
        "coverage": 0.5,
        "cases": [scored, failed],
    }
    return {
        "schema": "screamingface.report.v1",
        "benchmark": {"id": board},
        "candidates": [candidate],
    }


def _write_recording(
    root: Path, *, limit: int = 2, second: dict[str, Any] | None = None, **options: Any
) -> Path:
    first, other = RECIPES
    (root / f"report-{first}.json").write_text(json.dumps(_raw_report(**options)))
    (root / f"report-{other}.json").write_text(json.dumps(second or _raw_report()))
    (root / "candidate.json").write_text(_SPEC.model_dump_json())
    (root / "recording.json").write_text(json.dumps({"limit": limit}))
    (root / "cache.sql.gz").write_bytes(b"")
    return root


def test_a_recording_is_read_with_its_facts_failures_outputs_and_limit(tmp_path: Path) -> None:
    recording = fusion_lane._read_recording(_write_recording(tmp_path))

    assert recording.limit == 2
    assert recording.spec == _SPEC
    for recipe in RECIPES:
        saved = recording.reports[recipe]
        assert saved.failures == _FAILURES
        assert saved.outputs == _OUTPUTS
        # And it is exactly what a reproducing replay is compared with.
        assert fusion_lane._refuse_unless_reproduced(
            _report(), saved.facts, saved.outputs, saved.failures
        ) == {"1": "scored", "2": "failed"}


@pytest.mark.parametrize("name", fusion_lane._RECORDING_FILES)
def test_an_incomplete_recording_is_refused_naming_the_missing_file(
    tmp_path: Path, name: str
) -> None:
    _write_recording(tmp_path)
    (tmp_path / name).unlink()

    with pytest.raises(SystemExit, match=f"lacks {name}"):
        fusion_lane._read_recording(tmp_path)


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"board": "ifeval"}, "not 'inspect-gsm8k'"),
        ({"kind": "model"}, "this lane blesses a fusion"),
        ({"limit": 20}, "limit 20 but the report holds 2 cases"),
        ({"second": _raw_report(board="ifeval")}, "report-recipe_synthesizer.json describes"),
        ({"second": _raw_report(kind="model")}, "report-recipe_synthesizer.json records"),
    ],
    ids=["board", "kind", "limit", "second board", "second kind"],
)
def test_a_recording_of_another_run_is_refused(
    tmp_path: Path, options: dict[str, Any], reason: str
) -> None:
    with pytest.raises(SystemExit, match=reason):
        fusion_lane._read_recording(_write_recording(tmp_path, **options))


# -- record: every spend refusal comes before any spend -----------------------------


def test_record_arguments_default_to_the_documented_lane() -> None:
    args = fusion_lane._parse_args(["record", "--model", "openrouter/x/y", "--out", "out"])

    assert (args.samples, args.temperature, args.limit) == (3, 0.7, 5)
    assert args.run is fusion_lane.record


def test_bless_arguments_default_to_a_five_megabyte_snapshot() -> None:
    args = fusion_lane._parse_args(["bless", "--recording", "rec"])

    assert (args.recording, args.work_dir, args.max_snapshot_mb) == (Path("rec"), None, 5.0)
    assert args.run is fusion_lane.bless


def test_a_refused_record_boots_nothing_and_creates_no_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SCREAMINGFACE_RECORD_PAID", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")
    booted: list[str] = []
    monkeypatch.setattr(fusion_lane, "_record_stack", lambda *args: booted.append("stack"))
    args = fusion_lane._parse_args(
        ["record", "--model", "openrouter/x/y", "--out", str(tmp_path / "out")]
    )

    with pytest.raises(SystemExit, match="SCREAMINGFACE_RECORD_PAID"):
        args.run(args)

    assert booted == []
    assert not (tmp_path / "out").exists()


def test_record_without_a_key_is_refused_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_RECORD_PAID", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    args = fusion_lane._parse_args(
        ["record", "--model", "openrouter/x/y", "--out", str(tmp_path / "out")]
    )

    with pytest.raises(SystemExit, match="OPENROUTER_API_KEY"):
        args.run(args)

    assert not (tmp_path / "out").exists()


def _record_with(monkeypatch: pytest.MonkeyPatch, parameters: dict[str, Any]) -> _FakeClient:
    fake = _FakeClient(parameters)
    monkeypatch.setattr(sf, "Client", lambda **kwargs: fake)
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")
    fusion_lane._record_runs("http://engine.invalid", _SPEC, 2)
    return fake


@pytest.mark.parametrize(
    "parameters",
    [
        {},  # no seed row published
        {"seed": _seed(enabled=False)},  # published, but the gateway does not forward it
        {"seed": _seed(provider_support="unsupported")},  # the provider denies it
    ],
    ids=["missing", "disabled", "unsupported"],
)
def test_a_model_without_a_usable_seed_is_refused_before_the_live_run(
    monkeypatch: pytest.MonkeyPatch, parameters: dict[str, Any]
) -> None:
    fake = _FakeClient(parameters)
    monkeypatch.setattr(sf, "Client", lambda **kwargs: fake)
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")

    with pytest.raises(SystemExit, match="RECORD REFUSED"):
        fusion_lane._record_runs("http://engine.invalid", _SPEC, 2)

    assert "evaluate" not in fake.calls


def test_a_model_with_a_usable_seed_runs_each_shape_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The control of the test above: the fake does let a seed-capable model through.
    fake = _record_with(monkeypatch, {"seed": _seed()})

    assert fake.calls == ["connect", "models.get", "evaluate", "evaluate"]
    assert fake.candidates == [_SPEC.build(recipe) for recipe in RECIPES]


def test_record_writes_the_five_recording_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(fusion_lane.rl, "_require_paid_gate", lambda: None)
    monkeypatch.setattr(fusion_lane.rl, "_require_assets", lambda: tmp_path)
    reports = {recipe: _FakeReport(recipe) for recipe in RECIPES}
    monkeypatch.setattr(fusion_lane, "_record_stack", lambda *args: (reports, ["row"]))
    out = tmp_path / "out"
    args = fusion_lane._parse_args(["record", "--model", "openrouter/x/y", "--out", str(out)])

    args.run(args)

    assert {path.name for path in out.iterdir() if path.is_file()} == set(
        fusion_lane._RECORDING_FILES
    )
    for recipe in RECIPES:
        assert json.loads((out / f"report-{recipe}.json").read_text()) == {"label": recipe}
    assert json.loads((out / "recording.json").read_text()) == {"limit": 5}
    assert FusionLaneSpec.model_validate_json((out / "candidate.json").read_text()) == (
        FusionLaneSpec.model_validate({"model": "openrouter/x/y", "samples": 3, "temperature": 0.7})
    )


# -- bless: the authored golden -----------------------------------------------------


def test_the_authored_golden_holds_both_shapes_and_passes_its_own_check() -> None:
    digests = {recipe: body_digests([{"request_body": {"r": recipe}}]) for recipe in RECIPES}
    replays = {
        recipe: fusion_lane._Replay(report=_report(), digests=digests[recipe]) for recipe in RECIPES
    }
    recording = SimpleNamespace(spec=_SPEC, limit=2)

    golden = fusion_lane._author_golden(replays, recording)  # type: ignore[arg-type]

    assert (golden.lane, golden.board, golden.revision, golden.limit) == (
        "inspect-gsm8k-fusion",
        "inspect-gsm8k",
        "rev-1",
        2,
    )
    for recipe in RECIPES:
        lock = golden.recipes[recipe]
        assert lock.expression_sha == expression_sha(_URL4)
        assert (lock.final_score, lock.case_count, lock.gradeable_count) == ("0.5", 2, 1)
        assert lock.case_outputs == _OUTPUTS
        assert lock.request_bodies == digests[recipe]
        assert [(f.stage, f.code) for f in lock.case_failures["2"]] == [
            ("candidate", "upstream_error")
        ]


# -- the capture stack ----------------------------------------------------------------


class _Backend:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def start(self) -> str:
        self._events.append("backend.start")
        return "http://gateway.test"

    async def stop(self) -> None:
        self._events.append("backend.stop")


class _Proxy:
    """Stands for ``slice_snapshot._CaptureProxy``."""

    events: list[str]

    def __init__(self, gateway_url: str) -> None:
        self.events.append(f"proxy.start {gateway_url}")
        self.url = "http://proxy.test"
        self.records: list[dict[str, Any]] = []

    def shutdown(self) -> None:
        self.events.append("proxy.shutdown")


def _fake_stack(monkeypatch: pytest.MonkeyPatch, *, engine_fails: bool = False) -> list[str]:
    events: list[str] = []
    _Proxy.events = events

    def start(self: Any, gateway_url: str) -> str:
        events.append(f"engine.start {gateway_url}")
        if engine_fails:
            raise RuntimeError("engine did not boot")
        return "http://engine.test"

    monkeypatch.setattr(inspect_stack.InspectEngineProcess, "start", start)
    monkeypatch.setattr(
        inspect_stack.InspectEngineProcess, "stop", lambda self: events.append("engine.stop")
    )
    monkeypatch.setattr("fixtures.slice_snapshot._CaptureProxy", _Proxy)
    return events


def test_the_capture_stack_points_the_engine_at_the_proxy_and_tears_down_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events = _fake_stack(monkeypatch)

    with inspect_stack.inspect_capture_stack(_Backend(events), work_dir=tmp_path) as (stack, proxy):
        events.append("body")
        assert (stack.engine_url, stack.aigateway_url) == (
            "http://engine.test",
            "http://gateway.test",
        )
        assert isinstance(proxy, _Proxy)

    assert events == [
        "backend.start",
        "proxy.start http://gateway.test",
        "engine.start http://proxy.test",
        "body",
        "engine.stop",
        "proxy.shutdown",
        "backend.stop",
    ]


@pytest.mark.parametrize("engine_fails", [False, True], ids=["body fails", "engine fails"])
def test_the_capture_stack_tears_down_when_the_body_or_the_engine_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, engine_fails: bool
) -> None:
    events = _fake_stack(monkeypatch, engine_fails=engine_fails)

    with pytest.raises(RuntimeError):
        with inspect_stack.inspect_capture_stack(_Backend(events), work_dir=tmp_path):
            raise RuntimeError("the body failed")

    assert events[-3:] == ["engine.stop", "proxy.shutdown", "backend.stop"]
