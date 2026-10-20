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

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fixtures import reducer_lane
from harness._local_proc import repo_root
from harness.goldens import GoldenFailure, canonical_score, expression_sha
from harness.reducer_golden import ReducerCandidateSpec
from test_reducer_golden_contracts import (
    _abstained_evidence,
    _answered,
    _case,
    _evidence,
    _evidence_kwargs,
    _priced_evidence,
    _spec_doc,
    _trace,
)

import screamingface as sf
from screamingface import _surface as sx
from screamingface.combine_evidence import CombineEvidence

_URL4 = "(rendered expression)"
_SIGNAL_URL4 = "(rendered signal expression)"
_SPEC = ReducerCandidateSpec.model_validate(_spec_doc())


def _combine() -> dict[str, Any]:
    return json.loads(json.dumps(_evidence().to_dict()))


def _priced_combine(member_2_cost: float = 0.002) -> dict[str, Any]:
    return json.loads(json.dumps(_priced_evidence(member_2_cost).to_dict()))


def _live_traces() -> dict[str, Any]:
    return {"vote": _trace(), "signal_vote": _trace()}


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
        "failures": {"2": (GoldenFailure(stage="candidate", code="upstream_error"),)},
        "combines": {"1": _combine()},
        "signal_facts": SimpleNamespace(
            board="inspect-gsm8k",
            kind="fusion",
            rendered_url4=_SIGNAL_URL4,
            expected_score=0.5,
            expected_coverage=0.5,
            case_statuses={"1": "scored", "2": "failed"},
        ),
        "signal_combines": {"1": _priced_combine()},
        "live_traces": _live_traces(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _failed_case() -> Any:
    failure = SimpleNamespace(stage="candidate", code="upstream_error")
    return SimpleNamespace(case_id="2", status="failed", operations=None, failures=(failure,))


def _report(
    *,
    board: str = "inspect-gsm8k",
    url4: str = _URL4,
    score: float | None = 0.5,
    coverage: float = 0.5,
    cases: list[Any] | None = None,
    trace: dict[str, Any] | None = None,
) -> Any:
    scored = _case("1")
    scored.status, scored.failures = "scored", ()
    outcome = SimpleNamespace(
        url4=url4, score=score, coverage=coverage, cases=cases or [scored, _failed_case()]
    )
    return SimpleNamespace(
        benchmark=SimpleNamespace(id=board, revision="rev-1"),
        candidates=SimpleNamespace(only=outcome),
        trace_dict=lambda: _trace() if trace is None else trace,
    )


def _priced_case(member_2_cost: float = 0.002) -> Any:
    priced = _case("1", evidence=_priced_evidence(member_2_cost))
    priced.status, priced.failures = "scored", ()
    return priced


def _signal_report(member_2_cost: float = 0.002, *, url4: str = _SIGNAL_URL4) -> Any:
    return _report(url4=url4, cases=[_priced_case(member_2_cost), _failed_case()])


# -- bless: the replay must reproduce the saved report ------------------------------


def _scored_case(chosen: tuple[str, ...] = ("member_2",)) -> Any:
    result = _answered(chosen[0], "42")
    evidence = CombineEvidence(**{**_evidence_kwargs(), "chosen": chosen, "result": result})
    scored = _case("1", evidence=evidence)
    scored.status, scored.failures = "scored", ()
    return scored


def _other_failure_case() -> Any:
    failure = SimpleNamespace(stage="candidate", code="combine_spec_invalid")
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


def test_a_replay_with_other_signals_refuses_the_bless() -> None:
    drifted = _signal_report(member_2_cost=0.003)

    with pytest.raises(SystemExit, match=r"BLESS REFUSED.*SG-D1.*case '1'.*signals"):
        reducer_lane._refuse_unless_signals_reproduced(drifted, _recording())


def test_a_signal_replay_of_another_expression_refuses_the_bless() -> None:
    with pytest.raises(SystemExit, match="BLESS REFUSED.*different url4"):
        reducer_lane._refuse_unless_signals_reproduced(
            _signal_report(url4="(another expression)"), _recording()
        )


def test_a_recording_that_priced_no_call_refuses_the_bless() -> None:
    unpriced = _report(url4=_SIGNAL_URL4)
    recording = _recording(signal_combines={"1": _combine()})

    with pytest.raises(SystemExit, match=r"BLESS REFUSED.*priced no call \(SG#15"):
        reducer_lane._refuse_unless_signals_reproduced(unpriced, recording)


def _extract_trace(value: str) -> dict[str, Any]:
    entry = {"kind": "extract", "operation_id": "op_synthesis_1", "value": value}
    case = {"case_id": 1, "entries": [entry, *({"kind": "budget", "n": n} for n in range(6))]}
    return {**_trace(), "candidates": [{"candidate": "vote", "cases": [case]}]}


def test_matching_traces_are_accepted() -> None:
    recording = _recording(live_traces={"vote": _extract_trace("42"), "signal_vote": _trace()})

    reducer_lane._refuse_unless_traces_match(
        recording, {"vote": _extract_trace("42"), "signal_vote": _trace()}
    )


def test_a_trace_drift_refuses_the_bless() -> None:
    recording = _recording(live_traces={"vote": _extract_trace("42"), "signal_vote": _trace()})
    replayed = {"vote": _extract_trace("41"), "signal_vote": _trace()}
    path = "candidates[0].cases[0].entries[0].value"

    with pytest.raises(SystemExit, match=rf"BLESS REFUSED.*RT-4.*{re.escape(path)}"):
        reducer_lane._refuse_unless_traces_match(recording, replayed)


# -- bless: the recording must describe one run of this lane ------------------------


def _raw_report(
    *,
    kind: str = "fusion",
    board: str = "inspect-gsm8k",
    url4: str = _URL4,
    combine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scored = {
        "case_id": 1,
        "status": "scored",
        "failures": [],
        "operations": [
            {"operation_id": "op_model_1", "output": "so 41"},
            {
                "operation_id": "op_synthesis_1",
                "output": "so 42",
                "combine": _combine() if combine is None else combine,
            },
        ],
    }
    failed = {
        "case_id": 2,
        "status": "failed",
        "failures": [{"stage": "candidate", "code": "upstream_error", "message": "no votes"}],
    }
    candidate = {
        "kind": kind,
        "url4": url4,
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
    root: Path, *, limit: int = 2, signal_kind: str = "fusion", **report_options: Any
) -> Path:
    signal = _raw_report(kind=signal_kind, url4=_SIGNAL_URL4, combine=_priced_combine())
    (root / "report.json").write_text(json.dumps(_raw_report(**report_options)))
    (root / "signals-report.json").write_text(json.dumps(signal))
    (root / "trace.json").write_text(json.dumps(_trace()))
    (root / "signals-trace.json").write_text(json.dumps(_trace()))
    (root / "candidate.json").write_text(_SPEC.model_dump_json())
    (root / "recording.json").write_text(json.dumps({"limit": limit, "signal": "cost_usd"}))
    (root / "cache.sql.gz").write_bytes(b"")
    return root


def test_a_recording_is_read_with_its_failures_combines_and_limit(tmp_path: Path) -> None:
    recording = reducer_lane._read_recording(_write_recording(tmp_path))

    assert recording.limit == 2
    assert recording.spec == _SPEC
    assert recording.failures == _recording().failures
    assert recording.combines == {"1": _combine()}
    assert recording.signal_combines == {"1": _priced_combine()}
    assert recording.signal_facts.rendered_url4 == _SIGNAL_URL4
    assert recording.live_traces == _live_traces()
    # And it is exactly what a reproducing replay is compared with.
    reducer_lane._refuse_unless_signals_reproduced(_signal_report(), recording)
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
        ({"signal_kind": "model"}, "this lane blesses a fusion"),
    ],
)
def test_a_recording_of_another_run_is_refused(
    tmp_path: Path, options: dict[str, Any], reason: str
) -> None:
    with pytest.raises(SystemExit, match=reason):
        reducer_lane._read_recording(_write_recording(tmp_path, **options))


