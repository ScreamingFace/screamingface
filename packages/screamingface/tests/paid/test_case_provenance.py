"""Free tests: the press page's "Where the Cases came from" section (OME-1492).

INVARIANT: a view, never a verdict. The section reads each bundle's provenance.json and
must never fail or hide the press overview: a missing or unreadable file is one honest
row, not an error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _case_provenance import copy_labels, provenance_markdown

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


#: A hand-built preparer's block (OME-1492 PR 3): no seed forced, inspect never ran, and the
#: frozen selection drops rows. It simulates one prepared GDPval bundle; the Engine's own
#: prepare tests pin that the preparer writes this shape.
_GDPVAL: dict[str, Any] = {
    "sources": [
        {
            "kind": "hugging-face",
            "location": "openai/gdpval",
            "pin": "revision 11e7900cdcac61bc4daf59e65feb238acda98fbf",
            "phase": "load",
        }
    ],
    "seeds_applied": {},
    "samples": {"yielded": 220, "excluded": 118, "kept": 102},
    "pins": {},
    "seconds": 95.4,
}


def test_a_benchmark_on_a_shared_bundle_reads_that_bundle(tmp_path: Path) -> None:
    """draco-3pass, both HealthBench Benchmarks and gdpval-text have no folder of their own.

    WHY it matters: without the map their rows read "not recorded" while the bundle they
    actually ran on holds a block, which would send on-call looking for a missing file.
    """
    _bundle(tmp_path, "gdpval", _GDPVAL)
    _bundle(
        tmp_path,
        "healthbench",
        {**_GDPVAL, "samples": {"yielded": 525, "excluded": 0, "kept": 525}},
    )
    _bundle(tmp_path, "draco", {**_GDPVAL, "samples": {"yielded": 100, "excluded": 0, "kept": 100}})
    benchmarks: list[str] = [
        "gdpval-text",
        "healthbench-worst30",
        "healthbench-professional",
        "draco-3pass",
        "draco",
    ]

    markdown: str = provenance_markdown(benchmarks, tmp_path)

    assert "102 of 220 (118 excluded)" in _row(markdown, "gdpval-text")
    assert "525 of 525" in _row(markdown, "healthbench-worst30")
    assert "525 of 525" in _row(markdown, "healthbench-professional")
    assert "100 of 100" in _row(markdown, "draco-3pass")
    # A Benchmark whose bundle shares its id still reads its own folder.
    assert "100 of 100" in _row(markdown, "draco")


def test_a_hand_built_block_with_empty_pins_renders(tmp_path: Path) -> None:
    """A hand-built preparer never runs inspect, so its block has no inspect-evals pin."""
    _bundle(tmp_path, "medxpert", {**_GDPVAL, "samples": {"yielded": 3, "excluded": 0, "kept": 3}})

    row: str = _row(provenance_markdown(["medxpert"], tmp_path), "medxpert")

    assert "unreadable" not in row
    assert "openai/gdpval @ 11e7900c" in row
    assert row.endswith("| 3 of 3 | — | 95s |")


# ── OME-1524: each source links to its pinned commit, and the labels ship in the bundle ──

_MUSIQUE_URL: str = (
    "https://huggingface.co/datasets/dgslibisey/MuSiQue/blob/"
    "c8f4f8c9465fb69d31a8eae894c3fd509c4ca321/musique_ans_v1.0_dev.jsonl"
)


def _one_source(source: dict[str, str]) -> dict[str, Any]:
    """A hand-built-shaped block around one Case Source (no seeds, no inspect pins)."""
    return {
        "sources": [source],
        "seeds_applied": {},
        "samples": {"yielded": 2417, "excluded": 0, "kept": 2417},
        "pins": {},
        "seconds": 3.0,
    }


def test_a_source_with_a_link_reads_as_that_link(tmp_path: Path) -> None:
    """The owner opens the exact file the Cases came from in one click."""
    _bundle(
        tmp_path,
        "musique",
        _one_source(
            {
                "kind": "hugging-face",
                "location": "dgslibisey/MuSiQue/musique_ans_v1.0_dev.jsonl",
                "pin": "revision c8f4f8c9465fb69d31a8eae894c3fd509c4ca321",
                "phase": "load",
                "url": _MUSIQUE_URL,
            }
        ),
    )

    row: str = _row(provenance_markdown(["musique"], tmp_path), "musique")

    assert f"[dgslibisey/MuSiQue/musique_ans_v1.0_dev.jsonl @ c8f4f8c9]({_MUSIQUE_URL})" in row


def test_a_source_without_a_link_stays_plain_text(tmp_path: Path) -> None:
    """A label written before links existed, or an unpinned source, reads as it always did."""
    _bundle(tmp_path, "inspect-race_h", _RACE_H)

    row: str = _row(provenance_markdown(["inspect-race_h"], tmp_path), "inspect-race_h")

    assert "| ehovy/race/high @ 2fec9fd8 |" in row
    assert "](" not in row


def test_a_pipe_or_bracket_in_a_source_never_breaks_the_row(tmp_path: Path) -> None:
    """INVARIANT: one row per Benchmark, six cells. A ``|`` in a location would otherwise open
    a seventh cell, and a ``]`` or ``)`` would end the link early."""
    _bundle(
        tmp_path,
        "odd",
        _one_source(
            {
                "kind": "url",
                "location": "https://x.test/a|b]c.jsonl",
                "pin": "unpinned",
                "phase": "load",
                "url": "https://x.test/a|b]c (1).jsonl",
            }
        ),
    )

    row: str = _row(provenance_markdown(["odd"], tmp_path), "odd")

    assert (
        r"[https://x.test/a\|b\]c.jsonl @ unpinned](https://x.test/a%7Cb%5Dc%20%281%29.jsonl)"
        in row
    )
    assert row.replace(r"\|", "").count("|") == 7


def test_only_a_web_address_becomes_a_link(tmp_path: Path) -> None:
    """The label is build data, not code we control: a ``javascript:`` url is shown as text."""
    _bundle(
        tmp_path,
        "odd",
        _one_source(
            {
                "kind": "url",
                "location": "x",
                "pin": "unpinned",
                "phase": "load",
                "url": "javascript:alert(1)",
            }
        ),
    )

    row: str = _row(provenance_markdown(["odd"], tmp_path), "odd")

    assert "| x @ unpinned |" in row
    assert "javascript" not in row


def test_each_picked_benchmarks_label_is_copied_for_the_debug_bundle(tmp_path: Path) -> None:
    """The labels outlive the runner: one ``provenance/<benchmark>.json`` per Benchmark, a
    shared bundle's label under each Benchmark that reads it, and a missing one skipped."""
    assets: Path = tmp_path / "assets"
    _bundle(assets, "inspect-race_h", _RACE_H)
    _bundle(
        assets,
        "draco",
        _one_source(
            {
                "kind": "hugging-face",
                "location": "perplexity-ai/draco",
                "pin": "revision x",
                "phase": "load",
            }
        ),
    )
    log_dir: Path = tmp_path / "logs"

    copy_labels(["inspect-race_h", "draco-3pass", "never-prepared"], assets, log_dir)

    copied: list[str] = sorted(path.name for path in (log_dir / "provenance").iterdir())
    assert copied == ["draco-3pass.json", "inspect-race_h.json"]
    assert json.loads((log_dir / "provenance" / "inspect-race_h.json").read_text()) == _RACE_H
    assert (log_dir / "provenance" / "draco-3pass.json").read_bytes() == (
        assets / "draco" / "provenance.json"
    ).read_bytes()


def test_the_debug_bundle_never_carries_the_cases(tmp_path: Path) -> None:
    """INVARIANT: labels only. Some datasets are gated (xstest needs an accepted licence), and
    anyone who can read the repo can download the bundle."""
    assets: Path = tmp_path / "assets"
    _bundle(assets, "inspect-xstest", _RACE_H)
    (assets / "inspect-xstest" / "cases.json").write_text("[]", encoding="utf-8")
    log_dir: Path = tmp_path / "logs"

    copy_labels(["inspect-xstest"], assets, log_dir)

    assert [path.name for path in log_dir.rglob("*") if path.is_file()] == ["inspect-xstest.json"]
