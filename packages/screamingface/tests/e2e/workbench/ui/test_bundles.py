"""Workbench UI bundle reader (unit 4 plan, Task 2): discover and load bundles safely."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from workbench.ui.bundles import BundleNotFound, discover, load


def _bundle(root: Path, rel: str, trace: object | None) -> Path:
    d = root / rel
    (d / "logs").mkdir(parents=True)
    if trace is not None:
        (d / "trace.json").write_text(trace if isinstance(trace, str) else json.dumps(trace))
    (d / "logs" / "engine.txt").write_text("trace_id=abc")
    return d


def test_discovers_local_and_run_scoped_bundles_newest_first(tmp_path: Path) -> None:
    old = _bundle(
        tmp_path, "replay/quickstart", {"passed": True, "trace_ids": ["a" * 32], "reasons": []}
    )
    _bundle(
        tmp_path, "runs/r1/local/quickstart", {"passed": False, "trace_ids": [], "reasons": ["x"]}
    )
    os.utime(old / "trace.json", (1, 1))
    found = discover(tmp_path)
    assert [b.key for b in found] == ["runs/r1/local/quickstart", "replay/quickstart"]
    assert found[0].passed is False and found[0].reasons == ("x",)
    assert (found[1].target, found[1].notebook) == ("replay", "quickstart")
    assert found[1].trace_ids == ("a" * 32,)


def test_a_malformed_trace_is_listed_as_unreadable_not_raised(tmp_path: Path) -> None:
    _bundle(tmp_path, "replay/broken", "{not json")
    (only,) = discover(tmp_path)
    assert only.passed is None
    assert load(tmp_path, "replay/broken").trace is None


@pytest.mark.parametrize("trace", ["[1, 2]", {"passed": "yes", "trace_ids": "abc", "reasons": 7}])
def test_a_wrongly_shaped_trace_degrades_instead_of_raising(tmp_path: Path, trace: object) -> None:
    # WHY: a CI artifact is untrusted input — odd shapes must not crash the index page.
    _bundle(tmp_path, "replay/odd", trace)
    (only,) = discover(tmp_path)
    assert (only.passed, only.trace_ids, only.reasons) == (None, (), ())


def test_a_bundle_with_only_an_executed_notebook_is_listed_as_unreadable(tmp_path: Path) -> None:
    d = _bundle(tmp_path, "replay/nbonly", None)
    (d / "executed.ipynb").write_text("{}")
    (only,) = discover(tmp_path)
    assert (only.key, only.passed) == ("replay/nbonly", None)


def test_load_returns_logs_and_notebook_path(tmp_path: Path) -> None:
    d = _bundle(tmp_path, "replay/quickstart", {"passed": True, "trace_ids": [], "reasons": []})
    (d / "executed.ipynb").write_text("{}")
    detail = load(tmp_path, "replay/quickstart")
    assert detail.logs == {"engine": "trace_id=abc"}
    assert detail.notebook_path == (d / "executed.ipynb").resolve()
    assert detail.trace == {"passed": True, "trace_ids": [], "reasons": []}
    assert detail.summary.passed is True


@pytest.mark.parametrize(
    "key", ["../etc", "/etc/passwd", "replay/../../x", "replay/quickstart/../../..", "", "replay"]
)
def test_keys_outside_the_root_or_not_bundles_are_not_found(tmp_path: Path, key: str) -> None:
    _bundle(tmp_path, "replay/quickstart", {"passed": True})
    with pytest.raises(BundleNotFound):
        load(tmp_path, key)


def test_symlinked_directories_are_not_followed(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    _bundle(outside, "replay/leak", {"passed": True})
    (tmp_path / "link").symlink_to(outside)
    assert discover(tmp_path) == []
    with pytest.raises(BundleNotFound):
        load(tmp_path, "link/replay/leak")


def test_symlinked_files_inside_a_bundle_are_not_read(tmp_path: Path) -> None:
    # WHY: an unzipped artifact could carry logs/x.txt -> /etc/passwd; the UI must not serve it.
    secret = tmp_path.parent / f"{tmp_path.name}-secret.txt"
    secret.write_text("SECRET")
    d = _bundle(tmp_path, "replay/quickstart", {"passed": True})
    (d / "logs" / "leak.txt").symlink_to(secret)
    (d / "executed.ipynb").symlink_to(secret)
    detail = load(tmp_path, "replay/quickstart")
    assert "leak" not in detail.logs
    assert detail.notebook_path is None


def test_discovery_stops_at_max_depth(tmp_path: Path) -> None:
    _bundle(tmp_path, "a/b/c/d/e/deep", {"passed": True})
    assert discover(tmp_path) == []
    assert [b.key for b in discover(tmp_path, max_depth=6)] == ["a/b/c/d/e/deep"]


def test_a_missing_root_has_no_bundles(tmp_path: Path) -> None:
    assert discover(tmp_path / "absent") == []
