# pyright: reportMissingImports=false
# WHY file-level: the rows assemble through inspect_ai, absent in the extra-less install.
"""LABBench2 FigQA2 image and TableQA2 image: the two imported rows (OME-1733).

What these tests pin, and why:

- the judge the row pins IS the judge the scorer calls, so the Benchmark's identity names the
  model that actually grades; and that model stays a gateway route;
- the Cases row reads the dataset at the revision the Task pins, behind the HF token, under
  the dataset's CC BY-SA licence, with each Case's question kept for the judge;
- both rows are ours (a local Task), keep the 101 and 100 Cases, and count a Case the judge
  cannot grade as 0.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine.world.models.builtins import BUILTIN_MODEL_WORLD  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402
from screamingface_engine_inspect.local_tasks.lab_bench_2.lab_bench_2 import (  # noqa: E402
    CASE_COUNTS,
    DATASET,
    DATASET_REVISION,
    JUDGE_MODEL,
)
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES  # noqa: E402

#: Row key → (the dataset config its Task loads, the Task function).
_ROWS: dict[str, tuple[str, str]] = {
    "labbench2_figqa2_img": ("figqa2-img", "lab_bench_2_figqa2_img"),
    "labbench2_tableqa2_img": ("tableqa2-img", "lab_bench_2_tableqa2_img"),
}


@pytest.mark.parametrize("key", sorted(_ROWS))
def test_the_row_pins_the_judge_the_scorer_calls(key: str) -> None:
    # INVARIANT: the scorer asks `screamingface/<model>`; the row's JudgeSpec must name the
    # same <model>, or the Benchmark's identity would name a judge that never grades it.
    spec = next(spec for spec in BENCHMARKS if spec.key == key)
    judge = imported_benchmark(key).judge

    assert spec.scorer_kwargs == {"judge_model": JUDGE_MODEL}
    assert judge is not None
    assert f"screamingface/{judge.model}" == JUDGE_MODEL
    assert dict(judge.params) == {"temperature": "0", "max_tokens": "4096", "web_search": "false"}
    assert judge.model in BUILTIN_MODEL_WORLD.routable


@pytest.mark.parametrize("key", sorted(_ROWS))
def test_the_cases_row_reads_the_tasks_pinned_dataset(key: str) -> None:
    cases = TASK_REPLAY_CASES[key]

    assert cases.task.endswith(f":{_ROWS[key][1]}")
    assert cases.source_pins == {DATASET: DATASET_REVISION}
    assert cases.case_count == CASE_COUNTS[_ROWS[key][0]]
    assert cases.needs_hf_token is True
    assert cases.license == "cc-by-sa-4.0"
    # The judge quotes the question text the Candidate saw, "Attached files" lines included.
    assert cases.keep_sample_input is True


@pytest.mark.parametrize("key", sorted(_ROWS))
def test_the_row_is_a_local_task_that_counts_an_ungraded_case_as_zero(key: str) -> None:
    benchmark = imported_benchmark(key).benchmark

    assert benchmark.id == key  # a local Task's id is its bare key, no "inspect-" prefix
    assert benchmark.origin == "screamingface"
    assert benchmark.case_count == CASE_COUNTS[_ROWS[key][0]]
    assert benchmark.declaration.failure_policy == "withhold"