def test_an_incomplete_recording_is_refused_naming_the_missing_files(
    tmp_path: Path,
) -> None:
    _write_recording(tmp_path)
    name = "cache.sql.gz"
    (tmp_path / name).unlink()

    with pytest.raises(SystemExit, match=f"lacks {name}"):
        reducer_lane._read_recording(tmp_path)


# -- bless: the pinned evidence and the golden --------------------------------------


def test_the_pinned_evidence_is_the_first_case_that_carries_it() -> None:
    cases = [_failed_case(), _case("7"), _case("8")]

    lock = reducer_lane._evidence(cases)

    assert (lock.case_id, lock.operation_id) == ("7", "op_synthesis_1")
    assert lock.combine == _evidence().to_dict()


def test_the_pinned_evidence_skips_an_abstained_first_case() -> None:
    cases = [_case("1", evidence=_abstained_evidence()), _case("2")]

    assert reducer_lane._evidence(cases).case_id == "2"
    with pytest.raises(SystemExit, match="no case answered"):
        reducer_lane._evidence([_case("1", evidence=_abstained_evidence())])


def test_the_authored_golden_holds_the_five_locks_and_the_evidence() -> None:
    statuses = {"1": "scored", "2": "failed"}

    golden = reducer_lane._author_golden(_report(), _signal_report(), _recording(), statuses)

    assert golden.lane == "inspect-gsm8k-vote"
    assert (golden.board, golden.revision, golden.limit) == ("inspect-gsm8k", "rev-1", 2)
    assert golden.expression_sha == expression_sha(_URL4)
    assert golden.final_score == canonical_score(0.5) == "0.5"
    assert (golden.case_count, golden.gradeable_count) == (2, 1)
    assert [(f.stage, f.code) for f in golden.case_failures["2"]] == [
        ("candidate", "upstream_error")
    ]
    assert golden.evidence.case_id == "1"
    assert golden.signal_replay.expression_sha == expression_sha(_SIGNAL_URL4)
    assert golden.signal_replay.combines == {"1": _priced_combine()}
    assert golden.live_traces == _live_traces()


