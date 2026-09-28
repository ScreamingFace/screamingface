"""Run evidence, not the exporting installation, owns Client provenance (OME-416)."""

import json
from pathlib import Path

import pytest
from test_answer_seed_report import candidate, report
from test_client_run import _ReplayTransport
from test_engine_contract import URL4, frame

from screamingface._engine.contract import _RunState
from screamingface._evaluation.model import _compiled_candidate, _compiled_operation
from screamingface._evaluation.results import report_from_url4_outcome


def decoded(
    versions: list[object], *, source: str = "/trace/run_1/node/root", advisory: bool = False
):
    recipe = _compiled_candidate(
        name="sample",
        kind="model",
        models=["provider/model"],
        url4=URL4,
        operations=[_compiled_operation(id="op_model", kind="model", label="Model", depends_on=())],
    )
    body = _ReplayTransport().run(recipe, None).result_body
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    seq = 2
    for version in versions:
        raw = frame(
            "ai.url4.log",
            {
                "severity_text": "INFO",
                "severity_number": 9,
                "body": "Client software version",
                "attributes": {"screamingface.client.version": version},
            },
            sequence=None if advisory else seq,
            source=source,
        )
        state.accept(raw)
        if not advisory:
            state.accept(raw)
            seq += 1
    state.accept(
        frame("ai.url4.result", {"body": body, "media_type": "application/json"}, sequence=seq)
    )
    outcome = state.accept(
        frame("ai.url4.terminated", {"status": "succeeded", "error": None}, sequence=seq + 1)
    ).outcome
    assert outcome is not None
    return report_from_url4_outcome(recipe, outcome)


def test_engine_version_survives_report_and_file_export(tmp_path: Path):
    value = decoded(["0.1.2+original"])
    assert value.candidates[0].client_version == "0.1.2+original"
    path = tmp_path / "report.json"
    value.export(path)
    payload = json.loads(path.read_text())
    assert payload["candidates"][0]["client_version"] == "0.1.2+original"
    assert value.candidates[0].score == 1.0


@pytest.mark.parametrize(
    "versions", [[], [None], [42], [""], ["x" * 129], ["secret\nvalue"], ["é"], ["a", "b", "a"]]
)
def test_missing_invalid_or_conflicting_evidence_is_unknown(versions):
    value = decoded(versions)
    assert value.candidates[0].client_version is None
    assert json.loads(value.to_json())["candidates"][0]["client_version"] is None


def test_child_and_advisory_logs_cannot_stamp_root():
    assert decoded(["1.0"], source="/trace/run_1/node/child").candidates[0].client_version is None
    assert decoded(["1.0"], advisory=True).candidates[0].client_version is None


def test_independent_runs_and_repeated_equal_evidence():
    assert decoded(["1.0", "1.0"]).candidates[0].client_version == "1.0"
    assert decoded(["2.0"]).candidates[0].client_version == "2.0"
    assert decoded([]).candidates[0].client_version is None


def test_manual_candidate_defaults_unknown():
    assert candidate("sample").client_version is None
    assert (
        json.loads(report(candidate("sample")).to_json())["candidates"][0]["client_version"] is None
    )


@pytest.mark.parametrize("version", ["1.2.3", "0.0.0+source", "x" * 128])
def test_public_candidate_preserves_valid_tokens(version):
    from inspect import signature

    from screamingface import CandidateResult

    original = candidate("sample")
    fields = {name: getattr(original, name) for name in signature(CandidateResult).parameters}
    fields["client_version"] = version
    assert CandidateResult(**fields).to_dict()["client_version"] == version


@pytest.mark.parametrize("bad", [42, True, "", "x" * 129, "has space", "a\nb"])
def test_public_candidate_rejects_invalid_tokens(bad):
    from inspect import signature

    from screamingface import CandidateResult

    original = candidate("sample")
    fields = {name: getattr(original, name) for name in signature(CandidateResult).parameters}
    fields["client_version"] = bad
    with pytest.raises(ValueError, match="client_version"):
        CandidateResult(**fields)
