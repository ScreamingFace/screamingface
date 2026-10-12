"""An optional derived cache saves repeated accounting scans, never defines truth."""

import json
import os

import pytest
from test_accounting_breakdown import replace, result
from test_saved_runs import saved_fixture

import screamingface as sf


def cached(directory):
    from screamingface._results.accounting import saved_accounting_context

    _, saved = saved_fixture(directory, count=3)
    candidate = sf.reports.get(saved.key, directory=directory).candidates[0]
    expected = saved_accounting_context(candidate)
    return saved, candidate, expected, saved.path.with_suffix(".accounting.json")


def test_reopened_disclosure_reuses_cache_without_decoding(tmp_path, monkeypatch):
    from screamingface._results import cases
    from screamingface._ui.accounting_view import run_accounting_note

    saved, candidate, _, cache = cached(tmp_path)
    expected = run_accounting_note(candidate)
    assert cache.exists()

    def forbidden(body):
        raise AssertionError("warm accounting cache decoded a Case")

    monkeypatch.setattr(cases, "_decode", forbidden)
    reopened = sf.reports.get(saved.key, directory=tmp_path)
    assert run_accounting_note(reopened.candidates[0]) == expected


@pytest.mark.parametrize("content", ["broken", "null", '{"version":0}', '{"version":1}'])
def test_invalid_cache_rebuilds(tmp_path, content):
    from screamingface._results.accounting import saved_accounting_context

    _, candidate, expected, cache = cached(tmp_path)
    cache.write_text(content)
    assert saved_accounting_context(candidate) == expected
    assert json.loads(cache.read_text())["version"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_models", []),
        ("judge_models", {"judge": 1}),
        ("consistent", "true"),
        ("unattributed_cost_usd", "NaN"),
        ("unattributed_cost_usd", "-1"),
        ("unattributed_cost_usd", "broken"),
    ],
)
def test_digest_does_not_replace_context_validation(tmp_path, field, value):
    from screamingface._results.accounting import _digest, saved_accounting_context

    _, candidate, expected, cache = cached(tmp_path)
    payload = json.loads(cache.read_text())
    payload["context"][field] = value
    payload["digest"] = _digest(payload["context"])
    cache.write_text(json.dumps(payload))
    assert saved_accounting_context(candidate) == expected


def test_candidate_cost_change_invalidates_cache(tmp_path):
    from screamingface._results.accounting import saved_accounting_context

    _, candidate, _, _ = cached(tmp_path)
    changed = replace(
        candidate,
        cases=candidate.cases._items,
        usage=sf.Usage(cost_usd="1.25"),
        run_cost_status="complete",
    )
    assert changed.cases._disk_path == candidate.cases._disk_path
    assert saved_accounting_context(changed).unattributed_cost_usd == changed.usage.cost_usd


def test_index_change_invalidates_cache(tmp_path, monkeypatch):
    from screamingface._results import accounting

    _, candidate, expected, _ = cached(tmp_path)
    path = candidate.cases._disk_path
    assert path is not None
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
    derive = accounting._accounting_context
    calls = []

    def observe(value):
        calls.append(value)
        return derive(value)

    monkeypatch.setattr(accounting, "_accounting_context", observe)
    assert accounting.saved_accounting_context(candidate) == expected
    assert calls == [candidate]


def test_unwritable_cache_preserves_derived_context(tmp_path, monkeypatch, caplog):
    from screamingface._results import accounting

    _, candidate, expected, cache = cached(tmp_path)
    cache.unlink()

    def fail(*args):
        raise PermissionError("read-only")

    monkeypatch.setattr(accounting, "atomic_json", fail)
    assert accounting.saved_accounting_context(candidate) == expected
    assert "Could not cache report accounting" in caplog.text


def test_in_memory_context_writes_nothing(tmp_path, monkeypatch):
    from screamingface._results.accounting import saved_accounting_context

    monkeypatch.chdir(tmp_path)
    assert saved_accounting_context(result()).consistent
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("version", [True, "1", 2])
def test_cache_version_is_strict_and_rebuilt(tmp_path, version):
    from screamingface._results.accounting import saved_accounting_context

    _, candidate, expected, cache = cached(tmp_path)
    payload = json.loads(cache.read_text())
    payload["version"] = version
    cache.write_text(json.dumps(payload))
    assert saved_accounting_context(candidate) == expected
    rebuilt = json.loads(cache.read_text())["version"]
    assert type(rebuilt) is int and rebuilt == 1


@pytest.mark.parametrize("value", [True, 0, [], {}])
def test_cached_remainder_must_be_decimal_string_or_unknown(tmp_path, value):
    from screamingface._results.accounting import _digest, saved_accounting_context

    _, candidate, expected, cache = cached(tmp_path)
    payload = json.loads(cache.read_text())
    payload["context"]["unattributed_cost_usd"] = value
    payload["digest"] = _digest(payload["context"])
    cache.write_text(json.dumps(payload))
    assert saved_accounting_context(candidate) == expected


@pytest.mark.parametrize("root,remainder", [(None, "0"), (None, "999"), ("1", "999")])
def test_cached_remainder_must_respect_authoritative_root(tmp_path, root, remainder):
    from screamingface._results.accounting import _digest, saved_accounting_context

    _, candidate, _, cache = cached(tmp_path)
    candidate = replace(
        candidate,
        cases=candidate.cases._items,
        usage=sf.Usage(cost_usd=root),
        run_cost_status=None,
    )
    assert candidate.cases._disk_path is not None
    expected = saved_accounting_context(candidate)
    payload = json.loads(cache.read_text())
    payload["context"]["unattributed_cost_usd"] = remainder
    payload["digest"] = _digest(payload["context"])
    cache.write_text(json.dumps(payload))
    assert saved_accounting_context(candidate) == expected


def test_inconsistent_cache_cannot_retain_attribution(tmp_path):
    from screamingface._results.accounting import _digest, saved_accounting_context

    _, candidate, expected, cache = cached(tmp_path)
    payload = json.loads(cache.read_text())
    payload["context"].update(consistent=False, operation_models={"made-up": "model"})
    payload["digest"] = _digest(payload["context"])
    cache.write_text(json.dumps(payload))
    assert saved_accounting_context(candidate) == expected