# -- record: every spend refusal comes before any spend -----------------------------


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
        self.candidates: list[Any] = []
        self.models = SimpleNamespace(get=self._get)

    def _get(self, model: str) -> Any:
        self.calls.append("models.get")
        return SimpleNamespace(parameters=self._parameters)

    def connect(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append("connect")

    def evaluate(self, candidate: Any, *args: Any, **kwargs: Any) -> str:
        self.calls.append("evaluate")
        self.candidates.append(candidate)
        return f"report-{len(self.candidates)}"

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


def test_record_runs_the_signal_vote_first_and_the_plain_vote_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient({"seed": _seed()})
    monkeypatch.setattr(sf, "Client", lambda **kwargs: fake)
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")

    reports = reducer_lane._record_run("http://engine.invalid", _SPEC, 2)

    signal_vote = sx.Vote(over="last_number", normalize="numeric", weights=sf.signal("cost_usd"))
    plain_vote = sx.Vote(over="last_number", normalize="numeric")
    assert [candidate.steps[1] for candidate in fake.candidates] == [signal_vote, plain_vote]
    # Same members, so the plain vote's requests are the signal vote's, served from the live cache.
    assert fake.candidates[0].steps[0].members == fake.candidates[1].steps[0].members
    assert reports == ("report-1", "report-2")
    assert fake.calls == ["connect", "models.get", "evaluate", "evaluate"]


class _FakeReport:
    """The three things ``record`` reads off a live report."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.candidates = SimpleNamespace(only=SimpleNamespace(score=0.5, coverage=0.5))

    def export(self, path: Path) -> None:
        Path(path).write_text(json.dumps({"label": self.label}))

    def trace_dict(self) -> dict[str, Any]:
        return {"schema": "screamingface.report-trace.v1", "label": self.label}


def test_record_writes_the_seven_recording_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(reducer_lane, "_require_paid_gate", lambda: None)
    monkeypatch.setattr(reducer_lane, "_require_assets", lambda: tmp_path)
    stacked = ((_FakeReport("signal"), _FakeReport("plain")), ["row"])
    monkeypatch.setattr(reducer_lane, "_record_stack", lambda *args: stacked)
    out = tmp_path / "out"
    args = reducer_lane._parse_args(["record", "--model", "openrouter/x/y", "--out", str(out)])

    args.run(args)

    written = {path.name for path in out.iterdir() if path.is_file()}
    assert written == set(reducer_lane._RECORDING_FILES)

    def read(name: str) -> dict[str, Any]:
        return json.loads((out / name).read_text("utf-8"))

    assert read("report.json") == {"label": "plain"}
    assert read("signals-report.json") == {"label": "signal"}
    assert read("trace.json")["label"] == "plain"
    assert read("signals-trace.json")["label"] == "signal"
    assert read("recording.json") == {"limit": 20, "signal": "cost_usd"}
    assert read("candidate.json")["weights"] is None


# -- the replay snapshots carry the cache entry metadata (F4) -----------------------

_GATEWAY_SNAPSHOT = (
    repo_root()
    / "apps"
    / "aigateway"
    / "src"
    / "aigateway"
    / "core"
    / "request_cache"
    / "snapshot.py"
)


def _gateway_columns() -> tuple[str, ...]:
    """``CANONICAL_COLUMNS``, read from the gateway source (the SDK test job cannot import it)."""
    if not _GATEWAY_SNAPSHOT.parents[4].is_dir():
        pytest.skip("the aigateway app is absent from this checkout")
    for node in ast.parse(_GATEWAY_SNAPSHOT.read_text("utf-8")).body:
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", "") == "CANONICAL_COLUMNS"
        ):
            assert node.value is not None
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("CANONICAL_COLUMNS is not assigned in the gateway snapshot module")


def test_lane_snapshots_use_the_gateway_column_layout() -> None:
    columns = _gateway_columns()

    assert len(columns) == 13
    assert tuple(reducer_lane._COPY_COLUMNS.split(", ")) == columns
    header = reducer_lane._snapshot_text([], ["r"]).split("\n")[0]
    assert header == f"COPY public.request_cache_entries ({', '.join(columns)}) FROM stdin;"
