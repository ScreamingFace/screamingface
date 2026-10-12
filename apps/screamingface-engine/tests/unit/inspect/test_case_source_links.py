# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Each recorded Case Source carries a browser link to its pinned commit (OME-1524).

FEATURE: the paid smoke's "Where the Cases came from" table links every source.

WHY the link is built when the fetch is recorded, not later from the label text: the text
cannot say what it names. ``TsinghuaC3I/MedXpertQA/Text`` (a dataset config) and
``dgslibisey/MuSiQue/musique_ans_v1.0_dev.jsonl`` (a file) have the same shape; only the
primitive that was called knows which one it read.

Every test that calls a wrapped primitive also takes `no_network`: the recorder describes
the call before running the original, and the original then fails fast and offline.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.case_sources import CaseSource, CaseSourceRecorder  # noqa: E402
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402
from screamingface_engine_inspect.replay_provenance import replay_provenance  # noqa: E402

_SHA: str = "c8f4f8c9465fb69d31a8eae894c3fd509c4ca321"
_HUB: str = "https://huggingface.co/datasets"


@pytest.fixture
def recorder(tmp_path: Path) -> Iterator[CaseSourceRecorder]:
    """An installed recorder, uninstalled at teardown so later tests run on the originals."""

    installed: CaseSourceRecorder = CaseSourceRecorder(tmp_path / "cache")
    installed.install()
    yield installed
    installed.uninstall()


def test_a_dataset_load_with_a_config_links_the_repo_at_the_commit(
    no_network: None, recorder: CaseSourceRecorder
) -> None:
    """The config stays in the location, never in the link (it is not a path on the Hub).

    WHY a stand-in repo, shaped like MedXpertQA's ``TsinghuaC3I/MedXpertQA`` + ``Text``: a
    real repo may sit in the local Hub cache, and the offline original would then succeed.
    """

    import datasets

    with pytest.raises(Exception):  # noqa: B017 — offline original
        datasets.load_dataset("stand-in/medxpert", "Text", split="test", revision=_SHA)

    [source] = recorder.sources
    assert source.location == "stand-in/medxpert/Text"
    assert source.url == f"{_HUB}/stand-in/medxpert/tree/{_SHA}"


def test_a_dataset_load_on_a_branch_gets_no_link(
    no_network: None, recorder: CaseSourceRecorder
) -> None:
    """``main`` moves; a link to it would claim a commit the label never recorded."""

    import datasets

    with pytest.raises(Exception):  # noqa: B017 — offline original
        datasets.load_dataset("acme/sums", split="test", revision="main")

    assert [source.url for source in recorder.sources] == [None]


def test_a_single_file_download_links_the_file_at_the_commit(
    no_network: None, recorder: CaseSourceRecorder
) -> None:
    """MuSiQue's local Task downloads one file; the reader lands on that exact file.

    WHY a stand-in repo with MuSiQue's file name: the real repo may sit in the local Hub
    cache, and the offline original would then succeed.
    """

    import huggingface_hub

    with pytest.raises(Exception):  # noqa: B017 — offline original
        huggingface_hub.hf_hub_download(
            repo_id="stand-in/musique",
            filename="musique_ans_v1.0_dev.jsonl",
            revision=_SHA,
            repo_type="dataset",
        )

    assert [source.url for source in recorder.sources] == [
        f"{_HUB}/stand-in/musique/blob/{_SHA}/musique_ans_v1.0_dev.jsonl"
    ]


def test_a_file_in_a_subfolder_links_the_subfolder_path(
    no_network: None, recorder: CaseSourceRecorder
) -> None:
    """hf_hub_download joins ``subfolder`` and ``filename`` into the path it fetches."""

    import huggingface_hub

    with pytest.raises(Exception):  # noqa: B017 — offline original
        huggingface_hub.hf_hub_download(
            repo_id="acme/sums",
            filename="test.jsonl",
            subfolder="data",
            revision=_SHA,
            repo_type="dataset",
        )

    assert [source.url for source in recorder.sources] == [
        f"{_HUB}/acme/sums/blob/{_SHA}/data/test.jsonl"
    ]


def test_a_dataset_snapshot_links_the_repo_at_the_commit(
    no_network: None, recorder: CaseSourceRecorder
) -> None:
    import huggingface_hub

    with pytest.raises(Exception):  # noqa: B017 — offline original
        huggingface_hub.snapshot_download(
            repo_id="bigbio/med_qa", repo_type="dataset", revision=_SHA
        )

    assert [source.url for source in recorder.sources] == [f"{_HUB}/bigbio/med_qa/tree/{_SHA}"]


@pytest.mark.parametrize("repo_type", [None, "model", "space"])
def test_a_hub_fetch_outside_a_dataset_repo_gets_no_link(
    repo_type: Any, no_network: None, recorder: CaseSourceRecorder
) -> None:
    """A model or Space page lives at another address; a wrong link is worse than none."""

    import huggingface_hub

    with pytest.raises(Exception):  # noqa: B017 — offline original
        huggingface_hub.hf_hub_download(
            repo_id="acme/model", filename="vocab.txt", revision=_SHA, repo_type=repo_type
        )

    assert [source.url for source in recorder.sources] == [None]


def test_a_url_download_links_its_own_address_and_only_over_http(
    tmp_path: Path, no_network: None, recorder: CaseSourceRecorder
) -> None:
    """An http(s) address is already a link; an s3:// one opens nothing in a browser."""

    import inspect_ai.util as inspect_util

    web: str = "https://openaipublic.blob.core.windows.net/simple-evals/mgsm_en.tsv"
    for url in (web, "s3://bucket/data.jsonl"):
        with pytest.raises(Exception):  # noqa: B017 — offline original
            inspect_util.download(url, "4c2f" * 16, tmp_path / "cache" / "x")

    assert [(source.location, source.url) for source in recorder.sources] == [
        (web, web),
        ("s3://bucket/data.jsonl", None),
    ]


def test_the_link_is_not_part_of_a_case_sources_identity() -> None:
    """Kind, location and pin already decide the link, so two records of one fetch stay one
    Case Source, and the importer's comparisons are unchanged."""

    assert CaseSource("url", "https://x/y", "unpinned", url="https://x/y") == CaseSource(
        "url", "https://x/y", "unpinned"
    )


def test_the_label_lists_a_link_only_for_a_source_that_has_one(tmp_path: Path) -> None:
    """No link means no ``url`` key, the same as a hand-built label, never ``"url": null``."""

    recorder: CaseSourceRecorder = CaseSourceRecorder(tmp_path / "cache")
    linked: str = f"{_HUB}/dgslibisey/MuSiQue/blob/{_SHA}/musique_ans_v1.0_dev.jsonl"
    recorder.sources = [
        CaseSource(
            "hugging-face",
            "dgslibisey/MuSiQue/musique_ans_v1.0_dev.jsonl",
            f"revision {_SHA}",
            url=linked,
        ),
        CaseSource("file", "inspect_evals/a/b.jsonl", "inspect_evals==0.20.0"),
    ]
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(task="x:y", case_count=1, case_digest="d")

    block: dict[str, Any] = replay_provenance(recorder, spec, yielded=1, kept=1)

    assert block["sources"] == [
        {
            "kind": "hugging-face",
            "location": "dgslibisey/MuSiQue/musique_ans_v1.0_dev.jsonl",
            "pin": f"revision {_SHA}",
            "phase": "load",
            "url": linked,
        },
        {
            "kind": "file",
            "location": "inspect_evals/a/b.jsonl",
            "pin": "inspect_evals==0.20.0",
            "phase": "load",
        },
    ]
