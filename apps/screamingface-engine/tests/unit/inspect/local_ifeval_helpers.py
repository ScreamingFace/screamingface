# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""IFEval, the local inspect Task, on a test node: a few prepared Cases and the Benchmark.

IFEval is the one Benchmark that offers Draft Feedback, so the Engine's Corrective Loop tests run
against it. Since OME-1527 it is a local Task served by the plugin lane, so these tests prepare
its bundle the way Case Preparation does (each row rendered by the Task's own loader, its
Grading Material written by the real preparer) and install the real assembled Benchmark.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from inspect_ai.dataset import Sample

from screamingface_engine.benchmarks.definition import Benchmark
from screamingface_engine.benchmarks.nltk_data import NLTK_DATA_DIR
from screamingface_engine_inspect.benchmarks import imported_benchmark
from screamingface_engine_inspect.local_tasks.ifeval.ifeval import record_to_sample
from screamingface_engine_inspect.prepare import (
    TASK_REPLAY_CASES,
    PreparedCase,
    _write_cases,
    prepared_case,
)

#: The assembled IFEval Benchmark, as the Engine registers it.
IFEVAL: Benchmark = imported_benchmark("ifeval").benchmark

#: The check-surface route the SDK compiled into the Candidates under ``tests/unit/data/``
#: when IFEval was hand-built. The SDK's drift guard reads the route from those files, so they
#: keep it; :func:`compiled_candidate` swaps in the route IFEval advertises today.
HAND_BUILT_CHECK_ROUTE: str = "/benchmarks/ifeval/1cba769ece27f7ef/check-surface"

#: One instruction set: (prompt, instruction ids, their arguments).
type IFEvalCase = tuple[str, Sequence[str], Sequence[Mapping[str, Any]]]


def write_ifeval_bundle(root: Path, cases: Sequence[IFEvalCase]) -> None:
    """Prepare ``cases`` as IFEval Cases 1..N into ``root`` (assets/ifeval), as the build does.

    The nltk folder is created empty: the installer refuses a finished bundle without one, and
    the callers' instructions read no tokenizer, except the one test that then fills the folder
    the way the image build does
    (``test_ifeval_grades_with_the_bundled_tokenizers_and_no_network``).
    """

    prepared: list[PreparedCase] = []
    for case_id, (prompt, instruction_ids, kwargs) in enumerate(cases, start=1):
        row: dict[str, Any] = {
            "key": case_id,
            "prompt": prompt,
            "instruction_id_list": list(instruction_ids),
            "kwargs": [dict(arguments) for arguments in kwargs],
        }
        sample: Sample = record_to_sample(row, case_id)
        case: PreparedCase = prepared_case(
            sample, case_id, str(sample.input), TASK_REPLAY_CASES["ifeval"]
        )
        # The Grading Material crosses JSON on its way to disk, as at build.
        case["grading_material"] = json.loads(json.dumps(case["grading_material"]))
        prepared.append(case)
    root.mkdir(parents=True, exist_ok=True)
    _write_cases(prepared, root)
    (root / NLTK_DATA_DIR).mkdir()


def compiled_candidate(path: Path) -> str:
    """An SDK-compiled Candidate from ``tests/unit/data/``, pointed at today's check surface.

    rstrip: the repo's end-of-file hook appends a newline the rendered expression never carries.
    """

    assert IFEVAL.check_surface is not None
    url4: str = path.read_text(encoding="utf-8").rstrip("\n")
    assert HAND_BUILT_CHECK_ROUTE in url4, f"{path.name} no longer names the hand-built route"
    return url4.replace(HAND_BUILT_CHECK_ROUTE, IFEVAL.check_surface.check_route)
