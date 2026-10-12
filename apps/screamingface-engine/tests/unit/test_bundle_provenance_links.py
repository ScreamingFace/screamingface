"""The link on each Case Source: a browser address for the source AT its pinned commit (OME-1524).

FEATURE: the paid smoke's "Where the Cases came from" table, where each source is one click
from the exact data a Benchmark was built from.

INVARIANT: a link is built only for a full 40-hex commit. A branch, a tag or a short sha moves
or is ambiguous, so a link to it would claim more than the label knows; such a source gets no
link and the table shows it as plain text.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.bundle_provenance import (
    github_file_url,
    hugging_face_source,
    hugging_face_url,
)

_SHA: str = "7e7c465a68eb2b866926bfa59c8c9d17a8daba65"


def test_a_dataset_repo_links_its_tree_at_the_commit() -> None:
    """A dataset load reads the repo, so the link is the repo's file listing at that commit."""

    assert hugging_face_url("TsinghuaC3I/MedXpertQA", _SHA) == (
        f"https://huggingface.co/datasets/TsinghuaC3I/MedXpertQA/tree/{_SHA}"
    )


def test_one_file_links_the_file_itself_at_the_commit() -> None:
    """A single-file download lands the reader on the exact file (MuSiQue's dev split)."""

    assert hugging_face_url("dgslibisey/MuSiQue", _SHA, file="musique_ans_v1.0_dev.jsonl") == (
        f"https://huggingface.co/datasets/dgslibisey/MuSiQue/blob/{_SHA}/musique_ans_v1.0_dev.jsonl"
    )


@pytest.mark.parametrize(
    "revision",
    ["main", "v1.0", _SHA[:8], _SHA.upper(), _SHA + "0", ""],
    ids=["branch", "tag", "short-sha", "upper-case", "41-hex", "empty"],
)
def test_anything_but_a_full_commit_gets_no_link(revision: str) -> None:
    """A moving or ambiguous revision would make the link claim more than the pin does."""

    assert hugging_face_url("acme/sums", revision) is None
    assert github_file_url("acme/tools", revision, "data/x.jsonl") is None


@pytest.mark.parametrize(
    "repo_id",
    ["json", "/abs/path", "./local", "acme/sums/main", "acme/", "/sums"],
    ids=["builder-name", "absolute-path", "relative-path", "with-config", "no-name", "no-owner"],
)
def test_only_an_owner_slash_name_repo_gets_a_link(repo_id: str) -> None:
    """load_dataset also takes builder names ("json") and local paths, which have no Hub page."""

    assert hugging_face_url(repo_id, _SHA) is None


def test_a_vendored_github_file_links_the_file_at_the_commit() -> None:
    """IFEval's official input file: only the hand-built preparer knows the host is GitHub."""

    assert github_file_url(
        "josejg/instruction_following_eval",
        _SHA,
        "instruction_following_eval/data/input_data.jsonl",
    ) == (
        "https://github.com/josejg/instruction_following_eval/blob/"
        f"{_SHA}/instruction_following_eval/data/input_data.jsonl"
    )


def test_a_config_is_not_a_path_so_the_source_links_the_repo() -> None:
    """MedXpertQA's location keeps its config (the label's string is unchanged), and the link
    drops it: huggingface.co/datasets/TsinghuaC3I/MedXpertQA/Text is a 404."""

    source: dict[str, str] = hugging_face_source("TsinghuaC3I/MedXpertQA", _SHA, config="Text")

    assert source == {
        "kind": "hugging-face",
        "location": "TsinghuaC3I/MedXpertQA/Text",
        "pin": f"revision {_SHA}",
        "phase": "load",
        "url": f"https://huggingface.co/datasets/TsinghuaC3I/MedXpertQA/tree/{_SHA}",
    }


def test_a_source_pinned_to_a_branch_carries_no_url_key() -> None:
    """No link means no key at all, so a reader never meets a null where it expects a string."""

    assert "url" not in hugging_face_source("acme/sums", "main")
