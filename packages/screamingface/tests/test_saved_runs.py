"""Recovery metadata precedes downloads and retains SDK-only provenance."""

from dataclasses import replace
from datetime import UTC, datetime

from test_transport_artifact_fetch import _candidate

from screamingface._core.ports import _ResultArtifact, _RunOutcome


def outcome():
    return _RunOutcome(
        run_id="run/unsafe",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result_body=None,
        media_type="application/json",
        root_usage=None,
        artifact=_ResultArtifact("a" * 64, 3, "a" * 64),
        trace_id="trace",
    )


def test_manifest_roundtrip_before_download(tmp_path):
    from screamingface._results.store import ResultStore

    store = ResultStore(tmp_path)
    ticket = store.record("https://engine.example", _candidate(), outcome())
    assert ticket.path.parent == tmp_path.resolve() / ticket.key
    assert ticket.manifest.exists()
    assert not ticket.path.exists()
    loaded = store.load(ticket.key)
    assert loaded.outcome == outcome_cached(ticket.outcome)
    assert loaded.candidate.name == "opus"
    assert loaded.candidate.operations == _candidate().operations
    assert loaded.outcome.trace_id == "trace"
    assert store.load("run/unsafe").key == ticket.key


def outcome_cached(value):
    return replace(value, result_path=None)


def test_inline_results_are_saved_before_decode(tmp_path):
    from screamingface._results.store import ResultStore

    store = ResultStore(tmp_path)
    original = replace(outcome(), result_body='{"cases":[]}', artifact=None)
    saved = store.record("https://engine.example", _candidate(), original)
    result = saved.persist_inline()
    assert result.result_body == original.result_body
    assert result.result_path is not None
    assert result.result_path.read_text() == original.result_body
    assert store.load(saved.key).outcome.result_body is None


def test_download_streams_to_file_and_verifies_before_publishing(tmp_path):
    import hashlib

    import httpx

    from screamingface._engine.result_download import download_sync
    from screamingface._results.store import ResultStore

    payload = b'{"cases":[]}'
    original = replace(
        outcome(),
        artifact=_ResultArtifact("a" * 64, len(payload), hashlib.sha256(payload).hexdigest()),
    )
    saved = ResultStore(tmp_path).record("https://engine.example", _candidate(), original)

    def respond(request):
        assert saved.manifest.exists()
        if request.url.path == "/artifacts/" + "a" * 64:
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json={"token": "fresh"})

    with httpx.Client(base_url=saved.engine_url, transport=httpx.MockTransport(respond)) as http:
        result = download_sync(http, saved, mint=lambda: "fresh")
    assert result.result_body is None
    assert result.result_path is not None
    assert result.result_path.read_bytes() == payload
    assert result.artifact == original.artifact


def test_bad_download_retains_ticket_but_publishes_no_result(tmp_path):
    import httpx
    import pytest

    from screamingface._engine.result_download import download_sync
    from screamingface._results.store import ResultStore
    from screamingface.errors import ExecutionError

    saved = ResultStore(tmp_path).record("https://engine.example", _candidate(), outcome())
    with httpx.Client(
        base_url=saved.engine_url,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"bad")),
    ) as http:
        with pytest.raises(ExecutionError, match="integrity"):
            download_sync(http, saved, mint=lambda: "fresh")
    assert saved.manifest.exists()
    assert not saved.path.exists()


