"""Unicode validation must never silently rewrite saved candidate values."""

import json

import pytest
from recovery_fixtures import large_report
from test_persistence_followup import pair

import screamingface as sf
from screamingface._results.cases import index_result
from screamingface._results.store import atomic_json


@pytest.mark.parametrize("value", ["\ud800", "\udfff", "x\ud800y", "\ud800\ud800"])
def test_index_rejects_unpaired_surrogates(tmp_path, value):
    case = large_report(1).candidates.only.cases[0].to_dict()
    case["output"] = value
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"cases": [case]}))
    with pytest.raises(sf.ExecutionError, match="surrogate"):
        index_result(path)
    assert not path.with_suffix(".sqlite3").exists()


@pytest.mark.parametrize("value", ["😀", r"\ud800", r"\\ud800", 'a"\\b', "café"])
def test_index_preserves_valid_unicode_and_literal_escapes(tmp_path, value):
    case = large_report(1).candidates.only.cases[0].to_dict()
    case["output"] = value
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"cases": [case]}))
    _, cases = index_result(path)
    assert cases[0].output == value


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_unicode_failure_preserves_healthy_sibling(tmp_path, asynchronous):
    original, healthy, damaged = pair(tmp_path)
    atomic_json(tmp_path / "evaluations" / "evaluation.json", healthy.evaluation)
    body = json.loads(damaged.path.read_text())
    body["cases"][0]["output"] = "x\ud800y"
    damaged.path.write_text(json.dumps(body))
    with pytest.raises(sf.ExecutionError) as caught:
        if asynchronous:
            await sf.reports.get_async("evaluation", directory=tmp_path)
        else:
            sf.reports.get("evaluation", directory=tmp_path)
    assert caught.value.code == "candidates_failed"
    assert isinstance(caught.value.details, dict)
    assert set(caught.value.details["failed"]) == {"second"}
    assert caught.value.partial_report is not None
    assert caught.value.partial_report.to_dict() == original.to_dict()


@pytest.mark.parametrize("offset", range(65525, 65542))
@pytest.mark.parametrize("escaped", [rb"\uD83D\uDE00", rb"\\ud800"])
def test_valid_escape_tokens_survive_read_boundaries(tmp_path, offset, escaped):
    from screamingface._results.unicode_validation import validate_unicode

    path = tmp_path / "result.json"
    path.write_bytes(b'"' + b"x" * (offset - 1) + escaped + b'"')
    validate_unicode(path)


@pytest.mark.parametrize("offset", range(65525, 65542))
@pytest.mark.parametrize("escaped", [rb"\uD800", rb"\uDFFF", rb"\uD800x\uDC00"])
def test_unpaired_surrogates_are_rejected_across_read_boundaries(tmp_path, offset, escaped):
    from screamingface._results.unicode_validation import validate_unicode

    path = tmp_path / "result.json"
    path.write_bytes(b'"' + b"x" * (offset - 1) + escaped + b'"')
    with pytest.raises(sf.ExecutionError, match="surrogate"):
        validate_unicode(path)


def test_validation_cannot_reuse_an_index_that_already_replaced_a_surrogate(tmp_path, monkeypatch):
    from screamingface._results import cases

    case = large_report(1).candidates.only.cases[0].to_dict()
    case["output"] = "x\ud800y"
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"cases": [case]}))
    # INVARIANT: old indices with matching receipts must not certify altered Unicode.
    with monkeypatch.context() as context:
        context.setattr(cases, "validate_unicode", lambda _: None)
        _, indexed = index_result(path)
        assert indexed[0].output == "x?y"
    with pytest.raises(sf.ExecutionError, match="surrogate"):
        index_result(path)


def test_unicode_validation_reads_bounded_chunks(tmp_path, monkeypatch):
    import io
    from pathlib import Path

    from screamingface._results.unicode_validation import validate_unicode

    class BoundedStream(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 65536
            return super().read(size)

    path = tmp_path / "result.json"
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: BoundedStream(b" " * 200000))
    validate_unicode(path)
