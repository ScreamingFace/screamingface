"""Bundle provenance: where a bundle's Cases came from, kept with the bundle (OME-1492).

Think of it as the label on a sample jar: not the contents, only where and how it was filled.
Case Preparation writes one small JSON block, ``provenance.json``, into every bundle it
prepares, and adds the same block to that bundle's summary line in the build log. A red image
build or a red paid-smoke press can then say which dataset commit was read and how many rows
became Cases, from the log or the bundle alone.

Two kinds of preparer fill the label. The inspect plugin's Task replay builds its block from
what its child process saw (the plugin's replay provenance module); the six hand-built
preparers build theirs with :func:`hand_built_provenance`. Both write it with
:func:`write_provenance`, which lives here, in core, because core never imports a plugin.

Worked example, MedXpertQA: the preparer loaded 2450 rows of ``TsinghuaC3I/MedXpertQA``
(config ``Text``) at commit ``7e7c465a…``, dropped none and wrote 2450 Cases (the seconds
here are illustrative)::

    {"sources": [{"kind": "hugging-face", "location": "TsinghuaC3I/MedXpertQA/Text",
                  "pin": "revision 7e7c465a…", "phase": "load"}],
     "seeds_applied": {},
     "samples": {"yielded": 2450, "excluded": 0, "kept": 2450},
     "pins": {},
     "seconds": 41.2}

INVARIANT: the block holds commits, locations, counts and versions, never a Case's input or
target. The build log is public and some datasets are gated or licensed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Final

#: The file Case Preparation writes into a bundle, beside ``cases.json``.
PROVENANCE_FILE: Final = "provenance.json"

#: The summary-line key that carries the same block.
PROVENANCE_KEY: Final = "provenance"

# The Case Source words, the one home for them: the inspect plugin's fetch recorder imports
# them from here, so both kinds of bundle read alike on the paid smoke's run page.
#: A Hugging Face dataset, pinned by a revision.
HUGGING_FACE: Final = "hugging-face"
#: A download from a URL, pinned only when the URL itself names a commit or a hash.
URL: Final = "url"
#: A file shipped inside the package that prepares the bundle.
FILE: Final = "file"
#: The pin of a Case Source nothing upstream pins: for an Imported Benchmark the Case Digest is
#: then the only pin; for a hand-built one, nothing is.
UNPINNED: Final = "unpinned"
#: Read while the dataset loads (the plugin also has "render": read while building a prompt).
LOAD_PHASE: Final = "load"


def hugging_face_source(
    dataset: str, revision: str, *, config: str | None = None
) -> dict[str, str]:
    """The Case Source entry for a pinned Hugging Face load.

    Args:
        dataset: the Hub repo, ``owner/name``.
        revision: the commit the load is pinned to.
        config: the dataset config name, if the load passes one; it joins the location as
            ``owner/name/config``, the form the plugin records for the same call.

    Returns:
        ``{"kind", "location", "pin", "phase"}``, all strings.
    """

    location: str = f"{dataset}/{config}" if config else dataset
    return {
        "kind": HUGGING_FACE,
        "location": location,
        "pin": f"revision {revision}",
        "phase": LOAD_PHASE,
    }


def hand_built_provenance(
    sources: list[dict[str, str]], *, yielded: int, kept: int, started: float
) -> dict[str, Any]:
    """Build a hand-built preparer's block, just before it writes ``cases.json``.

    Example: GDPval loads 220 rows and its frozen selection keeps 102, so
    ``samples == {"yielded": 220, "excluded": 118, "kept": 102}``; ``excluded`` is always the
    difference, so the run page's "102 of 220 (118 excluded)" accounts for every row.

    Args:
        sources: every Case Source the preparer read, each from :func:`hugging_face_source`
            or of the same shape.
        yielded: rows the preparer loaded, before it dropped any on purpose.
        kept: Cases it is about to write.
        started: ``time.monotonic()`` when the preparer began, download included.

    Returns:
        The block, JSON-safe. ``seeds_applied`` and ``pins`` are empty: a hand-built preparer
        forces no seed and never runs inspect.
    """

    return {
        "sources": sources,
        "seeds_applied": {},
        "samples": {"yielded": yielded, "excluded": yielded - kept, "kept": kept},
        "pins": {},
        "seconds": round(time.monotonic() - started, 3),
    }


def write_provenance(out: Path, block: dict[str, Any]) -> None:
    """Write the block into the bundle.

    WHY callers write it BEFORE ``cases.json``: the workflow, the just recipe and the paid
    conftest treat a parseable ``cases.json`` as "bundle finished", so an interrupted bundle
    must never look finished without its provenance.
    """

    out.mkdir(parents=True, exist_ok=True)
    (out / PROVENANCE_FILE).write_text(
        json.dumps(block, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_provenance(out: Path) -> dict[str, Any]:
    """Read back the block a preparer just wrote, so its summary reports what landed."""

    block: dict[str, Any] = json.loads((out / PROVENANCE_FILE).read_text(encoding="utf-8"))
    return block


__all__ = [
    "FILE",
    "HUGGING_FACE",
    "LOAD_PHASE",
    "PROVENANCE_FILE",
    "PROVENANCE_KEY",
    "UNPINNED",
    "URL",
    "hand_built_provenance",
    "hugging_face_source",
    "read_provenance",
    "write_provenance",
]