def saved_fixture(tmp_path, count=60, expected=None):
    import json
    from dataclasses import asdict

    from recovery_fixtures import large_report

    from screamingface._evaluation.model import _compiled_candidate
    from screamingface._results.store import ResultStore

    source = large_report(count)
    candidate = source.candidates[0]
    compiled = _compiled_candidate(
        name=candidate.name,
        kind=candidate.kind,
        models=candidate.models,
        url4=candidate.url4,
        operations=candidate.operations,
    )
    payload = {
        "schema": "screamingface.candidate-result.v1",
        "benchmark_id": source.benchmark.id,
        "benchmark_revision": source.benchmark.revision,
        "case_count": count,
        "score": candidate.score,
        "coverage": candidate.coverage,
        "metrics": {},
        "failures": [],
        "cases": [c.to_dict() for c in candidate.cases],
    }
    value = _RunOutcome(
        run_id=candidate.run_id,
        started_at=candidate.started_at,
        completed_at=candidate.completed_at,
        result_body=json.dumps(payload),
        media_type="application/json",
        root_usage=candidate.usage,
        client_version=candidate.client_version,
    )
    context = {
        "id": "evaluation",
        "benchmark": asdict(source.benchmark),
        "case_count": count,
        "candidates": expected or [candidate.name],
    }
    saved = ResultStore(tmp_path).record("http://127.0.0.1:1", compiled, value, context)
    saved.persist_inline()
    return source, saved


def test_recover_full_report_without_network_and_export_identical(tmp_path):
    import screamingface as sf

    original, saved = saved_fixture(tmp_path)
    recovered = sf.reports.get(saved.outcome.run_id, directory=tmp_path)
    assert recovered.to_json() == original.to_json()
    assert recovered.candidates[0].cases.by_id(59).output == "answer 59"
    assert sf.reports.list(directory=tmp_path)[0].downloaded
    assert sf.reports.list(directory=tmp_path)[0].size_bytes > 0
    sf.reports.delete(saved.key, directory=tmp_path)
    assert sf.reports.list(directory=tmp_path) == []


def test_recover_partial_names_missing_candidates(tmp_path):
    import pytest

    import screamingface as sf

    _, saved = saved_fixture(tmp_path, expected=["model", "unfinished"])
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get(saved.key, directory=tmp_path)
    assert error.value.code == "candidates_failed"
    assert error.value.details == {"failed": {"unfinished": "result_not_received"}}
    assert error.value.partial_report is not None
    assert len(error.value.partial_report.candidates) == 1


def test_recovery_after_decoder_process_is_killed(tmp_path):
    import os
    import subprocess
    import sys

    import screamingface as sf

    original, saved = saved_fixture(tmp_path)
    script = """
import os, sys
import screamingface as sf
from screamingface._results import cases
original = cases._insert_cases
def crash(events, db):
    original(events, db)
    os._exit(23)
cases._insert_cases = crash
sf.reports.get(sys.argv[1], directory=sys.argv[2])
"""
    child = subprocess.run(
        [sys.executable, "-c", script, saved.key, str(tmp_path)], env=os.environ.copy(), check=False
    )
    assert child.returncode == 23
    assert saved.path.exists()
    assert not saved.path.with_suffix(".sqlite3").exists()
    assert sf.reports.get(saved.key, directory=tmp_path).to_json() == original.to_json()


def test_recovery_can_move_to_another_disk(tmp_path):
    import screamingface as sf

    original, saved = saved_fixture(tmp_path / "original")
    destination = tmp_path / "other-disk"
    recovered = sf.reports.get(saved.key, directory=tmp_path / "original", destination=destination)
    assert recovered.to_json() == original.to_json()
    assert saved.path.exists()
    assert sf.reports.list(directory=destination)[0].downloaded


def test_expired_remote_error_reports_age(tmp_path):
    import httpx
    import pytest

    from screamingface._engine.result_download import download_sync
    from screamingface._results.store import ResultStore
    from screamingface.errors import ExecutionError

    saved = ResultStore(tmp_path).record("https://engine.example", _candidate(), outcome())
    with httpx.Client(
        base_url=saved.engine_url, transport=httpx.MockTransport(lambda _: httpx.Response(404))
    ) as http:
        with pytest.raises(ExecutionError, match="expired.*age") as error:
            download_sync(http, saved, mint=lambda: "fresh")
    assert error.value.code == "result_expired"


