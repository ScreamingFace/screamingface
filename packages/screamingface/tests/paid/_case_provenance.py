"""The press page's "Where the Cases came from" section (OME-1492).

Mental model: the label on each sample jar. Case Preparation writes a small
``provenance.json`` into every Imported Benchmark's bundle (which Hub commit or URL it
read, which seed it forced, how many Samples it kept, which inspect version prepared it).
This module reads those labels back from the assets root and lays them out as one table,
so a red press can be traced to a moved commit or a changed count without re-running the
import. The file sits in the cached bundle, so the section appears on every press, not
only on the presses that prepared assets.

Worked example, race_h's block ``{"sources": [{"location": "ehovy/race/high", "pin":
"revision 2fec9fd8…"}], "seeds_applied": {"shuffle_seed": 20260917}, "samples":
{"yielded": 3498, "excluded": 0, "kept": 3498}, "pins": {"inspect-evals": "0.20.0"},
"seconds": 15.2}`` reads

    | inspect-race_h | ehovy/race/high @ 2fec9fd8 | shuffle_seed 20260917
    | 3498 of 3498 | inspect-evals 0.20.0 | 15s |

(one table row, wrapped here)

INVARIANT: a view, never a verdict. A missing or unreadable file is one honest row, never
an exception, because this section must not hide the press overview it sits under.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

#: The file Case Preparation writes into each bundle (the Engine's ``PROVENANCE_FILE``;
#: the SDK venv cannot import the Engine, so the name is repeated here).
PROVENANCE_FILE: Final = "provenance.json"

#: How much of a commit or digest a table cell shows.
_SHORT_PIN_CHARS: Final = 8
#: Shorter than this, a pin value is a version or a word, not a hash: shown whole.
_MIN_HASH_CHARS: Final = 12
_HEX_DIGITS: Final = frozenset("0123456789abcdef")
_NONE: Final = "—"


def provenance_markdown(benchmarks: list[str], assets_root: Path) -> str:
    """One Markdown table row per Benchmark, sorted by name, read from its bundle.

    Args:
        benchmarks: the Benchmark ids this press ran. For every Imported Benchmark the
            bundle folder has the same name; the hand-built shared bundles are mapped in
            OME-1492 PR 3, so until then those rows read "not recorded".
        assets_root: the prepared assets root the stack served from.

    Returns:
        The section, heading included, ending in a newline.
    """
    rows: list[str] = [
        "### Where the Cases came from",
        "",
        "| Benchmark | Read from | Seeds forced | Samples kept | inspect-evals | Prep time |",
        "|---|---|---|---|---|---|",
    ]
    rows += [
        _row(benchmark, assets_root / benchmark / PROVENANCE_FILE)
        for benchmark in sorted(benchmarks)
    ]
    return "\n".join(rows) + "\n"


def _row(benchmark: str, path: Path) -> str:
    """One Benchmark's row, or an honest placeholder when its block can't be read."""
    if not path.is_file():
        return f"| {benchmark} | not recorded | {_NONE} | {_NONE} | {_NONE} | {_NONE} |"
    try:
        block: Any = json.loads(path.read_text(encoding="utf-8"))
        cells: list[str] = _cells(block)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        KeyError,
        AttributeError,
    ):
        # WHY this wide: the file is data from a build, not code we control; any shape it
        # takes must end as one row, never as a crash under the press overview.
        unreadable: str = f"unreadable {PROVENANCE_FILE}"
        return f"| {benchmark} | {unreadable} | {_NONE} | {_NONE} | {_NONE} | {_NONE} |"
    return "| " + " | ".join([benchmark, *cells]) + " |"


def _cells(block: dict[str, Any]) -> list[str]:
    """The five data cells: sources, seeds, sample counts, inspect-evals version, time."""
    sources: str = "<br>".join(
        f"{source['location']} @ {_short_pin(source['pin'])}" for source in block["sources"]
    )
    seeds: str = ", ".join(f"{name} {value}" for name, value in block["seeds_applied"].items())
    samples: dict[str, int] = block["samples"]
    kept: str = f"{samples['kept']} of {samples['yielded']}"
    if samples["excluded"]:
        kept += f" ({samples['excluded']} excluded)"
    return [
        sources or _NONE,
        seeds or _NONE,
        kept,
        f"inspect-evals {block['pins']['inspect-evals']}",
        f"{round(block['seconds'])}s",
    ]


def _short_pin(pin: str) -> str:
    """Shorten the hash in a pin: "revision 2fec9fd8a1b2…" → "2fec9fd8"; keep words whole.

    Pins come as "<kind> <value>" ("revision <sha>", "commit <sha>", "sha256 <hex>") or as
    one word ("unpinned", "inspect_evals==0.20.0").
    """
    value: str = pin.split(" ", 1)[-1]
    if len(value) >= _MIN_HASH_CHARS and set(value) <= _HEX_DIGITS:
        return value[:_SHORT_PIN_CHARS]
    return value
