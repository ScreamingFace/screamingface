"""Ambiguous saved names cannot relabel answers or hide retained storage."""

import hashlib
import json
import shutil
from dataclasses import replace

import pytest
from test_persistence_followup import pair

import screamingface as sf
from screamingface._evaluation.model import _compiled_candidate
from screamingface._results.store import ResultStore, atomic_json


def _duplicate_group(directory, *, duplicate_first, malformed=False, unaffected=True):
    _, first, second = pair(directory)
    store = ResultStore(directory)
    body = json.loads(second.path.read_text())
    body["cases"][0]["output"] = "SECOND CANDIDATE ANSWER"
    shutil.rmtree(second.path.parent)
    # WHY: exercise both real saved-key orders without depending on fixture hashes.
    run_id = next(
        f"duplicate-{index}"
        for index in range(100)
        if (
            hashlib.sha256(f"{second.engine_url}\nduplicate-{index}".encode()).hexdigest()
            < first.key
        )
        == duplicate_first
    )
    assert first.evaluation is not None
    context = {**first.evaluation}
    if unaffected:
        context["candidates"] = [*context["candidates"], "unaffected"]
    first = store.record(first.engine_url, first.candidate, first.outcome, context)
    second = store.record(
        second.engine_url, second.candidate, replace(second.outcome, run_id=run_id), context
    )
    second.path.write_text(json.dumps(body))
    data = json.loads(second.manifest.read_text())
    data["candidate"]["name"] = first.candidate.name
    if malformed:
        data["outcome"]["cache_saved_cost_usd"] = "broken"
    atomic_json(second.manifest, data)
    atomic_json(directory / "evaluations" / "evaluation.json", context)
    if unaffected:
        candidate = _compiled_candidate(
            name="unaffected",
            kind=first.candidate.kind,
            models=first.candidate.models,
            url4=first.candidate.url4,
            operations=first.candidate.operations,
        )
        healthy = store.record(
            first.engine_url, candidate, replace(first.outcome, run_id="healthy-third"), context
        )
        healthy.path.write_bytes(first.path.read_bytes())
    return first, second


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("duplicate_first", [False, True])
@pytest.mark.parametrize("malformed", [False, True])
async def test_duplicate_claims_preserve_only_unambiguous_candidates(
    tmp_path, asynchronous, duplicate_first, malformed
):
    first, second = _duplicate_group(tmp_path, duplicate_first=duplicate_first, malformed=malformed)
    assert (second.key < first.key) == duplicate_first
    with pytest.raises(sf.ExecutionError) as caught:
        if asynchronous:
            await sf.reports.get_async("evaluation", directory=tmp_path)
        else:
            sf.reports.get("evaluation", directory=tmp_path)
    # INVARIANT: matching membership does not identify which run owns a duplicate name.
    assert caught.value.code == "candidates_failed"
    assert isinstance(caught.value.details, dict)
    assert caught.value.details["failed"] == {
        "model": "result_metadata_invalid",
        "second": "result_not_received",
    }
    assert "duplicate" in caught.value.details["failure_messages"]["model"].lower()
    partial = caught.value.partial_report
    assert partial is not None
    assert [(c.name, c.run_id, c.cases[0].output) for c in partial.candidates] == [
        ("unaffected", "healthy-third", "answer 0")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_duplicate_claims_without_other_success_have_no_partial_report(
    tmp_path, asynchronous
):
    _duplicate_group(tmp_path, duplicate_first=False, unaffected=False)
    with pytest.raises(sf.ExecutionError) as caught:
        if asynchronous:
            await sf.reports.get_async("evaluation", directory=tmp_path)
        else:
            sf.reports.get("evaluation", directory=tmp_path)
    assert caught.value.code == "candidates_failed"
    assert isinstance(caught.value.details, dict)
    assert caught.value.details["failed"]["model"] == "result_metadata_invalid"
    assert caught.value.partial_report is None


@pytest.mark.parametrize("corrupt_names", [(), ("model",), ("second",), ("model", "second")])
def test_listing_counts_every_retained_member_directory(tmp_path, corrupt_names):
    _, first, second = pair(tmp_path)
    atomic_json(tmp_path / "evaluations" / "evaluation.json", first.evaluation)
    for run in (first, second):
        if run.candidate.name in corrupt_names:
            data = json.loads(run.manifest.read_text())
            data["outcome"]["cache_saved_cost_usd"] = "broken"
            atomic_json(run.manifest, data)
    transient = second.path.parent / ".pending-download"
    transient.write_bytes(b"temporary data")
    expected_size = sum(
        path.stat().st_size
        for run in (first, second)
        for path in run.path.parent.iterdir()
        if not path.name.startswith(".")
    )
    entry = sf.reports.list(directory=tmp_path)[0]
    assert entry.candidates == ("model", "second")
    # INVARIANT: invalid metadata still consumes retained disk space.
    assert entry.size_bytes == expected_size
    assert entry.downloaded == (not corrupt_names)
