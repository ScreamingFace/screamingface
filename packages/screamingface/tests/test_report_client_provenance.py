"""Run evidence, not the exporting installation, owns Client provenance (OME-416).

Which evidence names the caller is the Engine's fold's rule, pinned in
`apps/screamingface-engine/tests/unit/test_candidate_record_evidence_rules.py`; the Client
carries the version the record names onto the Report and its export.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_answer_seed_report import candidate, report
from test_client_run import _ReplayTransport
from test_engine_contract import URL4

from screamingface._evaluation.model import _compiled_candidate, _compiled_operation
from screamingface._evaluation.results import report_from_url4_outcome


def recorded(version: str | None):
    """The Report of a run whose record names ``version`` as its caller's."""
    recipe = _compiled_candidate(
        name="sample",
        kind="model",
        models=["provider/model"],
        url4=URL4,
        operations=[_compiled_operation(id="op_model", kind="model", label="Model", depends_on=())],
    )
    outcome = replace(_ReplayTransport().run(recipe, None), client_version=version)
    return report_from_url4_outcome(recipe, outcome)


def test_engine_version_survives_report_and_file_export(tmp_path: Path):
    value = recorded("0.1.2+original")
    assert value.candidates[0].client_version == "0.1.2+original"
    path = tmp_path / "report.json"
    value.export(path)
    payload = json.loads(path.read_text())
    assert payload["candidates"][0]["client_version"] == "0.1.2+original"
    assert value.candidates[0].score == 1.0


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
