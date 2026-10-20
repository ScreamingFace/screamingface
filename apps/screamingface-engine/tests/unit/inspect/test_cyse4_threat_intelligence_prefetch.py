# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The cyse4_threat_intelligence prefetch: a replay stocks upstream's reports folder from the
owner's report mirror, not web.archive.org (OME-1602).

INVARIANT: before the threat_intelligence task function runs, upstream's reports folder
already holds the 19 CrowdStrike reports (unpacked from CrowdStrike's pinned zip by upstream's
own code) and the 26 other report PDFs, fetched from the Hugging Face mirror at its pinned
commit and verified against upstream's own sha256 pins. Upstream's fetch step then finds
every PDF and calls nothing; web.archive.org, which refuses connections partway through a
burst, is never asked.

No network: inspect's download() is replaced by a recorder, and upstream's zip step by a
stand-in, in every test.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_evals")

from inspect_evals.cyberseceval_4 import _data_utils, threat_intelligence  # noqa: E402
from inspect_evals.cyberseceval_4._constants import THREAT_INTEL_PDF_SHA256  # noqa: E402

from screamingface_engine_inspect import import_replay, task_replay  # noqa: E402
from screamingface_engine_inspect.case_source_prefetch import prefetch_case_sources  # noqa: E402

#: The Task reference the cyse4_threat_intelligence declaration in prepare.py writes.
_THREAT_INTEL_TASK: str = (
    "inspect_evals.cyberseceval_4.threat_intelligence:cyse4_threat_intelligence"
)
#: The owner's mirror at the commit the prefetch pins (uploaded 2026-10-20).
_MIRROR_PREFIX: str = (
    "https://huggingface.co/datasets/khoaguin/cyberseceval4-threat-intel-reports/resolve/"
    "ab38cf24125e38b88ef0f2dd866d5d3cc12965cb/pdfs/"
)
#: Stand-in for one of the 19 CrowdStrike reports upstream's zip step unpacks.
_CROWDSTRIKE_REPORT: str = "crowdstrike-stand-in.txt"


def _stub_upstream_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point upstream's cyse4 cache root at the test's folder; return the reports folder.

    Stand-in: upstream resolves the root through platformdirs, which would be the developer's
    real user cache here; the replay child gets a clean one through XDG_CACHE_HOME.
    """

    monkeypatch.delenv(threat_intelligence.THREAT_INTEL_ENV_VAR, raising=False)
    monkeypatch.setattr(_data_utils, "cyse4_cache_root", lambda: tmp_path / "cyberseceval_4")
    return tmp_path / "cyberseceval_4" / "threat_intelligence" / "reports"


def _stub_zip_step(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
    """Replace upstream's CrowdStrike zip step with one that writes a stand-in report.

    Stand-in: the real step fetches CrowdStrike's 58 MB zip from GitHub and unpacks it.
    """

    def unpack(target_dir: Path) -> Path:
        """Record the call and what the folder held, then unpack the stand-in."""

        events.append(f"unpack into a folder holding {len(list(target_dir.glob('*')))} files")
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / _CROWDSTRIKE_REPORT).write_text("CrowdStrike report", encoding="utf-8")
        return target_dir

    monkeypatch.setattr(threat_intelligence, "download_threat_intel_data", unpack)


def _record_downloads(
    monkeypatch: pytest.MonkeyPatch, events: list[str]
) -> list[tuple[str, str, Path]]:
    """Replace inspect's ``download`` with one that writes a stand-in PDF; return the calls.

    Stand-in: each "PDF" is its report id as bytes, and upstream's pin for it is set to that
    content's sha256, so upstream's own skip-if-present check can run for real afterwards.
    """

    import inspect_ai.util

    calls: list[tuple[str, str, Path]] = []

    def fake_download(url: str, sha256: str, dest: Path, **_: Any) -> Path:
        """Record the request and write the stand-in bytes instead of fetching."""

        events.append(f"fetch {Path(dest).name}")
        calls.append((url, sha256, Path(dest)))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(Path(dest).stem.encode())
        return Path(dest)

    for report_id in THREAT_INTEL_PDF_SHA256:
        monkeypatch.setitem(
            THREAT_INTEL_PDF_SHA256, report_id, hashlib.sha256(report_id.encode()).hexdigest()
        )
    monkeypatch.setattr(inspect_ai.util, "download", fake_download)
    return calls


def test_after_the_prefetch_upstreams_own_fetch_step_asks_no_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network: None
) -> None:
    """WHY upstream's real step, not a list of ours: a folder or file name that differs by a
    byte would leave a PDF unfound, and upstream would go to web.archive.org for it."""

    reports_dir: Path = _stub_upstream_cache(monkeypatch, tmp_path)
    events: list[str] = []
    _stub_zip_step(monkeypatch, events)
    _record_downloads(monkeypatch, events)

    prefetch_case_sources(_THREAT_INTEL_TASK, tmp_path / "inspect_evals")

    # Upstream's real fetch step, run against the stocked folder. Its own download() is the
    # real one: it skips a file whose sha256 matches, and no_network fails any real request.
    import inspect_ai._util.download

    monkeypatch.setattr(threat_intelligence, "download", inspect_ai._util.download.download)
    # Stand-in: upstream sleeps 4 s between reports to spare archive.org; nothing is fetched.
    monkeypatch.setattr(threat_intelligence.time, "sleep", lambda _seconds: None)
    questions: Path = (
        Path(threat_intelligence.__file__).parent
        / "threat_intel_reasoning"
        / "report_questions.json"
    )
    threat_intelligence.download_pdfs_from_urls(reports_dir, questions, text_only_ok=True)

    assert sorted(path.name for path in reports_dir.glob("*.pdf")) == sorted(
        f"{report_id}.pdf" for report_id in THREAT_INTEL_PDF_SHA256
    )
    assert (reports_dir / _CROWDSTRIKE_REPORT).exists()


def test_the_prefetch_reads_every_pinned_report_from_the_mirror_at_its_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network: None
) -> None:
    """WHY upstream's pin on each fetch: the mirror is ours, so its bytes are only trusted
    because inspect's download() checks them against the checksum upstream published."""

    reports_dir: Path = _stub_upstream_cache(monkeypatch, tmp_path)
    events: list[str] = []
    _stub_zip_step(monkeypatch, events)
    calls: list[tuple[str, str, Path]] = _record_downloads(monkeypatch, events)

    prefetch_case_sources(_THREAT_INTEL_TASK, tmp_path / "inspect_evals")

    assert len(calls) == len(THREAT_INTEL_PDF_SHA256) == 26
    assert {(url, sha, dest) for url, sha, dest in calls} == {
        (f"{_MIRROR_PREFIX}{report_id}.pdf", sha, reports_dir / f"{report_id}.pdf")
        for report_id, sha in THREAT_INTEL_PDF_SHA256.items()
    }


