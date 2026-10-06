# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Prepare an Imported Benchmark's Cases in-process, the way Case Preparation does (OME-1460).

Since OME-1460 every Imported Benchmark is prepared by Task replay: the eval's own task
function builds its Task, and capture renders each Sample through the Task's own solvers.
Benchmark tests that need a few prepared Cases call :func:`prepare_with_stand_in_hub`, which
does exactly that with one stand-in: the eval's ``hf_dataset`` fetch returns the test's rows,
converted by the eval's own ``sample_fields``. It proves the prepared layout and the eval's
own rendering; it does not prove what the Hub serves (the replay tests and the sweep do).
"""

from __future__ import annotations

import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest import mock

from inspect_ai.dataset import MemoryDataset

from screamingface_engine_inspect.capture import captured_case_records
from screamingface_engine_inspect.prepare import (
    TASK_REPLAY_CASES,
    PreparedCase,
    TaskReplayCasesSpec,
    _write_cases,
)


def prepare_with_stand_in_hub(
    benchmark_key: str, rows: list[dict[str, Any]], out: Path
) -> list[PreparedCase]:
    """Build the Benchmark's Task from its declaration over ``rows`` and write its Cases.

    Args:
        benchmark_key: a TASK_REPLAY_CASES key whose eval fetches through ``hf_dataset``.
        rows: stand-in Hub rows, in the dataset's own column names.
        out: the empty directory to prepare into (assets/<benchmark id>/).

    Returns:
        The prepared Cases, as written.
    """

    spec: TaskReplayCasesSpec = TASK_REPLAY_CASES[benchmark_key]
    module_name, _, attribute = spec.task.partition(":")
    module: Any = importlib.import_module(module_name)

    def stand_in_hub(*_: Any, sample_fields: Any, **__: Any) -> MemoryDataset:
        """The test's rows, converted by the eval's own sample_fields."""

        return MemoryDataset([sample_fields(row) for row in rows])

    # WHY INSPECT_EVAL_MODEL: as in the replay child (replay_environment), a solver that asks
    # for a model gets inspect's "none" model, never a real one (mmlu's does).
    with (
        mock.patch.object(module, "hf_dataset", stand_in_hub),
        mock.patch.dict(os.environ, {"INSPECT_EVAL_MODEL": "none/none"}),
    ):
        task: Any = getattr(module, attribute)(**(spec.task_args or {}))
        # WHY a worker thread: capture runs the solvers on its own event loop, and several
        # callers are async tests whose loop is already running.
        with ThreadPoolExecutor(max_workers=1) as pool:
            prepared: list[PreparedCase] = pool.submit(captured_case_records, task, spec).result()
    _write_cases(prepared, out)
    return prepared


def replay_in_process_over_rows(
    benchmark_key: str, rows: list[dict[str, Any]], cache_root: Path
) -> list[PreparedCase]:
    """Replay the Benchmark's real task in this process, with the real enforcer installed,
    over ``rows`` served as the Hub dataset; return the prepared Cases.

    Unlike :func:`prepare_with_stand_in_hub`, inspect's own ``hf_dataset`` runs, so the
    declaration's forced seeds reach inspect's shuffles; only ``datasets.load_dataset`` is a
    stand-in. Use it to test what the enforcer does to a real eval's Cases.
    """

    import functools

    import datasets

    from screamingface_engine_inspect.case_sources import CaseSourceRecorder
    from screamingface_engine_inspect.task_replay import fetch_pins_of

    spec: TaskReplayCasesSpec = TASK_REPLAY_CASES[benchmark_key]
    module_name, _, attribute = spec.task.partition(":")
    module: Any = importlib.import_module(module_name)
    real_load_dataset: Any = datasets.load_dataset

    @functools.wraps(real_load_dataset)  # WHY: the recorder binds arguments to this signature
    def stand_in_load_dataset(*_: Any, **__: Any) -> Any:
        """The rows, whatever was asked for."""

        return datasets.Dataset.from_list(rows)

    with (
        mock.patch.object(datasets, "load_dataset", stand_in_load_dataset),
        mock.patch.dict(
            os.environ,
            {"XDG_CACHE_HOME": str(cache_root / "xdg"), "INSPECT_EVAL_MODEL": "none/none"},
        ),
    ):
        recorder: CaseSourceRecorder = CaseSourceRecorder(cache_root)
        recorder.install(fetch_pins_of(spec))
        try:
            task: Any = getattr(module, attribute)(**(spec.task_args or {}))
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(captured_case_records, task, spec).result()
        finally:
            recorder.uninstall()