def test_disk_full_never_falls_back_to_ram(tmp_path, monkeypatch):
    import httpx
    import pytest

    from screamingface._engine import result_download
    from screamingface._results.store import ResultStore
    from screamingface.errors import ExecutionError

    saved = ResultStore(tmp_path).record("https://engine.example", _candidate(), outcome())

    def full(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(result_download, "NamedTemporaryFile", full)
    with httpx.Client(base_url=saved.engine_url) as http:
        with pytest.raises(ExecutionError, match="disk full") as error:
            result_download.download_sync(http, saved, mint=lambda: "fresh")
    assert error.value.code == "result_storage_failed"
    assert saved.manifest.exists()
    assert not saved.path.exists()


def test_async_local_recovery_is_identical(tmp_path):
    import asyncio

    import screamingface as sf

    original, saved = saved_fixture(tmp_path)
    assert (
        asyncio.run(sf.reports.get_async(saved.key, directory=tmp_path)).to_json()
        == original.to_json()
    )


def test_remote_recovery_sync_and_async_never_starts_a_model(tmp_path):
    import asyncio
    import hashlib

    from protocol_server import protocol_server

    import screamingface as sf
    from screamingface._results.store import ResultStore

    original, local = saved_fixture(tmp_path / "fixture", count=2)
    body = local.path.read_text()
    digest = hashlib.sha256(body.encode()).hexdigest()
    with protocol_server(mode="artifact_result", artifact_body=body) as engine:
        for async_mode in (False, True):
            directory = tmp_path / str(async_mode)
            outcome = replace(
                local.outcome,
                result_body=None,
                artifact=_ResultArtifact(digest, len(body.encode()), digest),
            )
            saved = ResultStore(directory).record(
                engine.url, local.candidate, outcome, local.evaluation
            )
            recovered = (
                asyncio.run(sf.reports.get_async(saved.key, directory=directory))
                if async_mode
                else sf.reports.get(saved.key, directory=directory)
            )
            assert recovered.to_json() == original.to_json()
            assert saved.path.read_text() == body
        assert engine.state.start_attempts == 0
        assert len(engine.state.artifact_requests) == 2
        assert len(engine.state.minted_tokens) == 2


def test_evaluate_and_recover_use_the_same_durable_result(tmp_path, monkeypatch):
    import httpx
    from protocol_server import protocol_server
    from test_client_run import _engine
    from test_evaluation_outcome import valid_body

    import screamingface as sf
    from screamingface._engine.transport import Url4CloudTransport
    from screamingface._results.cases import DiskCases

    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    with protocol_server(mode="artifact_result", artifact_body=valid_body()) as engine:
        transport = Url4CloudTransport(engine.url, save_results=True, reconnect_budget_s=0)
        _match_protocol_url(monkeypatch, transport)
        with sf.Client(
            engine_url=engine.url,
            http_transport=httpx.MockTransport(_engine),
            run_transport=transport,
        ) as client:
            report = client.evaluate(sf.Model("provider/opus"), benchmark="draco", progress=False)
        info = sf.reports.list()[0]
        assert info.id
        assert isinstance(report.candidates[0].cases._items, DiskCases)
        assert sf.reports.get(info.id).to_json() == report.to_json()
        assert len(engine.state.artifact_requests) == 1


def test_explicit_opt_out_retains_legacy_transport_behavior(tmp_path, monkeypatch):
    from protocol_server import protocol_server

    from screamingface._engine.transport import Url4CloudTransport
    from screamingface._results.store import ResultStore

    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    with protocol_server(mode="artifact_result", artifact_body="legacy result") as engine:
        transport = Url4CloudTransport(engine.url, save_results=False)
        try:
            result = transport.run(_candidate(), None)
        finally:
            transport.close()
    assert result.result_body == "legacy result"
    assert result.result_path is None
    assert ResultStore(tmp_path).list() == []


def _match_protocol_url(monkeypatch, transport):
    import protocol_server as protocol

    original_frames = protocol._run_frames
    original_run = transport.run
    selected = [""]

    def frames():
        result = original_frames()
        result[0]["data"] = {"url4": selected[0]}
        return result

    def run(candidate, on_event):
        selected[0] = candidate.url4
        return original_run(candidate, on_event)

    monkeypatch.setattr(protocol, "_run_frames", frames)
    monkeypatch.setattr(transport, "run", run)


def test_invalid_saved_artifact_id_never_makes_an_http_request(tmp_path):
    import httpx
    import pytest

    from screamingface._engine.result_download import download_sync
    from screamingface._results.store import ResultStore
    from screamingface.errors import ExecutionError

    original = replace(outcome(), artifact=_ResultArtifact("../other", 3, "a" * 64))
    saved = ResultStore(tmp_path).record("https://engine.example", _candidate(), original)
    requests = []
    with httpx.Client(
        base_url=saved.engine_url,
        transport=httpx.MockTransport(
            lambda request: (requests.append(request), httpx.Response(200))[1]
        ),
    ) as http:
        with pytest.raises(ExecutionError, match="artifact"):
            download_sync(http, saved, mint=lambda: "fresh")
    assert requests == []
    assert not saved.path.exists()


def test_recovery_preserves_failure_codes_and_remediation(tmp_path):
    import pytest

    import screamingface as sf

    _, saved = saved_fixture(tmp_path)
    saved.path.unlink()  # Simulate interruption before an inline result was persisted.
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get(saved.key, directory=tmp_path)
    assert isinstance(error.value.details, dict)
    assert error.value.details["failed"] == {"model": "result_unavailable"}
    assert "Inline result" in error.value.details["failure_messages"]["model"]
    assert isinstance(error.value.__cause__, sf.ExecutionError)


def test_saved_reports_group_candidates_and_delete_the_whole_report(tmp_path):
    import screamingface as sf
    from screamingface._evaluation.model import _compiled_candidate
    from screamingface._results.store import ResultStore

    _, first = saved_fixture(tmp_path, expected=["model", "second"])
    second_candidate = _compiled_candidate(
        name="second",
        kind=first.candidate.kind,
        models=first.candidate.models,
        url4=first.candidate.url4,
        operations=first.candidate.operations,
    )
    second = ResultStore(tmp_path).record(
        first.engine_url,
        second_candidate,
        replace(first.outcome, run_id="second-run"),
        first.evaluation,
    )
    second.persist_inline()
    entries = sf.reports.list(directory=tmp_path)
    assert len(entries) == 1
    assert entries[0].id == "evaluation"
    assert entries[0].candidates == ("model", "second")
    assert entries[0].downloaded
    loaded = sf.reports.get(entries[0].id, directory=tmp_path)
    assert [c.name for c in loaded.candidates] == ["model", "second"]
    assert loaded.candidates[1].cases.by_id(59).output == "answer 59"
    sf.reports.delete(entries[0].id, directory=tmp_path)
    assert sf.reports.list(directory=tmp_path) == []
    assert not first.manifest.exists() and not second.manifest.exists()


def test_saved_report_list_keeps_independent_and_incomplete_evaluations(tmp_path):
    import pytest

    import screamingface as sf
    from screamingface._results.store import ResultStore

    _, first = saved_fixture(tmp_path, expected=["model", "missing"])
    assert first.evaluation is not None
    other = ResultStore(tmp_path).record(
        first.engine_url,
        first.candidate,
        replace(first.outcome, run_id="other-run"),
        {**first.evaluation, "id": "other", "candidates": ["model"]},
    )
    other.persist_inline()
    standalone = ResultStore(tmp_path).record(
        first.engine_url,
        first.candidate,
        replace(first.outcome, run_id="standalone"),
    )
    standalone.persist_inline()
    entries = {entry.id: entry for entry in sf.reports.list(directory=tmp_path)}
    assert set(entries) == {"evaluation", "other", standalone.key}
    assert not entries["evaluation"].downloaded
    assert entries["other"].downloaded and entries[standalone.key].downloaded
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get("evaluation", directory=tmp_path)
    assert error.value.partial_report is not None
    assert isinstance(error.value.details, dict)
    assert error.value.details["failed"] == {"missing": "result_not_received"}
    with pytest.raises(KeyError):
        sf.reports.get("unknown", directory=tmp_path)
    sf.reports.delete("other", directory=tmp_path)
    assert set(entry.id for entry in sf.reports.list(directory=tmp_path)) == {
        "evaluation",
        standalone.key,
    }