def test_the_crowdstrike_reports_are_unpacked_before_any_mirrored_pdf_lands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network: None
) -> None:
    """WHY first: upstream unpacks CrowdStrike's zip only into an EMPTY reports folder. A
    folder stocked with the 26 PDFs alone would make it skip the zip, and every CrowdStrike
    question would fail to find its report."""

    _stub_upstream_cache(monkeypatch, tmp_path)
    events: list[str] = []
    _stub_zip_step(monkeypatch, events)
    _record_downloads(monkeypatch, events)

    prefetch_case_sources(_THREAT_INTEL_TASK, tmp_path / "inspect_evals")

    assert events[0] == "unpack into a folder holding 0 files"
    assert len(events) == 1 + 26


def test_a_stocked_reports_folder_is_not_unpacked_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network: None
) -> None:
    """WHY: upstream treats a non-empty folder as already unpacked, and so must the prefetch;
    the 26 PDFs are still checked, and download() skips each one that matches its pin."""

    reports_dir: Path = _stub_upstream_cache(monkeypatch, tmp_path)
    reports_dir.mkdir(parents=True)
    (reports_dir / _CROWDSTRIKE_REPORT).write_text("CrowdStrike report", encoding="utf-8")
    events: list[str] = []
    _stub_zip_step(monkeypatch, events)
    _record_downloads(monkeypatch, events)

    prefetch_case_sources(_THREAT_INTEL_TASK, tmp_path / "inspect_evals")

    assert not any(event.startswith("unpack") for event in events)
    assert len(events) == 26


def test_the_other_cyse4_tasks_get_no_prefetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network: None
) -> None:
    """WHY: malware_analysis and mitre_frr fetch only CrowdStrike's GitHub zip, which has
    never failed; they must fetch exactly as they always have."""

    _stub_upstream_cache(monkeypatch, tmp_path)
    events: list[str] = []
    _stub_zip_step(monkeypatch, events)
    _record_downloads(monkeypatch, events)

    prefetch_case_sources(
        "inspect_evals.cyberseceval_4.malware_analysis:cyse4_malware_analysis", tmp_path
    )
    prefetch_case_sources("inspect_evals.cyberseceval_4.mitre_frr:cyse4_mitre_frr", tmp_path)

    assert events == []


class _Stop(Exception):
    """Ends the import child at the eval module's import, so the test never loads a dataset."""


def test_the_imports_first_run_prefetches_into_its_own_cache_before_importing_the_eval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY the import too: the importer's first run reads the Cases the declaration is sealed
    with; without the prefetch it went to web.archive.org and was refused (2026-10-20), so
    the row could never be imported. WHY before the import: the task function is what calls
    upstream's loader, and the recorder must still see the fetches the eval itself makes."""

    events: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        import_replay,
        "prefetch_case_sources",
        lambda task, cache: events.append(("prefetch", (task, cache))),
    )

    def stop_at_import(module_name: str) -> Any:
        """Stand-in for importing the eval module: records the call, then ends the child."""

        events.append(("import", module_name))
        raise _Stop

    # Stand-in: stops before the eval module loads, so this proves the order, not the fetch.
    monkeypatch.setattr(import_replay, "import_module", stop_at_import)
    cache_root: Path = tmp_path / "cache"
    request_path: Path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps({"task": _THREAT_INTEL_TASK, "task_args": None, "cache_root": str(cache_root)}),
        encoding="utf-8",
    )

    with pytest.raises(_Stop):
        import_replay._replay_in_this_process(request_path, tmp_path / "result.json")

    child_cache: Path = Path(
        task_replay.replay_environment(cache_root, {})["INSPECT_EVALS_CACHE_DIR"]
    )
    assert events == [
        ("prefetch", (_THREAT_INTEL_TASK, child_cache)),
        ("import", _THREAT_INTEL_TASK.partition(":")[0]),
    ]
