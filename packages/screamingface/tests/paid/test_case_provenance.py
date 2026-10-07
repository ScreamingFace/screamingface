"""Free tests: the press page's "Where the Cases came from" section (OME-1492).

INVARIANT: a view, never a verdict. The section reads each bundle's provenance.json and
must never fail or hide the press overview: a missing or unreadable file is one honest
row, not an error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _case_provenance import provenance_markdown

#: The block Case Preparation writes for race_h (values from its declaration). It
#: simulates one prepared bundle; it does not prove the Engine writes this shape, which
#: the Engine's own task-replay tests pin.
_RACE_H: dict[str, Any] = {
    "sources": [
        {
            "kind": "hugging-face",
            "location": "ehovy/race/high",
            "pin": "revision 2fec9fd8a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "phase": "load",
        }
    ],
    "seeds_applied": {"shuffle_seed": 20260917},
    "samples": {"yielded": 3498, "excluded": 0, "kept": 3498},
    "pins": {"inspect-ai": "0.3.263", "inspect-evals": "0.20.0"},
    "seconds": 15.2,
}


def _bundle(root: Path, benchmark: str, block: dict[str, Any] | str) -> None:
    """Write one bundle's provenance.json (a str is written verbatim, for broken files)."""
    folder: Path = root / benchmark
    folder.mkdir(parents=True)
    text: str = block if isinstance(block, str) else json.dumps(block)
    (folder / "provenance.json").write_text(text, encoding="utf-8")


def _row(markdown: str, benchmark: str) -> str:
    """The table row for one Benchmark."""
    return next(line for line in markdown.splitlines() if line.startswith(f"| {benchmark} |"))


def test_an_imported_benchmark_shows_its_commit_seed_and_counts(tmp_path: Path) -> None:
    _bundle(tmp_path, "inspect-race_h", _RACE_H)

    row: str = _row(provenance_markdown(["inspect-race_h"], tmp_path), "inspect-race_h")

    assert "ehovy/race/high @ 2fec9fd8" in row
    assert "2fec9fd8a1b2" not in row  # a short commit, so the table stays readable
    assert "shuffle_seed 20260917" in row
    assert "3498 of 3498" in row
    assert "inspect-evals 0.20.0" in row
    assert "15s" in row


def test_excluded_samples_show_both_counts(tmp_path: Path) -> None:
    """sad_stages_full keeps 797 of 800: the cut must be visible, not only the result."""
    block: dict[str, Any] = {**_RACE_H, "samples": {"yielded": 800, "excluded": 3, "kept": 797}}
    _bundle(tmp_path, "inspect-sad_stages_full", block)

    row: str = _row(
        provenance_markdown(["inspect-sad_stages_full"], tmp_path), "inspect-sad_stages_full"
    )

    assert "797 of 800 (3 excluded)" in row


def test_a_block_without_seeds_or_hub_fetches_still_renders(tmp_path: Path) -> None:
    """agieval reads a URL pinned by commit and forces no seed; the hand-built preparers'
    blocks (OME-1492 PR 3) will look like this too."""
    block: dict[str, Any] = {
        **_RACE_H,
        "sources": [
            {
                "kind": "url",
                "location": "https://example.invalid/a.jsonl",
                "pin": "commit 84ab12cd" + "0" * 32,
            }
        ],
        "seeds_applied": {},
    }
    _bundle(tmp_path, "inspect-agieval_sat_math", block)

    row: str = _row(
        provenance_markdown(["inspect-agieval_sat_math"], tmp_path), "inspect-agieval_sat_math"
    )

    assert "https://example.invalid/a.jsonl @ 84ab12cd" in row
    assert "| — |" in row


def test_a_bundle_without_the_file_reads_not_recorded(tmp_path: Path) -> None:
    """Hand-built bundles until PR 3, and any bundle prepared before this change."""
    row: str = _row(provenance_markdown(["draco"], tmp_path), "draco")

    assert "not recorded" in row


def test_an_unreadable_file_never_breaks_the_overview(tmp_path: Path) -> None:
    """A cut-off or hand-edited file is one honest row; the press verdict is unaffected."""
    _bundle(tmp_path, "inspect-gsm8k", '{"sources": [')
    _bundle(tmp_path, "inspect-mmlu", json.dumps(["not", "a", "block"]))

    markdown: str = provenance_markdown(["inspect-gsm8k", "inspect-mmlu"], tmp_path)

    assert "unreadable" in _row(markdown, "inspect-gsm8k")
    assert "unreadable" in _row(markdown, "inspect-mmlu")


def test_rows_follow_benchmark_name_order(tmp_path: Path) -> None:
    """Boards finish in completion order; this section is a lookup table, so sort it."""
    markdown: str = provenance_markdown(["inspect-mmlu", "draco", "inspect-gsm8k"], tmp_path)

    rows: list[str] = [
        line for line in markdown.splitlines() if line.startswith("| ") and "not recorded" in line
    ]
    assert [row.split(" | ")[0] for row in rows] == ["| draco", "| inspect-gsm8k", "| inspect-mmlu"]


def test_a_non_finite_time_never_breaks_the_overview(tmp_path: Path) -> None:
    """json.loads accepts NaN and Infinity; rounding them raises ValueError/OverflowError,
    which must end as one honest row like any other unreadable block."""
    _bundle(tmp_path, "inspect-race_h", {**_RACE_H, "seconds": float("inf")})
    _bundle(tmp_path, "inspect-gsm8k", {**_RACE_H, "seconds": float("nan")})

    markdown: str = provenance_markdown(["inspect-race_h", "inspect-gsm8k"], tmp_path)

    assert "unreadable" in _row(markdown, "inspect-race_h")
    assert "unreadable" in _row(markdown, "inspect-gsm8k")
