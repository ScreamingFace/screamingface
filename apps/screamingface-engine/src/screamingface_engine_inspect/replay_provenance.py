"""Replay provenance: where a Task-replay bundle's Cases came from, kept with the bundle.

FEATURE: OME-1492 — a red image build or a red paid-smoke press can say which Hub commit was
read, which seed was forced and how many Samples were kept, from the log or the bundle alone.

Think of it as the label on a sample jar: not the contents, only where and how it was filled.
The replay child already records every fetch and every forced seed (the fetch-pin enforcer's
recorder); this module turns that record into one small JSON block, which Case Preparation
writes beside ``cases.json`` and adds to the bundle's summary line.

Worked example, race_h: the child read ``ehovy/race`` at commit ``2fec9fd8…`` and forced
``shuffle_seed`` (declared 20260917); the task yielded 3498 Samples and none were excluded::

    {"sources": [{"kind": "hugging-face", "location": "ehovy/race/high",
                  "pin": "revision 2fec9fd8…", "phase": "load"}],
     "seeds_applied": {"shuffle_seed": 20260917},
     "samples": {"yielded": 3498, "excluded": 0, "kept": 3498},
     "pins": {"inspect-ai": "0.3.263", "inspect-evals": "0.20.0"},
     "seconds": 15.0}

INVARIANT: the block holds commits, locations, seed values, counts and versions — never a
Case's input or target. The Actions log is public and some datasets are gated or licensed.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

from screamingface_engine_inspect.case_sources import CaseSourceRecorder
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec
from screamingface_engine_inspect.revision_inputs import pinned_inspect_packages

#: The file Case Preparation writes into a bundle, beside ``cases.json``.
PROVENANCE_FILE: Final = "provenance.json"

#: The summary-line key that carries the same block.
PROVENANCE_KEY: Final = "provenance"


def replay_provenance(
    recorder: CaseSourceRecorder, spec: TaskReplayCasesSpec, *, yielded: int, kept: int
) -> dict[str, Any]:
    """Build the block from what the child saw; the parent adds ``seconds``.

    Stages: (1) ``sources`` — every fetch the recorder saw, each with the pin it was forced
    to; (2) ``seeds_applied`` — each seed the enforcer forced, with the declaration's value
    (the recorder keeps only names, and a name alone can't tell two builds apart);
    (3) ``samples`` — the dataset before the declaration's exclusions, the exclusions, and
    the Cases kept; (4) ``pins`` — the installed inspect packages.

    Args:
        recorder: the recorder the child installed before calling the task function.
        spec: the declaration whose seeds the enforcer forced.
        yielded: Samples in the Task's dataset, after the eval's own filtering and before
            the declaration's ``excluded_sample_ids``.
        kept: Cases captured, after those exclusions.

    Returns:
        A JSON-safe dict: lists and dicts of strings and numbers, no sets.
    """

    # Stage 1 — the fetches, each with its forced pin.
    sources: list[dict[str, str]] = [asdict(source) for source in recorder.sources]
    # Stage 2 — the forced seeds, by name, with the declared value (sorted: stable output).
    seeds_applied: dict[str, int | None] = {
        name: getattr(spec, name) for name in sorted(recorder.seeds_applied)
    }
    # Stage 3 — the Sample counts.
    samples: dict[str, int] = {"yielded": yielded, "excluded": yielded - kept, "kept": kept}
    # Stage 4 — the inspect packages, as {"inspect-ai": "0.3.263", ...}.
    pins: dict[str, str] = dict(pin.split("==", 1) for pin in pinned_inspect_packages())
    return {"sources": sources, "seeds_applied": seeds_applied, "samples": samples, "pins": pins}


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


__all__ = ["PROVENANCE_FILE", "PROVENANCE_KEY", "replay_provenance", "write_provenance"]
