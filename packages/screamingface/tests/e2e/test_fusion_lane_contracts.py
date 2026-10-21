"""Contract tests for the pure seams of ``fixtures/fusion_lane.py`` (OME-1289 E4a, FR#13).

DEFAULT lane: no docker, no key, no recording. ``record`` is paid and ``bless`` needs docker and a
recording, so neither runs here. What does run is everything around them that needs no stack:

- the spend refusals of ``record`` (no opt-in flag, no key, a model without a usable ``seed``);
- the refusals of ``bless``: a recording that does not describe one run of this lane, a replay that
  does not reproduce the saved report (url4, statuses, score, coverage, failures, one Case output);
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


def test_a_replay_that_does_not_reproduce_the_report_refuses_the_bless() -> None:
    report = _report(
        cases=[_case("1", "scored", "so 41"), _case("2", "failed", None, "upstream_error")]
    )
    reason = r"case '1'.*output"
    with pytest.raises(SystemExit, match=f"BLESS REFUSED.*{reason}"):
        _reproduce(report)


def test_a_replay_that_lost_a_case_refuses_the_bless() -> None:
    with pytest.raises(SystemExit, match="BLESS REFUSED"):
        _reproduce(_report(cases=[_case("1", "scored", "so 42")]))


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


def test_an_incomplete_recording_is_refused_naming_the_missing_file(
    tmp_path: Path,
) -> None:
    _write_recording(tmp_path)
    name = "cache.sql.gz"
    (tmp_path / name).unlink()

    with pytest.raises(SystemExit, match=f"lacks {name}"):
        fusion_lane._read_recording(tmp_path)


def test_a_recording_of_another_run_is_refused(
    tmp_path: Path,
) -> None:
    reason = "report-recipe_synthesizer.json describes"
    with pytest.raises(SystemExit, match=reason):
        fusion_lane._read_recording(_write_recording(tmp_path, second=_raw_report(board="ifeval")))


# -- record: every spend refusal comes before any spend -----------------------------


def test_a_refused_record_boots_nothing_and_creates_no_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SCREAMINGFACE_RECORD_PAID", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")
    booted: list[str] = []
    monkeypatch.setattr(fusion_lane.rl, "_record_stack", lambda *args: booted.append("stack"))
    args = fusion_lane._parse_args(
        ["record", "--model", "openrouter/x/y", "--out", str(tmp_path / "out")]
    )

    with pytest.raises(SystemExit, match="SCREAMINGFACE_RECORD_PAID"):
        args.run(args)

    assert booted == []
    assert not (tmp_path / "out").exists()


def _record_with(monkeypatch: pytest.MonkeyPatch, parameters: dict[str, Any]) -> _FakeClient:
    fake = _FakeClient(parameters)
    monkeypatch.setattr(sf, "Client", lambda **kwargs: fake)
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")
    fusion_lane._record_runs("http://engine.invalid", _SPEC, 2)
    return fake


def test_a_model_without_a_usable_seed_is_refused_before_the_live_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parameters = {}  # no seed row published
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
    monkeypatch.setattr(fusion_lane.rl, "_record_stack", lambda *args: (reports, ["row"]))
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
