# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The Case Source recorder: one Case Source per top-level fetch, by identity (spec R3).

INVARIANT: a fetch is recorded once however the eval reached the primitive (by module
attribute or by a name imported earlier), and a read from the replay's own cache is never a
Case Source.

Every test that calls a wrapped primitive also takes `no_network`: the recorder describes
the call before running the original, and the original then fails fast and offline.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.case_sources import (  # noqa: E402
    CaseSource,
    CaseSourceRecorder,
    pin_from_url,
)

_COMMIT: str = "84ab72d94318290aad2e4ec820d535a95a1f7552"
_AGIEVAL_URL: str = (
    f"https://raw.githubusercontent.com/ruixiangcui/AGIEval/{_COMMIT}/data/v1_1/lsat-ar.jsonl"
)


@pytest.fixture
def install_recorder() -> Iterator[Callable[[Path], CaseSourceRecorder]]:
    """Install recorders on demand and uninstall every one at teardown.

    WHY a factory: some tests must set the scene (a module that imported a primitive by
    name) BEFORE the recorder installs; WHY teardown: the recorder patches this pytest
    process, and a later test must not run through stale wrappers.
    """

    installed: list[CaseSourceRecorder] = []

    def install(cache_root: Path) -> CaseSourceRecorder:
        """One installed recorder whose cache is `cache_root`."""

        recorder: CaseSourceRecorder = CaseSourceRecorder(cache_root)
        recorder.install()
        installed.append(recorder)
        return recorder

    yield install
    for recorder in reversed(installed):
        recorder.uninstall()


def test_pin_from_url_reads_a_commit_out_of_the_path() -> None:
    assert pin_from_url(_AGIEVAL_URL) == f"commit {_COMMIT}"
    assert (
        pin_from_url("https://openaipublic.blob.core.windows.net/simple-evals/mgsm_en.tsv")
        == "unpinned"
    )


def test_a_url_download_with_a_sha256_is_pinned_by_the_hash(
    tmp_path: Path, no_network: None, install_recorder: Callable[[Path], CaseSourceRecorder]
) -> None:
    """inspect_ai.util.download(url, sha256, dest): mgsm's primitive."""

    recorder: CaseSourceRecorder = install_recorder(tmp_path / "cache")
    import inspect_ai.util as inspect_util

    with pytest.raises(Exception):  # noqa: B017 — the offline original fails; any failure will do
        inspect_util.download("https://example.invalid/mgsm_en.tsv", "ab" * 32, tmp_path / "x")

    assert recorder.sources == [
        CaseSource("url", "https://example.invalid/mgsm_en.tsv", "sha256 " + "ab" * 32)
    ]


def test_the_recorder_rebinds_a_primitive_imported_by_name(
    tmp_path: Path, no_network: None, install_recorder: Callable[[Path], CaseSourceRecorder]
) -> None:
    """Review Focus 2: mgsm binds `download` at import time, before any recorder exists."""

    from inspect_ai.util import download as bound_before_install

    # Stand-in for mgsm's module: it imported `download` by name. It proves the rebind
    # reaches a module-level name; it does not prove a name hidden in a closure is reached.
    stand_in: types.ModuleType = types.ModuleType("stand_in_eval_that_imported_download")
    stand_in.download = bound_before_install  # type: ignore[attr-defined]
    sys.modules[stand_in.__name__] = stand_in
    try:
        recorder: CaseSourceRecorder = install_recorder(tmp_path / "cache")

        assert stand_in.download is not bound_before_install  # type: ignore[attr-defined]
        with pytest.raises(Exception):  # noqa: B017 — offline original
            stand_in.download("https://example.invalid/a.tsv", "cd" * 32, tmp_path / "y")  # type: ignore[attr-defined]
        assert [source.location for source in recorder.sources] == ["https://example.invalid/a.tsv"]
    finally:
        del sys.modules[stand_in.__name__]


def test_a_fetch_inside_a_recorded_fetch_is_not_a_second_case_source(
    tmp_path: Path, no_network: None, install_recorder: Callable[[Path], CaseSourceRecorder]
) -> None:
    """Review Focus 1: agieval's _download_remote calls inspect_ai's file() for the bytes."""

    from inspect_evals.utils import load_dataset as evals_load_dataset

    recorder: CaseSourceRecorder = install_recorder(tmp_path / "cache")

    with pytest.raises(Exception):  # noqa: B017 — offline original
        evals_load_dataset._download_remote(_AGIEVAL_URL, str(tmp_path / "cache" / "lsat-ar.jsonl"))

    assert recorder.sources == [CaseSource("url", _AGIEVAL_URL, f"commit {_COMMIT}")]


def test_a_read_from_the_replay_cache_is_not_a_case_source(
    tmp_path: Path, install_recorder: Callable[[Path], CaseSourceRecorder]
) -> None:
    """Review Focus 3: after downloading, mgsm reads the TSV back from the cache."""

    cache: Path = tmp_path / "cache"
    cache.mkdir()
    (cache / "mgsm_en.tsv").write_text("q\ta\n", encoding="utf-8")
    recorder: CaseSourceRecorder = install_recorder(cache)
    from inspect_ai._util.file import file as inspect_file

    with inspect_file(str(cache / "mgsm_en.tsv"), "r") as handle:
        assert handle.read() == "q\ta\n"

    assert recorder.sources == []


def test_a_file_outside_the_cache_is_a_file_case_source(
    tmp_path: Path, install_recorder: Callable[[Path], CaseSourceRecorder]
) -> None:
    """persistbench reads a file inside the inspect_evals package; a stand-in reads tmp_path."""

    data: Path = tmp_path / "data.jsonl"
    data.write_text("{}\n", encoding="utf-8")
    recorder: CaseSourceRecorder = install_recorder(tmp_path / "cache")
    from inspect_ai._util.file import file as inspect_file

    with inspect_file(str(data), "r"):
        pass

    assert recorder.sources == [CaseSource("file", str(data.resolve()), "unpinned")]


