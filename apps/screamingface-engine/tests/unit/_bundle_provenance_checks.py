"""Shared checks for the provenance block a hand-built preparer writes (OME-1492 PR 3).

Each of the six hand-built preparers (draco, ifeval, healthbench, gdpval, medxpert,
contracteval) appends one test to its own prepare test file; this module holds the checks they
all make, so the six tests state only what differs: the source, the counts, the Case text.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from screamingface_engine.benchmarks.bundle_provenance import PROVENANCE_FILE, PROVENANCE_KEY


def watch_provenance_writes(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> list[bool]:
    """Spy on a preparer's provenance writer: one entry per write, True if cases.json existed."""

    real: Any = module.write_provenance
    seen: list[bool] = []

    def spy(out: Path, block: dict[str, Any]) -> None:
        """Note whether the bundle already looked finished, then write as usual."""
        seen.append((out / "cases.json").is_file())
        real(out, block)

    monkeypatch.setattr(module, "write_provenance", spy)
    return seen


def hugging_face_source(location: str, revision: str) -> dict[str, str]:
    """The Case Source a pinned Hugging Face load reads, in the shape the block lists it.

    The ``url`` (OME-1524) is the repo at the commit: the first two location segments, never
    a config, because ``huggingface.co/datasets/TsinghuaC3I/MedXpertQA/Text`` is a 404.
    """

    repo_id: str = "/".join(location.split("/")[:2])
    return {
        "kind": "hugging-face",
        "location": location,
        "pin": f"revision {revision}",
        "phase": "load",
        "url": f"https://huggingface.co/datasets/{repo_id}/tree/{revision}",
    }


def assert_hand_built_block(
    out: Path,
    summary: dict[str, Any],
    writes: list[bool],
    *,
    sources: list[dict[str, str]],
    yielded: int,
    kept: int,
    case_texts: list[str],
) -> None:
    """The bundle's ``provenance.json`` names its sources and counts, and nothing else."""

    # WHY exactly one write, before cases.json: the image build, the just recipe and the paid
    # conftest treat a parseable cases.json as "bundle finished", so an interrupted bundle must
    # never look finished without its provenance.
    assert writes == [False]
    raw: str = (out / PROVENANCE_FILE).read_text(encoding="utf-8")
    block: dict[str, Any] = json.loads(raw)
    assert block["sources"] == sources
    # A hand-built preparer forces no seed and never runs inspect.
    assert block["seeds_applied"] == {}
    assert block["pins"] == {}
    assert block["samples"] == {"yielded": yielded, "excluded": yielded - kept, "kept": kept}
    cases: list[Any] = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    assert block["samples"]["kept"] == len(cases)
    assert isinstance(block["seconds"], float)
    assert block["seconds"] >= 0
    # The summary line in the build log carries the same block the bundle holds.
    assert summary[PROVENANCE_KEY] == block
    # INVARIANT: never a Case's text. The build log is public and some datasets are licensed.
    for text in case_texts:
        assert text not in raw
