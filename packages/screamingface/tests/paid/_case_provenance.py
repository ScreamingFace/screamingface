"""The press page's "Where the Cases came from" section (OME-1492).

Mental model: the label on each sample jar. Case Preparation writes a small
``provenance.json`` into every bundle (which Hub commit or URL it read, which seed it
forced, how many Samples it kept, which inspect version prepared it; a hand-built
preparer forces no seed and runs no inspect, so those cells read "—").
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

(one table row, wrapped here). A source whose label carries a ``url`` (OME-1524: a link to
that source, built by the Engine code that read it: a Hub or GitHub source at its full commit,
a web download at its own address, whose pin cell may still read ``unpinned``) reads as that
link,
``[ehovy/race/high @ 2fec9fd8](https://huggingface.co/datasets/ehovy/race/tree/2fec9fd8…)``.
This module never builds a URL itself: only the Engine knows the host and the repo id.

The labels also ship in the debug bundle: :func:`copy_labels` copies each one into the log
folder, because the assets root lives on the CI runner and in the Actions cache, neither of
which the owner can download.

INVARIANT: a view, never a verdict. A missing or unreadable file is one honest row, never
an exception, because this section must not hide the press overview it sits under.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

#: The file Case Preparation writes into each bundle (the Engine's ``PROVENANCE_FILE``;
#: the SDK venv cannot import the Engine, so the name is repeated here).
PROVENANCE_FILE: Final = "provenance.json"

#: How much of a commit or digest a table cell shows.
_SHORT_PIN_CHARS: Final = 8
#: Shorter than this, a pin value is a version or a word, not a hash: shown whole.
_MIN_HASH_CHARS: Final = 12
_HEX_DIGITS: Final = frozenset("0123456789abcdef")
_NONE: Final = "—"
#: The only addresses drawn as links: the label is build data, so a ``javascript:`` url in it
#: stays text.
_WEB_SCHEMES: Final = ("https://", "http://")
#: What a link target keeps as-is; everything else is percent-encoded, so ``|`` cannot open a
#: table cell and ``)`` or a space cannot end the link early.
_URL_SAFE: Final = ":/?#@!$&'*+,;=%"
#: The folder, inside the log folder, the debug bundle carries the labels in.
LABELS_DIR: Final = "provenance"

#: The Benchmarks that read another Benchmark's bundle (the Engine's ``builtins.py`` pairs
#: them). Every other Benchmark's bundle folder has the Benchmark's own id. Repeated here
#: for the same reason as ``PROVENANCE_FILE``: the SDK venv cannot import the Engine.
_SHARED_BUNDLE: Final[dict[str, str]] = {
    "draco-3pass": "draco",
    "healthbench-worst30": "healthbench",
    "healthbench-professional": "healthbench",
    "gdpval-text": "gdpval",
}


def provenance_markdown(benchmarks: list[str], assets_root: Path) -> str:
    """One Markdown table row per Benchmark, sorted by name, read from its bundle.

    Args:
        benchmarks: the Benchmark ids this press ran. A Benchmark on a shared bundle
            (``_SHARED_BUNDLE``) reads that bundle's file; every other one reads the
            folder with its own id.
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
        _row(benchmark, _label_path(benchmark, assets_root)) for benchmark in sorted(benchmarks)
    ]
    return "\n".join(rows) + "\n"


def copy_labels(benchmarks: list[str], assets_root: Path, log_dir: Path) -> None:
    """Copy each Benchmark's label to ``log_dir/provenance/<benchmark>.json`` for the bundle.

    Example: a press over ``inspect-race_h`` and ``draco-3pass`` leaves
    ``provenance/inspect-race_h.json`` and ``provenance/draco-3pass.json`` (draco's label: the
    two share a bundle), one file per row of the table.

    INVARIANT: labels only, never ``cases.json``: some datasets are gated on Hugging Face, and
    anyone who can read the repo can download the bundle. A Benchmark with no label is skipped;
    its table row already says "not recorded".

    Args:
        benchmarks: the Benchmark ids this press ran.
        assets_root: the prepared assets root the stack served from.
        log_dir: the folder the debug bundle uploads.

    Raises:
        OSError: a copy failed; the caller decides it only warns.
    """
    labels: Path = log_dir / LABELS_DIR
    for benchmark in benchmarks:
        source: Path = _label_path(benchmark, assets_root)
        if source.is_file():
            labels.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, labels / f"{benchmark}.json")


def _label_path(benchmark: str, assets_root: Path) -> Path:
    """Where a Benchmark's label sits: its own bundle, or the bundle it shares."""
    return assets_root / _SHARED_BUNDLE.get(benchmark, benchmark) / PROVENANCE_FILE


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
        ValueError,
        OverflowError,
    ):
        # WHY this wide: the file is data from a build, not code we control; any shape it
        # takes must end as one row, never as a crash under the press overview. json.loads
        # accepts NaN and Infinity, and rounding them raises ValueError or OverflowError.
        unreadable: str = f"unreadable {PROVENANCE_FILE}"
        return f"| {benchmark} | {unreadable} | {_NONE} | {_NONE} | {_NONE} | {_NONE} |"
    return "| " + " | ".join([benchmark, *cells]) + " |"


def _cells(block: dict[str, Any]) -> list[str]:
    """The five data cells: sources, seeds, sample counts, inspect-evals version, time."""
    sources: str = "<br>".join(_source_cell(source) for source in block["sources"])
    seeds: str = ", ".join(f"{name} {value}" for name, value in block["seeds_applied"].items())
    samples: dict[str, int] = block["samples"]
    kept: str = f"{samples['kept']} of {samples['yielded']}"
    if samples["excluded"]:
        kept += f" ({samples['excluded']} excluded)"
    # A hand-built preparer never runs inspect, so its `pins` is empty.
    inspect_evals: str | None = block["pins"].get("inspect-evals")
    return [
        sources or _NONE,
        seeds or _NONE,
        kept,
        f"inspect-evals {inspect_evals}" if inspect_evals else _NONE,
        f"{round(block['seconds'])}s",
    ]


def _source_cell(source: dict[str, Any]) -> str:
    """One source as ``location @ pin``, a link to that pin when its label carries one.

    WHY escape: a location is upstream text, and a ``|`` would open a cell or a ``]`` end the
    link text, breaking the row (and every row under it) on the run page.
    """
    text: str = _escape(f"{source['location']} @ {_short_pin(source['pin'])}")
    url: Any = source.get("url")
    if not isinstance(url, str) or not url.startswith(_WEB_SCHEMES):
        return text
    return f"[{text}]({quote(url, safe=_URL_SAFE)})"


def _escape(text: str) -> str:
    """Make upstream text inert inside a Markdown table cell and link text."""
    for character in ("\\", "|", "[", "]"):
        text = text.replace(character, "\\" + character)
    return text


def _short_pin(pin: str) -> str:
    """Shorten the hash in a pin: "revision 2fec9fd8a1b2…" → "2fec9fd8"; keep words whole.

    Pins come as "<kind> <value>" ("revision <sha>", "commit <sha>", "sha256 <hex>") or as
    one word ("unpinned", "inspect_evals==0.20.0").
    """
    value: str = pin.split(" ", 1)[-1]
    if len(value) >= _MIN_HASH_CHARS and set(value) <= _HEX_DIGITS:
        return value[:_SHORT_PIN_CHARS]
    return value