def test_a_file_inside_the_inspect_evals_package_is_pinned_by_its_version(
    tmp_path: Path, install_recorder: Callable[[Path], CaseSourceRecorder]
) -> None:
    """A package file is as pinned as the inspect_evals version the image installs."""

    from importlib.metadata import version

    import inspect_evals

    recorder: CaseSourceRecorder = install_recorder(tmp_path / "cache")
    from inspect_ai._util.file import file as inspect_file

    with inspect_file(str(Path(inspect_evals.__file__)), "r"):
        pass

    assert recorder.sources == [
        CaseSource(
            "file", "inspect_evals/__init__.py", f"inspect_evals=={version('inspect_evals')}"
        )
    ]


def test_a_hugging_face_load_is_pinned_by_its_revision(
    tmp_path: Path, no_network: None, install_recorder: Callable[[Path], CaseSourceRecorder]
) -> None:
    import datasets

    recorder: CaseSourceRecorder = install_recorder(tmp_path / "cache")

    with pytest.raises(Exception):  # noqa: B017 — offline original
        datasets.load_dataset("acme/sums", "main", split="test", revision="c" * 40)

    assert recorder.sources == [
        CaseSource("hugging-face", "acme/sums/main", "revision " + "c" * 40)
    ]


def test_a_hugging_face_snapshot_is_one_case_source_however_many_files_it_fetches(
    tmp_path: Path, no_network: None, install_recorder: Callable[[Path], CaseSourceRecorder]
) -> None:
    """piqa and medqa snapshot the repository; the snapshot is one Case Source."""

    import huggingface_hub

    recorder: CaseSourceRecorder = install_recorder(tmp_path / "cache")

    with pytest.raises(Exception):  # noqa: B017 — offline original
        huggingface_hub.snapshot_download(
            repo_id="bigbio/med_qa", repo_type="dataset", revision="d" * 40
        )

    assert recorder.sources == [CaseSource("hugging-face", "bigbio/med_qa", "revision " + "d" * 40)]


def test_download_manager_urls_are_recorded_and_relative_paths_are_not(
    tmp_path: Path, no_network: None, install_recorder: Callable[[Path], CaseSourceRecorder]
) -> None:
    """D7: piqa's builder fetches two unpinned URLs through datasets' DownloadManager; medqa's
    "downloads" data_clean.zip, a path inside the snapshot already recorded."""

    from datasets.download.download_manager import DownloadManager

    recorder: CaseSourceRecorder = install_recorder(tmp_path / "cache")
    url: str = "https://storage.googleapis.com/x/physicaliqa-train-dev.zip"

    with pytest.raises(Exception):  # noqa: B017 — offline original
        DownloadManager().download({"train": [url], "extra": "data_clean.zip"})

    assert recorder.sources == [CaseSource("url", url, "unpinned")]


def test_uninstall_puts_every_primitive_back(
    tmp_path: Path, install_recorder: Callable[[Path], CaseSourceRecorder]
) -> None:
    """INVARIANT: the recorder leaves the process as it found it."""

    import datasets
    import inspect_ai.util as inspect_util
    from datasets.download.download_manager import DownloadManager
    from inspect_ai._util import file as file_module

    before: tuple[object, ...] = (
        datasets.load_dataset,
        inspect_util.download,
        file_module.file,
        DownloadManager.download,
    )
    recorder: CaseSourceRecorder = CaseSourceRecorder(tmp_path / "cache")
    recorder.install()
    assert inspect_util.download is not before[1]

    recorder.uninstall()

    assert (
        datasets.load_dataset,
        inspect_util.download,
        file_module.file,
        DownloadManager.download,
    ) == before


def test_the_comment_says_when_the_digest_is_the_only_pin() -> None:
    assert CaseSource("url", "https://x/y.jsonl", "unpinned").as_comment() == (
        "url https://x/y.jsonl · pin unpinned (no upstream hash: the Case Digest is the only pin)"
    )
    assert CaseSource("hugging-face", "bigbio/med_qa", "revision " + "d" * 40).as_comment() == (
        f"hugging-face bigbio/med_qa · pin revision {'d' * 40}"
    )


def test_the_generated_comment_puts_the_pin_on_its_own_line() -> None:
    """WHY two lines: the URL line ends with its URL, which the 100-column gate exempts."""

    source: CaseSource = CaseSource("url", _AGIEVAL_URL, f"commit {_COMMIT}")

    assert source.comment_lines() == (f"url {_AGIEVAL_URL}", f"pin commit {_COMMIT}")


def test_a_hugging_face_source_names_its_repository_and_web_page() -> None:
    config_load: CaseSource = CaseSource("hugging-face", "bigbio/med_qa/main", "unpinned")
    one_file: CaseSource = CaseSource("hugging-face", "BBEH/bbeh/data/x.json", "unpinned")

    assert config_load.hub_repo_id() == "bigbio/med_qa"
    assert one_file.hub_repo_id() == "BBEH/bbeh"
    assert config_load.web_url() == "https://huggingface.co/datasets/bigbio/med_qa"


def test_only_a_browsable_source_has_a_web_url() -> None:
    """The BenchmarkSpec dataset_url must be an absolute http(s) URL (definition.py)."""

    assert CaseSource("url", "https://x/y.jsonl", "unpinned").web_url() == "https://x/y.jsonl"
    assert CaseSource("url", "s3://bucket/y.jsonl", "unpinned").web_url() is None
    assert CaseSource("file", "inspect_evals/a/b.jsonl", "inspect_evals==0.20.0").web_url() is None
