# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The SAD prefetch: a replay fills its empty cache from GitHub's raw host (OME-1574).

INVARIANT: before a SAD replay's task function runs, its cache already holds the five zips
at exactly the paths SAD's own loader checks, fetched from raw.githubusercontent.com at the
pinned commit and verified against upstream's checksums. The loader's download() then finds
a matching file and never calls GitHub's contents API, whose 60-calls-an-hour anonymous
limit failed image builds with HTTP 403. Every other eval is left alone.

No network: inspect's download() is replaced by a recorder in every test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from inspect_evals.constants import INSPECT_EVALS_CACHE_PATH
from inspect_evals.sad import download_data
from inspect_evals.sad.download_data import SAD_GITHUB_REVISION

from screamingface_engine_inspect import task_replay
from screamingface_engine_inspect.case_source_prefetch import prefetch_case_sources

#: A real SAD Task reference, as the five SAD declarations in prepare.py write it.
_SAD_TASK: str = "inspect_evals.sad.sad:sad_facts_llms"


class _Stop(Exception):
    """Ends the replay child at the task function, so the test never loads a dataset."""


def _record_downloads(monkeypatch: pytest.MonkeyPatch, target: Any) -> list[tuple[str, str, Path]]:
    """Replace ``download`` on ``target`` with a recorder; return the (url, sha256, dest) list."""

    calls: list[tuple[str, str, Path]] = []

    def fake_download(url: str, sha256: str, dest: Path, **_: Any) -> Path:
        """Record the request instead of fetching it."""

        calls.append((url, sha256, Path(dest)))
        return Path(dest)

    monkeypatch.setattr(target, "download", fake_download)
    return calls


def test_a_sad_replay_prefetches_the_five_zips_where_sad_looks_for_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network: None
) -> None:
    """WHY compared with upstream's own loader: a path or checksum that differs by a byte
    would leave the file unfound, and the loader would call the rate-limited API anyway."""

    import inspect_ai.util

    ours: list[tuple[str, str, Path]] = _record_downloads(monkeypatch, inspect_ai.util)
    prefetch_case_sources(_SAD_TASK, tmp_path)
    # What SAD's loader checks, under its own cache root (the pytest process's, not ours).
    theirs: list[tuple[str, str, Path]] = _record_downloads(monkeypatch, download_data)
    download_data._ensure_downloaded()

    assert len(ours) == len(theirs) == 5
    assert {(sha, dest.relative_to(tmp_path)) for _, sha, dest in ours} == {
        (sha, dest.relative_to(INSPECT_EVALS_CACHE_PATH)) for _, sha, dest in theirs
    }
    raw_prefix: str = f"https://raw.githubusercontent.com/LRudL/sad/{SAD_GITHUB_REVISION}/sad/"
    assert {url for url, _, _ in ours} == {
        f"{raw_prefix}{zip_path}structs.zip" for zip_path in download_data.ZIP_PATHS.values()
    }


def test_a_non_sad_replay_prefetches_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network: None
) -> None:
    """WHY: every other eval must fetch exactly as it always has; only SAD hit the limit."""

    import inspect_ai.util

    calls: list[tuple[str, str, Path]] = _record_downloads(monkeypatch, inspect_ai.util)
    prefetch_case_sources("inspect_evals.mgsm.mgsm:mgsm", tmp_path)
    # A package whose name merely starts with "sad" is not SAD.
    prefetch_case_sources("inspect_evals.sadness.sadness:sadness", tmp_path)

    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_the_replay_child_prefetches_into_its_own_cache_before_calling_the_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY before: the task function is what calls SAD's loader; a prefetch after it would
    come too late. WHY its own cache: the child's INSPECT_EVALS_CACHE_DIR is the only place
    the loader looks."""

    events: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        task_replay,
        "prefetch_case_sources",
        lambda task, cache: events.append(("prefetch", (task, cache))),
    )

    def stop_at_task(reference: str) -> Any:
        """Stand-in for resolving the task: records the call, then ends the child."""

        events.append(("resolve", reference))
        raise _Stop

    # Stand-in: stops before the eval module loads, so this proves the order, not the fetch.
    monkeypatch.setattr(task_replay, "_resolve", stop_at_task)
    spec_path: Path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps({"task": _SAD_TASK, "case_count": 249, "case_digest": "0" * 64}),
        encoding="utf-8",
    )
    cache_root: Path = tmp_path / "cache"

    with pytest.raises(_Stop):
        task_replay._replay_in_this_process(spec_path, tmp_path / "result.json", cache_root)

    child_cache: Path = Path(
        task_replay.replay_environment(cache_root, {})["INSPECT_EVALS_CACHE_DIR"]
    )
    assert events == [("prefetch", (_SAD_TASK, child_cache)), ("resolve", _SAD_TASK)]
