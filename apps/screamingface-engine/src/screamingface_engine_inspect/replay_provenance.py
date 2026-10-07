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

from dataclasses import asdict
from typing import Any

# WHY from core: the six hand-built preparers write the same file, and core never imports a
# plugin, so the file name, the summary key and the writer live in core (OME-1492 PR 3).
from screamingface_engine.benchmarks.bundle_provenance import (
    PROVENANCE_FILE,
    PROVENANCE_KEY,
    write_provenance,
)
from screamingface_engine_inspect.case_sources import CaseSourceRecorder
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec
from screamingface_engine_inspect.revision_inputs import pinned_inspect_packages


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


__all__ = ["PROVENANCE_FILE", "PROVENANCE_KEY", "replay_provenance", "write_provenance"]
