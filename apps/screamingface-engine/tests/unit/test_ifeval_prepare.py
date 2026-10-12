"""IFEval asset preparation — pinned dataset rows into the private runtime layout.

`build` verifies every row against the vendored official dataset, so fixture rows are
REAL official rows (via `official_rows`) — synthetic rows would be rejected as drift.
"""

from __future__ import annotations

import json
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.ifeval.prepare import (
    PrepareError,
    build,
    official_rows,
    prepare_nltk,
    strip_nulls,
)


def test_strip_nulls_removes_only_none_valued_kwargs() -> None:
    # WHY: a raw HF `datasets` load pads every kwargs dict with all-None keys; passing a
    # None through build_description would crash a checker whose default is a real value.
    stripped = strip_nulls(
        [
            {"num_words": None, "relation": "at least"},
            {"num_highlights": 2, "section_spliter": None},
            {},
        ]
    )

    assert stripped == [{"relation": "at least"}, {"num_highlights": 2}, {}]


def test_build_emits_public_cases_and_private_instruction_specs(tmp_path: Path) -> None:
    rows = official_rows()[:2]

    summary = build(rows, tmp_path, expected_count=2)

    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    # Case ids ARE the official IFEval keys, in the official file order.
    assert cases == [
        {"id": rows[0]["key"], "input": rows[0]["prompt"]},
        {"id": rows[1]["key"], "input": rows[1]["prompt"]},
    ]
    # INVARIANT: cases.json carries NO instruction ids or kwargs. The client sees only the
    # prompt; the machine-checkable constraints stay in the image so a Candidate cannot be
    # tuned against the answer key.
    assert "instruction_id_list" not in json.dumps(cases)
    spec = json.loads(
        (tmp_path / "instructions" / f"{rows[0]['key']}.json").read_text(encoding="utf-8")
    )
    assert spec["prompt"] == rows[0]["prompt"]
    assert spec["instruction_id_list"] == rows[0]["instruction_id_list"]
    assert spec["kwargs"] == strip_nulls(rows[0]["kwargs"])
    assert summary == {"cases": 2, "patched_keys": [], "out": str(tmp_path)}


def test_build_preserves_positional_parallelism(tmp_path: Path) -> None:
    # An HF-style row: same official content, but every kwargs dict padded with a
    # None-valued key (schema uniformity). The emitted spec must stay positionally
    # parallel with the padding stripped.
    official = official_rows()[0]
    row = dict(official, kwargs=[dict(kwargs, unused=None) for kwargs in official["kwargs"]])

    build([row], tmp_path, expected_count=1)

    spec = json.loads(
        (tmp_path / "instructions" / f"{official['key']}.json").read_text(encoding="utf-8")
    )
    assert len(spec["instruction_id_list"]) == len(spec["kwargs"])
    assert spec["kwargs"] == strip_nulls(official["kwargs"])
    assert all("unused" not in kwargs for kwargs in spec["kwargs"])


def test_build_rejects_a_count_mismatch(tmp_path: Path) -> None:
    with pytest.raises(PrepareError):
        build([official_rows()[0]], tmp_path, expected_count=541)


def test_build_rejects_an_empty_prompt(tmp_path: Path) -> None:
    # INVARIANT: an empty prompt never reaches the emitted assets — it now fails the
    # official-dataset verification (unknown prompt drift) before any file is written.
    with pytest.raises(PrepareError):
        build([dict(official_rows()[0], prompt="")], tmp_path, expected_count=1)


def test_prepare_nltk_authorizes_the_target_before_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: nltk>=3.10 rejects download targets not registered in nltk.data.path
    # ("Security Violation: Unauthorized path") — the target must be authorized first,
    # or every fresh image build fails.
    import nltk

    downloads: list[str] = []

    def fake_download(resource: str, *, quiet: bool, download_dir: str) -> bool:
        downloads.append(resource)
        return str(tmp_path / "nltk_data") in nltk.data.path

    monkeypatch.setattr(nltk, "download", fake_download)

    summary = prepare_nltk(tmp_path)

    assert downloads == ["punkt", "punkt_tab"]
    assert summary == {"nltk_data": str(tmp_path / "nltk_data")}


def test_build_rejects_skewed_instruction_kwargs_lengths(tmp_path: Path) -> None:
    # INVARIANT: kwargs must stay positionally parallel to instruction_id_list — a
    # truncated kwargs list is rejected (as kwargs drift from the official dataset).
    row = dict(official_rows()[0], kwargs=[])

    with pytest.raises(PrepareError):
        build([row], tmp_path, expected_count=1)


def test_a_prepared_bundle_records_where_its_cases_came_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The block names both places IFEval's Case text comes from: the Hub pin and the official file.

    WHY the vendored official file is a source: its text wins over the Hub's on key 2785, so
    that Case's prompt comes from it, at the verifier commit it was copied from.
    """
    from _bundle_provenance_checks import (
        assert_hand_built_block,
        hugging_face_source,
        watch_provenance_writes,
    )

    from screamingface_engine.benchmarks.ifeval import definition
    from screamingface_engine.benchmarks.ifeval import prepare as module

    rows: list[dict] = official_rows()[:2]
    # WHY these stand-ins: the full 541-row download and the nltk corpus need the network; two
    # real official rows go through the same build, and the corpus is not a Case source.
    monkeypatch.setattr(module, "CASE_COUNT", len(rows))
    monkeypatch.setattr(module, "load_rows", lambda _limit=None: rows)
    monkeypatch.setattr(module, "prepare_nltk", lambda out: {"nltk_data": str(out / "nltk_data")})
    writes: list[bool] = watch_provenance_writes(monkeypatch, module)
    # WHY derived, not typed: each vendored file's banner cites its real upstream path, so a
    # location that drifts from it (a 404 for on-call) fails here instead of matching a copy.
    vendor: Traversable = resources.files("screamingface_engine.benchmarks.ifeval.vendor")
    banner: str = vendor.joinpath("instructions.py").read_text(encoding="utf-8").splitlines()[1]
    upstream_folder: str = banner.split(f"{definition.VERIFIER_REVISION}/", 1)[1].rsplit("/", 1)[0]

    summary: dict = module.prepare(tmp_path)

    assert_hand_built_block(
        tmp_path,
        summary,
        writes,
        sources=[
            hugging_face_source("google/IFEval", definition.DATASET_REVISION),
            {
                "kind": "file",
                "location": (
                    f"{definition.VERIFIER_REPOSITORY}/{upstream_folder}/data/input_data.jsonl"
                ),
                "pin": f"commit {definition.VERIFIER_REVISION}",
                "phase": "load",
                "url": (
                    f"https://github.com/{definition.VERIFIER_REPOSITORY}/blob/"
                    f"{definition.VERIFIER_REVISION}/{upstream_folder}/data/input_data.jsonl"
                ),
            },
        ],
        yielded=2,
        kept=2,
        case_texts=[rows[0]["prompt"], rows[1]["prompt"]],
    )
