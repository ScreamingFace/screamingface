"""Contract tests for the pure seams of ``fixtures/reducer_lane.py`` (OME-1289 E4a, EV-12).

DEFAULT lane: no docker, no key, no recording. The script's ``record`` step is paid and its
``bless`` step needs docker and a recording, so neither runs here. What does run is everything
around them that needs no stack:

- the spend refusals of ``record`` (no opt-in flag, no key, a model without a usable ``seed``), with
  a fake client that proves the live ``evaluate`` is never reached after a refusal;
- the refusals of ``bless`` (a recording that does not describe one run of this lane, a replay that
  does not reproduce the saved report), the choice of the pinned evidence and the golden authoring.

A mistake in any of them would otherwise first show after the user's paid recording.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fixtures import reducer_lane
from harness.goldens import GoldenFailure, canonical_score, expression_sha
from harness.reducer_golden import ReducerCandidateSpec
from test_reducer_golden_contracts import _case, _evidence, _evidence_kwargs, _spec_doc

import screamingface as sf
from screamingface.combine_evidence import CombineEvidence

_URL4 = "(rendered expression)"
_SPEC = ReducerCandidateSpec.model_validate(_spec_doc())


def _combine() -> dict[str, Any]:
    return json.loads(json.dumps(_evidence().to_dict()))


def _recording(**overrides: Any) -> Any:
    """What ``bless`` knows of a recording that matches ``_report()`` below."""
    values: dict[str, Any] = {
        "facts": SimpleNamespace(
            board="inspect-gsm8k",
            kind="fusion",
            rendered_url4=_URL4,
            expected_score=0.5,
            expected_coverage=0.5,
            case_statuses={"1": "scored", "2": "failed"},
        ),
        "spec": _SPEC,
        "cache": Path("cache.sql.gz"),
        "limit": 2,
        "failures": {"2": (GoldenFailure(stage="candidate", code="combine_no_votes"),)},
        "combines": {"1": _combine()},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _failed_case() -> Any:
    failure = SimpleNamespace(stage="candidate", code="combine_no_votes")
    return SimpleNamespace(case_id="2", status="failed", operations=None, failures=(failure,))


def _report(
    *,
    board: str = "inspect-gsm8k",
    url4: str = _URL4,
    score: float | None = 0.5,
    coverage: float = 0.5,
    cases: list[Any] | None = None,
) -> Any:
    scored = _case("1")
    scored.status, scored.failures = "scored", ()
    outcome = SimpleNamespace(
        url4=url4, score=score, coverage=coverage, cases=cases or [scored, _failed_case()]
    )
    return SimpleNamespace(
        benchmark=SimpleNamespace(id=board, revision="rev-1"),
        candidates=SimpleNamespace(only=outcome),
    )


# -- bless: the replay must reproduce the saved report ------------------------------


def test_a_reproducing_replay_is_accepted_and_its_statuses_returned() -> None:
    assert reducer_lane._refuse_unless_reproduced(_report(), _recording()) == {
        "1": "scored",
        "2": "failed",
    }


def _scored_case(chosen: tuple[str, ...] = ("member_2",)) -> Any:
    evidence = CombineEvidence(**{**_evidence_kwargs(), "chosen": chosen})
    scored = _case("1", evidence=evidence)
    scored.status, scored.failures = "scored", ()
    return scored


def _other_failure_case() -> Any:
    failure = SimpleNamespace(stage="candidate", code="upstream_error")
    return SimpleNamespace(case_id="2", status="failed", operations=None, failures=(failure,))


@pytest.mark.parametrize(
    ("report", "reason"),
    [
        (_report(board="ifeval"), "not 'inspect-gsm8k'"),
        (_report(url4="(another expression)"), "different url4"),
        (_report(score=0.25), "score"),
        (_report(coverage=1.0), "coverage"),
        (_report(cases=[_scored_case(("member_3",)), _failed_case()]), "combine evidence"),
        (_report(cases=[_scored_case(), _other_failure_case()]), "failure codes"),
    ],
)
def test_a_replay_that_does_not_reproduce_the_report_refuses_the_bless(
    report: Any, reason: str
) -> None:
    with pytest.raises(SystemExit, match=f"BLESS REFUSED.*{reason}"):
        reducer_lane._refuse_unless_reproduced(report, _recording())


def test_a_replay_with_other_case_statuses_refuses_the_bless() -> None:
    facts = SimpleNamespace(
        **{**vars(_recording().facts), "case_statuses": {"1": "scored", "2": "scored"}}
    )
    with pytest.raises(SystemExit, match="case statuses diverge"):
        reducer_lane._refuse_unless_reproduced(_report(), _recording(facts=facts))


def test_a_replay_that_lost_the_combine_evidence_refuses_the_bless() -> None:
    bare = _case("1")
    bare.operations, bare.status, bare.failures = (), "scored", ()
    with pytest.raises(SystemExit, match="combine evidence"):
        reducer_lane._refuse_unless_reproduced(_report(cases=[bare, _failed_case()]), _recording())


# -- bless: the recording must describe one run of this lane ------------------------


def _raw_report(*, kind: str = "fusion", board: str = "inspect-gsm8k") -> dict[str, Any]:
    scored = {
        "case_id": 1,
        "status": "scored",
        "failures": [],
        "operations": [
            {"operation_id": "op_model_1", "output": "so 41"},
            {"operation_id": "op_synthesis_1", "output": "so 42", "combine": _combine()},
        ],
    }
    failed = {
        "case_id": 2,
        "status": "failed",
        "failures": [{"stage": "candidate", "code": "combine_no_votes", "message": "no votes"}],
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


def _write_recording(root: Path, *, limit: int = 2, **report_options: Any) -> Path:
    (root / "report.json").write_text(json.dumps(_raw_report(**report_options)))
    (root / "candidate.json").write_text(_SPEC.model_dump_json())
    (root / "recording.json").write_text(json.dumps({"limit": limit}))
    (root / "cache.sql.gz").write_bytes(b"")
    return root


def test_a_recording_is_read_with_its_failures_combines_and_limit(tmp_path: Path) -> None:
    recording = reducer_lane._read_recording(_write_recording(tmp_path))

    assert recording.limit == 2
    assert recording.spec == _SPEC
    assert recording.failures == _recording().failures
    assert recording.combines == {"1": _combine()}
    # And it is exactly what a reproducing replay is compared with.
    assert reducer_lane._refuse_unless_reproduced(_report(), recording) == {
        "1": "scored",
        "2": "failed",
    }


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"board": "ifeval"}, "not 'inspect-gsm8k'"),
        ({"kind": "model"}, "this lane blesses a fusion"),
        ({"limit": 20}, "limit 20 but the report holds 2 cases"),
    ],
)
def test_a_recording_of_another_run_is_refused(
    tmp_path: Path, options: dict[str, Any], reason: str
) -> None:
    with pytest.raises(SystemExit, match=reason):
        reducer_lane._read_recording(_write_recording(tmp_path, **options))


def test_an_incomplete_recording_is_refused_naming_the_missing_files(tmp_path: Path) -> None:
    _write_recording(tmp_path)
    (tmp_path / "recording.json").unlink()

    with pytest.raises(SystemExit, match="lacks recording.json"):
        reducer_lane._read_recording(tmp_path)


# -- bless: the pinned evidence and the golden --------------------------------------


def test_the_pinned_evidence_is_the_first_case_that_carries_it() -> None:
    cases = [_failed_case(), _case("7"), _case("8")]

    lock = reducer_lane._evidence(cases)

    assert (lock.case_id, lock.operation_id) == ("7", "op_synthesis_1")
    assert lock.combine == _evidence().to_dict()


def test_a_run_without_combine_evidence_refuses_the_bless() -> None:
    with pytest.raises(SystemExit, match="no case carries combine evidence"):
        reducer_lane._evidence([_failed_case()])


def test_the_authored_golden_holds_the_five_locks_and_the_evidence() -> None:
    statuses = {"1": "scored", "2": "failed"}

    golden = reducer_lane._author_golden(_report(), _SPEC, statuses, limit=2)

    assert golden.lane == "inspect-gsm8k-vote"
    assert (golden.board, golden.revision, golden.limit) == ("inspect-gsm8k", "rev-1", 2)
    assert golden.expression_sha == expression_sha(_URL4)
    assert golden.final_score == canonical_score(0.5) == "0.5"
    assert (golden.case_count, golden.gradeable_count) == (2, 1)
    assert [(f.stage, f.code) for f in golden.case_failures["2"]] == [
        ("candidate", "combine_no_votes")
    ]
    assert golden.evidence.case_id == "1"


# -- record: every spend refusal comes before any spend -----------------------------


def test_record_arguments_default_to_the_documented_lane() -> None:
    args = reducer_lane._parse_args(["record", "--model", "openrouter/x/y", "--out", "out"])

    assert (args.samples, args.temperature, args.limit) == (5, 0.7, 20)
    assert (args.extract, args.normalize) == ("last_number", "numeric")
    assert args.run is reducer_lane.record


def test_record_without_the_opt_in_flag_is_refused_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCREAMINGFACE_RECORD_PAID", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")

    with pytest.raises(SystemExit, match="SCREAMINGFACE_RECORD_PAID"):
        reducer_lane._require_paid_gate()


def test_record_without_a_key_is_refused_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_RECORD_PAID", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="OPENROUTER_API_KEY"):
        reducer_lane._require_paid_gate()


def test_a_refused_record_boots_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SCREAMINGFACE_RECORD_PAID", raising=False)
    booted: list[str] = []
    monkeypatch.setattr(reducer_lane, "_record_stack", lambda *args: booted.append("stack"))
    args = reducer_lane._parse_args(
        ["record", "--model", "openrouter/x/y", "--out", str(tmp_path / "out")]
    )

    with pytest.raises(SystemExit, match="SCREAMINGFACE_RECORD_PAID"):
        args.run(args)

    assert booted == []
    assert not (tmp_path / "out").exists()


class _FakeClient:
    """A client that records every call, so a test can see what a refusal let through."""

    calls: list[str]

    def __init__(self, parameters: dict[str, Any]) -> None:
        self._parameters = parameters
        self.calls = []
        self.models = SimpleNamespace(get=self._get)

    def _get(self, model: str) -> Any:
        self.calls.append("models.get")
        return SimpleNamespace(parameters=self._parameters)

    def connect(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append("connect")

    def evaluate(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append("evaluate")
        return "report"

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _seed(*, enabled: bool = True, provider_support: str = "supported") -> Any:
    return SimpleNamespace(enabled=enabled, provider_support=provider_support)


def _record_with(monkeypatch: pytest.MonkeyPatch, parameters: dict[str, Any]) -> _FakeClient:
    fake = _FakeClient(parameters)
    monkeypatch.setattr(sf, "Client", lambda **kwargs: fake)
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")
    reducer_lane._record_run("http://engine.invalid", _SPEC, 2)
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
        reducer_lane._record_run("http://engine.invalid", _SPEC, 2)

    assert "evaluate" not in fake.calls


def test_a_model_with_a_usable_seed_reaches_the_live_run(monkeypatch: pytest.MonkeyPatch) -> None:
    # The control of the test above: the fake does let a seed-capable model through.
    fake = _record_with(monkeypatch, {"seed": _seed()})

    assert fake.calls == ["connect", "models.get", "evaluate"]
