# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The pin-generator importer — the tool that turns an inspect task into row diffs.

INVARIANT the suite defends: the importer never invents benchmark facts. Everything it
writes is either read from the eval's own task (dataset args, conversion/template/
scorer references) or captured as a named Hub dataset fact (revision sha, row count,
license) — and it lands ONLY between the three files' anchor comments, as a diff a
human reviews before anything merges (import time is the only trust window).

Runs only with the `inspect` extra installed. No network: the fabricated eval
module's ``hf_dataset`` is intercepted by the importer itself, and the capture
layer is injected.
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai import Task  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.scorer import choice, match  # noqa: E402
from inspect_ai.solver import generate, multiple_choice, prompt_template  # noqa: E402

from screamingface_engine_inspect import importer as importer_module  # noqa: E402
from screamingface_engine_inspect.importer import (  # noqa: E402
    CLEARED_DATASET_LICENSES,
    HubDatasetFacts,
    ImporterError,
    InspectTaskFacts,
    read_hub_dataset_facts,
    read_inspect_task,
    render_generated_rows,
    write_generated_rows,
)

_SRC_DIR: Path = Path(importer_module.__file__).resolve().parent


# ---------------------------------------------------------------------------
# A fabricated eval package, registered in sys.modules — the importer must read
# everything from it exactly as it would from a real inspect_evals module.
# ---------------------------------------------------------------------------

_FAKE_MODULE = "fake_eval_for_importer"

_TEMPLATE = "Answer briefly.\n\n{prompt}\n"


def _make_record_to_sample() -> Any:
    """The fabricated eval's row rule — referenced by dotted name in the facts."""

    def record_to_sample(row: dict[str, Any]) -> Sample:
        return Sample(input=str(row["q"]), target=str(row["a"]))

    record_to_sample.__module__ = _FAKE_MODULE
    return record_to_sample


def _install_fake_eval(monkeypatch: pytest.MonkeyPatch, **task_fns: Any) -> types.ModuleType:
    """Register a module carrying hf_dataset + the given task functions."""

    module = types.ModuleType(_FAKE_MODULE)
    from inspect_ai.dataset import hf_dataset

    module.hf_dataset = hf_dataset  # type: ignore[attr-defined]
    module.TEMPLATE = _TEMPLATE  # type: ignore[attr-defined]
    module.record_to_sample = _make_record_to_sample()  # type: ignore[attr-defined]
    for name, fn in task_fns.items():
        setattr(module, name, fn)
    monkeypatch.setitem(sys.modules, _FAKE_MODULE, module)
    return module


def _free_text_task() -> Task:
    module = sys.modules[_FAKE_MODULE]
    return Task(
        dataset=module.hf_dataset(
            path="acme/sums",
            name="main",
            split="test",
            sample_fields=module.record_to_sample,
            revision="deadbeef" * 5,
        ),
        solver=[prompt_template(module.TEMPLATE), generate()],
        scorer=match(numeric=True),
    )


def _mcq_task() -> Task:
    module = sys.modules[_FAKE_MODULE]
    return Task(
        dataset=module.hf_dataset(
            path="acme/quiz",
            split="validation",
            sample_fields=module.record_to_sample,
        ),
        solver=multiple_choice(),
        scorer=choice(),
    )


def _fewshot_task() -> Task:
    """Two hf_dataset calls; only the one the Task holds is the benchmark."""

    module = sys.modules[_FAKE_MODULE]
    module.hf_dataset(
        path="acme/sums",
        name="main",
        split="train",
        sample_fields=module.record_to_sample,
    )
    return _free_text_task()


# ---------------------------------------------------------------------------
# read_inspect_task
# ---------------------------------------------------------------------------


def test_read_inspect_task_reads_the_free_text_task_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_eval(monkeypatch, sums=_free_text_task)

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:sums")

    assert facts.dataset == "acme/sums"
    assert facts.config == "main"
    assert facts.split == "test"
    assert facts.pinned_revision == "deadbeef" * 5
    assert facts.record_to_sample == f"{_FAKE_MODULE}:record_to_sample"
    assert facts.prompt_template == f"{_FAKE_MODULE}:TEMPLATE"
    assert facts.mcq is False
    assert facts.scorer == "inspect_ai.scorer:match"
    assert facts.scorer_kwargs == {"numeric": True}


def test_read_inspect_task_reads_the_mcq_task(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_eval(monkeypatch, quiz=_mcq_task)

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:quiz")

    assert facts.mcq is True
    assert facts.prompt_template is None
    assert facts.pinned_revision is None
    assert facts.config == ""
    assert facts.scorer == "inspect_ai.scorer:choice"
    assert facts.scorer_kwargs == {}
    # The DEFAULT choice template is fully prepared — no review flag.
    assert facts.unreproduced_solvers == ()


def test_read_inspect_task_picks_the_dataset_the_task_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fewshot eval calls hf_dataset twice; the benchmark is the Task's dataset."""

    _install_fake_eval(monkeypatch, sums=_fewshot_task)

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:sums")

    assert facts.split == "test"


def test_read_inspect_task_flags_a_system_message_the_prepare_would_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System instructions have no prepare channel — vanishing silently would change
    the imported benchmark (review finding on PR 965)."""

    from inspect_ai.solver import system_message

    def instructed() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            solver=[system_message("You are a careful accountant."), generate()],
            scorer=match(numeric=True),
        )

    _install_fake_eval(monkeypatch, instructed=instructed)

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:instructed")

    assert any("system_message" in flag for flag in facts.unreproduced_solvers)


def test_read_inspect_task_flags_a_custom_choice_template(monkeypatch: pytest.MonkeyPatch) -> None:
    """The prepare step renders MCQ with the default SINGLE_ANSWER template; a custom one
    must surface for review, not silently change the benchmark (review finding on PR 965)."""

    def custom_mcq() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/quiz", split="test", sample_fields=module.record_to_sample
            ),
            solver=multiple_choice(template="Pick wisely.\n{question}\n{choices}"),
            scorer=choice(),
        )

    _install_fake_eval(monkeypatch, custom_mcq=custom_mcq)

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:custom_mcq")

    assert any("custom choice template" in flag for flag in facts.unreproduced_solvers)
    # The default-template MCQ task stays unflagged — see the mcq test above.


def test_read_inspect_task_refuses_a_task_that_never_loads_hf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def local_task() -> Task:
        return Task(dataset=[Sample(input="q", target="1")], solver=generate(), scorer=match())

    _install_fake_eval(monkeypatch, local=local_task)

    with pytest.raises(ImporterError, match="hf_dataset"):
        read_inspect_task(f"{_FAKE_MODULE}:local")


def test_read_inspect_task_binds_through_the_vendored_hf_dataset_shim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """inspect_evals ≥0.20 routes hf_dataset through its ``(*args, **kwargs)`` retry
    shim; binding against the shim buries every real kwarg in the VAR_KEYWORD
    bucket, and the kwarg-reproduction guard then refuses the ENTIRE hf family as
    "kwarg(s) kwargs" (OME-1238). The recorder must bind the caller's arguments
    against the real hf_dataset signature — including a positionally passed path.
    Bound through the REAL vendored shim, not a hand-written stand-in, so a shim
    reshape on a pin bump fails here first."""

    from inspect_evals.utils.huggingface import hf_dataset as vendored_shim

    def wrapped_task() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                "acme/sums",
                split="test",
                name="main",
                sample_fields=module.record_to_sample,
                revision="deadbeef" * 5,
            ),
            solver=[prompt_template(sys.modules[_FAKE_MODULE].TEMPLATE), generate()],
            scorer=match(numeric=True),
        )

    module = _install_fake_eval(monkeypatch, sums=wrapped_task)
    module.hf_dataset = vendored_shim  # type: ignore[attr-defined]

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:sums")

    assert facts.dataset == "acme/sums"
    assert facts.config == "main"
    assert facts.split == "test"
    assert facts.pinned_revision == "deadbeef" * 5
    assert facts.record_to_sample == f"{_FAKE_MODULE}:record_to_sample"


def test_read_inspect_task_refuses_an_unknown_variadic_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the vendored shim is verified pass-through — identity, not shape. A
    wrapper that mutated kwargs before forwarding would make the reproduced-kwargs
    guard reason about arguments the real load never sees, so any other fully
    variadic wrapper refuses."""

    import inspect_ai.dataset

    def homegrown_wrapper(*args: Any, **kwargs: Any) -> Any:
        return inspect_ai.dataset.hf_dataset(*args, **kwargs)

    def wrapped_task() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                "acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            solver=generate(),
            scorer=match(),
        )

    module = _install_fake_eval(monkeypatch, sums=wrapped_task)
    module.hf_dataset = homegrown_wrapper  # type: ignore[attr-defined]

    with pytest.raises(ImporterError, match="variadic wrapper"):
        read_inspect_task(f"{_FAKE_MODULE}:sums")


def test_shim_call_with_an_extra_kwarg_refuses_under_its_own_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flatten's whole point: a kwarg landing in the real signature's own
    ``**kwargs`` bucket must be judged BY NAME — the refusal says ``data_files``,
    never the opaque bucket name ``kwargs``."""

    from inspect_evals.utils.huggingface import hf_dataset as vendored_shim

    def extra_kwarg_task() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums",
                split="test",
                sample_fields=module.record_to_sample,
                data_files="rows.parquet",
            ),
            solver=generate(),
            scorer=match(),
        )

    module = _install_fake_eval(monkeypatch, sums=extra_kwarg_task)
    module.hf_dataset = vendored_shim  # type: ignore[attr-defined]

    with pytest.raises(ImporterError, match="data_files"):
        read_inspect_task(f"{_FAKE_MODULE}:sums")


def test_an_unbindable_hf_dataset_call_refuses_as_importer_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The importer's contract: every refusal is an ImporterError naming the fact —
    bind_partial's bare TypeError (e.g. a doubled path argument) must not leak."""

    from inspect_evals.utils.huggingface import hf_dataset as vendored_shim

    def doubled_arg_task() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                "acme/sums",
                path="acme/other",
                split="test",
                sample_fields=module.record_to_sample,
            ),
            solver=generate(),
            scorer=match(),
        )

    module = _install_fake_eval(monkeypatch, sums=doubled_arg_task)
    module.hf_dataset = vendored_shim  # type: ignore[attr-defined]

    with pytest.raises(ImporterError, match="does not bind"):
        read_inspect_task(f"{_FAKE_MODULE}:sums")


def test_read_inspect_task_resolves_a_prompt_template_from_a_sibling_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AIME keeps its prompt template in a shared helper (utils.aime_common), not
    the task module — the row must POINT at the defining module (OME-1238)."""

    sibling_name = f"{_FAKE_MODULE}.common"
    sibling = types.ModuleType(sibling_name)
    sibling.SHARED_TEMPLATE = "Shared instructions.\n\n{prompt}\n"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, sibling_name, sibling)

    def shared_task() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            solver=[prompt_template(sibling.SHARED_TEMPLATE), generate()],
            scorer=match(numeric=True),
        )

    _install_fake_eval(monkeypatch, shared=shared_task)

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:shared")

    assert facts.prompt_template == f"{sibling_name}:SHARED_TEMPLATE"


def test_read_inspect_task_refuses_an_ambiguous_sibling_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two sibling modules holding the same template object cannot yield ONE
    dotted reference — the importer must refuse, never pick silently."""

    shared_template = "Ambiguous instructions.\n\n{prompt}\n"
    for suffix in ("common_a", "common_b"):
        name = f"{_FAKE_MODULE}.{suffix}"
        sibling = types.ModuleType(name)
        sibling.SHARED_TEMPLATE = shared_template  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, name, sibling)

    def ambiguous_task() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            solver=[prompt_template(shared_template), generate()],
            scorer=match(numeric=True),
        )

    _install_fake_eval(monkeypatch, ambiguous=ambiguous_task)

    with pytest.raises(ImporterError, match="exactly one module"):
        read_inspect_task(f"{_FAKE_MODULE}:ambiguous")


# ---------------------------------------------------------------------------
# read_hub_dataset_facts
# ---------------------------------------------------------------------------


def _facts(**overrides: Any) -> InspectTaskFacts:
    base: dict[str, Any] = {
        "task_ref": f"{_FAKE_MODULE}:sums",
        "dataset": "acme/sums",
        "config": "main",
        "split": "test",
        "pinned_revision": None,
        "record_to_sample": f"{_FAKE_MODULE}:record_to_sample",
        "prompt_template": f"{_FAKE_MODULE}:TEMPLATE",
        "mcq": False,
        "scorer": "inspect_ai.scorer:match",
        "scorer_kwargs": {"numeric": True},
        "unreproduced_solvers": (),
    }
    base.update(overrides)
    return InspectTaskFacts(**base)


def _fake_info(sha: str, license_id: str | None) -> Any:
    return types.SimpleNamespace(sha=sha, card_data={"license": license_id})


def test_capture_records_head_sha_when_upstream_does_not_pin() -> None:
    obs: HubDatasetFacts = read_hub_dataset_facts(
        _facts(),
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 321,
    )

    assert obs.revision == "a" * 40
    assert obs.case_count == 321
    assert obs.license == "mit"


def test_capture_resolves_a_mutable_upstream_pin_to_its_commit_sha() -> None:
    """A branch/tag pin like "main" must never land in pins.py — later builds
    would fetch different data (review finding on PR 965)."""

    seen: list[str | None] = []

    def info_of(dataset: str, revision: str | None) -> Any:
        seen.append(revision)
        return _fake_info("a" * 40, "mit")

    obs: HubDatasetFacts = read_hub_dataset_facts(
        _facts(pinned_revision="main"),
        dataset_info=info_of,
        count_rows=lambda facts, revision: 321,
    )

    # The pin names WHICH revision to resolve; the stored value is its sha —
    # and the license was read at that same revision, not at HEAD.
    assert seen == ["main"]
    assert obs.revision == "a" * 40


def test_capture_keeps_an_upstream_sha_pin() -> None:
    obs: HubDatasetFacts = read_hub_dataset_facts(
        _facts(pinned_revision="b" * 40),
        dataset_info=lambda dataset, revision: _fake_info(revision or "", "mit"),
        count_rows=lambda facts, revision: 321,
    )

    assert obs.revision == "b" * 40


# ---------------------------------------------------------------------------
# render_generated_rows
# ---------------------------------------------------------------------------


def test_rendered_rows_are_valid_python_and_carry_the_facts() -> None:
    rows = render_generated_rows(
        "sums", _facts(), HubDatasetFacts(revision="c" * 40, case_count=42, license="mit")
    )

    ast.parse(rows.pins)
    ast.parse(f"BENCHMARK_CASES = {{\n{rows.cases}}}")
    ast.parse(f"BENCHMARKS = (\n{rows.benchmark})")
    assert 'SUMS_DATASET = "acme/sums"' in rows.pins
    assert f'SUMS_DATASET_REVISION = "{"c" * 40}"' in rows.pins
    assert "SUMS_CASE_COUNT = 42" in rows.pins
    assert "license: mit" in rows.pins
    assert f'record_to_sample="{_FAKE_MODULE}:record_to_sample"' in rows.cases
    assert f'prompt_template="{_FAKE_MODULE}:TEMPLATE"' in rows.cases
    # Free text ⇒ the draft-feedback offer is legitimate and declared.
    assert "with_check_surface=True" in rows.benchmark
    assert 'scorer="inspect_ai.scorer:match"' in rows.benchmark
    assert 'scorer_kwargs={"numeric": True}' in rows.benchmark
    # Catalogue prose is the dev's, never invented by the tool.
    assert "TODO" in rows.benchmark


def test_mcq_rows_refuse_the_check_surface() -> None:
    """OME-796: pass/fail feedback over a handful of options is an elimination attack."""

    rows = render_generated_rows(
        "quiz",
        _facts(mcq=True, prompt_template=None, scorer="inspect_ai.scorer:choice", scorer_kwargs={}),
        HubDatasetFacts(revision="c" * 40, case_count=7, license="mit"),
    )

    assert "with_check_surface" not in rows.benchmark
    assert "prompt_template" not in rows.cases


def test_mcq_detection_follows_the_solver_not_the_scorer_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """lab_bench grades its MCQ benchmarks with its OWN scorer (precision_choice), so
    keying mcq on the scorer name reads them as free-text and hands an MCQ benchmark
    the draft-feedback offer — an elimination attack (OME-796). MCQ-ness is the benchmark's
    SHAPE, declared by the multiple_choice solver, and is detected there."""

    from inspect_ai.scorer import Score, Target, accuracy, scorer
    from inspect_ai.solver import TaskState

    @scorer(metrics=[accuracy()])
    def house_grader(no_answer: str | None = None) -> Any:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")

        return score

    def custom_graded_mcq() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/quiz", split="test", sample_fields=module.record_to_sample
            ),
            solver=multiple_choice(),
            scorer=house_grader(no_answer="Insufficient information to answer the question."),
        )

    module = _install_fake_eval(monkeypatch, custom_graded_mcq=custom_graded_mcq)
    # The eval exports its own scorer constructor — the row must resolve it there.
    module.house_grader = house_grader  # type: ignore[attr-defined]

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:custom_graded_mcq")

    assert facts.mcq is True
    assert facts.scorer.endswith(":house_grader")


def test_mcq_detection_sees_through_a_custom_solver_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detects MCQ when a custom wrapper hides the multiple_choice solver but the
    choice scorer proves the shape (the mmlu family case, OME-796 guard): mmlu's
    mmlu_multiple_choice calls multiple_choice() INSIDE its own @solver, so the
    registry walk never meets it — reading such a benchmark as free-text would hand
    an MCQ benchmark the draft-feedback offer (the elimination attack)."""

    from inspect_ai.solver import Generate, TaskState, solver

    @solver
    def wrapped_mcq() -> Any:
        inner: Any = multiple_choice()

        async def solve(state: TaskState, generate: Generate) -> TaskState:
            return await inner(state, generate)

        return solve

    def wrapper_graded_mcq() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/quiz", split="test", sample_fields=module.record_to_sample
            ),
            solver=wrapped_mcq(),
            scorer=choice(),
        )

    _install_fake_eval(monkeypatch, wrapper_graded_mcq=wrapper_graded_mcq)

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:wrapper_graded_mcq")

    assert facts.mcq is True


def test_benchmark_row_renders_str_scorer_kwargs_format_safe() -> None:
    """The first str scorer kwarg (lab_bench's no_answer) must emit DOUBLE-quoted
    — repr's single quotes would fail the ruff-format gate on the emitted file."""

    rows = render_generated_rows(
        "quiz",
        _facts(
            mcq=True,
            prompt_template=None,
            scorer="inspect_evals.lab_bench.lab_bench:precision_choice",
            scorer_kwargs={"no_answer": "Insufficient information."},
        ),
        HubDatasetFacts(revision="c" * 40, case_count=7, license="mit"),
    )

    assert '"no_answer": "Insufficient information."' in rows.benchmark
    ast.parse(f"BENCHMARKS = (\n{rows.benchmark})")


def test_custom_solver_gets_a_review_flag() -> None:
    """A solver the importer cannot classify must be pointed out, not papered over."""

    rows = render_generated_rows(
        "quiz",
        _facts(unreproduced_solvers=("inspect_evals/mmlu_multiple_choice",)),
        HubDatasetFacts(revision="c" * 40, case_count=7, license="mit"),
    )

    assert "TODO(review)" in rows.cases
    assert "mmlu_multiple_choice" in rows.cases


# ---------------------------------------------------------------------------
# write_generated_rows — in-place insertion at the anchors
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine_src_copy(tmp_path: Path) -> Path:
    """A working copy of the real three files — the insertion contract's ground truth."""

    for name in ("pins.py", "prepare.py", "benchmarks.py"):
        shutil.copy(_SRC_DIR / name, tmp_path / name)
    return tmp_path


def _generate(engine_src: Path, key: str = "sums", **fact_overrides: Any) -> None:
    write_generated_rows(
        key,
        _facts(**fact_overrides),
        HubDatasetFacts(revision="c" * 40, case_count=42, license="mit"),
        engine_src=engine_src,
    )


def test_generate_rows_lands_all_three_rows_in_parseable_files(engine_src_copy: Path) -> None:
    _generate(engine_src_copy)

    pins = (engine_src_copy / "pins.py").read_text()
    prepare = (engine_src_copy / "prepare.py").read_text()
    benchmarks = (engine_src_copy / "benchmarks.py").read_text()
    for text, name in ((pins, "pins.py"), (prepare, "prepare.py"), (benchmarks, "benchmarks.py")):
        ast.parse(text, filename=name)
    assert 'SUMS_DATASET = "acme/sums"' in pins
    assert '"sums": CasesSpec(' in prepare
    assert 'key="sums"' in benchmarks
    # The CasesSpec entry reads the pins constants; the import block must carry them.
    assert "SUMS_CASE_COUNT," in prepare


def test_generate_rows_refuses_a_key_that_already_exists(engine_src_copy: Path) -> None:
    with pytest.raises(ImporterError, match="gsm8k"):
        _generate(engine_src_copy, key="gsm8k")


def test_generated_cases_row_resolves_against_the_real_spec(
    engine_src_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The inserted entry must construct a real CasesSpec when the file executes."""

    _generate(engine_src_copy)

    namespace: dict[str, Any] = {}
    exec(compile((engine_src_copy / "pins.py").read_text(), "pins.py", "exec"), namespace)
    assert namespace["SUMS_DATASET"] == "acme/sums"
    assert namespace["SUMS_CASE_COUNT"] == 42


def test_unlisted_license_warns_but_emits(
    engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Owner decision 2026-09-16: the human review of the diff is the gate."""

    assert "proprietary" not in CLEARED_DATASET_LICENSES
    write_generated_rows(
        "sums",
        _facts(),
        HubDatasetFacts(revision="c" * 40, case_count=42, license="proprietary"),
        engine_src=engine_src_copy,
    )

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "proprietary" in err
    assert 'SUMS_DATASET = "acme/sums"' in (engine_src_copy / "pins.py").read_text()
    assert "license: proprietary" in (engine_src_copy / "pins.py").read_text()


# ---------------------------------------------------------------------------
# main — the CLI wiring, capture injected
# ---------------------------------------------------------------------------


def test_main_wires_reading_capture_and_insertion(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_fake_eval(monkeypatch, sums=_free_text_task)

    exit_code = importer_module.main(
        [
            f"{_FAKE_MODULE}:sums",
            "--key",
            "sums",
            "--engine-src",
            str(engine_src_copy),
        ],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 0
    assert '"sums": CasesSpec(' in (engine_src_copy / "prepare.py").read_text()
    assert "review the diff" in capsys.readouterr().out.lower()


def test_main_passes_task_args_through(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    def sums(fewshot: int = 10) -> Task:
        if fewshot:  # pragma: no cover — the guard IS the assertion
            raise AssertionError("importer must forward --task-arg fewshot=0")
        return _free_text_task()

    _install_fake_eval(monkeypatch, sums=sums)

    exit_code = importer_module.main(
        [
            f"{_FAKE_MODULE}:sums",
            "--key",
            "sums",
            "--task-arg",
            "fewshot=0",
            "--engine-src",
            str(engine_src_copy),
        ],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 0


# ---------------------------------------------------------------------------
# write_generated_rows hardening (review round 2 on PR 966)
# ---------------------------------------------------------------------------


def test_generate_rows_refuses_a_colliding_pin_prefix(engine_src_copy: Path) -> None:
    """ "foo-bar" and "foo_bar" both derive FOO_BAR_* constants — the second import
    would silently shadow the first benchmark's dataset/revision/count."""

    _generate(engine_src_copy, key="foo-bar")
    with pytest.raises(ImporterError, match="FOO_BAR"):
        _generate(engine_src_copy, key="foo_bar")


def test_generate_rows_writes_nothing_when_an_anchor_is_missing(engine_src_copy: Path) -> None:
    """All insertion points are validated BEFORE any write: a broken benchmarks.py anchor
    must not leave pins/prepare half-imported (a retry would then hit 'already
    exists' with no clean way back)."""

    benchmarks_path = engine_src_copy / "benchmarks.py"
    intact = benchmarks_path.read_text()
    anchor_line = next(
        line for line in intact.splitlines() if importer_module._BENCHMARKS_ANCHOR in line
    )
    benchmarks_path.write_text(intact.replace(anchor_line + "\n", ""))
    pins_before = (engine_src_copy / "pins.py").read_text()
    prepare_before = (engine_src_copy / "prepare.py").read_text()

    with pytest.raises(ImporterError, match="benchmarks.py"):
        _generate(engine_src_copy)

    assert (engine_src_copy / "pins.py").read_text() == pins_before
    assert (engine_src_copy / "prepare.py").read_text() == prepare_before
    # Restoring the anchor makes the SAME import succeed — no stale half-state.
    benchmarks_path.write_text(intact)
    _generate(engine_src_copy)
    assert '"sums": CasesSpec(' in (engine_src_copy / "prepare.py").read_text()


def test_generate_rows_refuses_a_key_that_is_not_an_identifier_stem(
    engine_src_copy: Path,
) -> None:
    """ "2wikimultihop" would emit `2WIKIMULTIHOP_DATASET = ...` — invalid Python that
    reports success and then cannot load. Refuse before writing."""

    with pytest.raises(ImporterError, match="identifier"):
        _generate(engine_src_copy, key="2wikimultihop")

    assert "2WIKIMULTIHOP" not in (engine_src_copy / "pins.py").read_text()


# ---------------------------------------------------------------------------
# custom choice template capture (the family renderer OME-1116 milestone C's
# benchmarks force: mmlu_pro / winogrande / race_h)
# ---------------------------------------------------------------------------


def test_read_inspect_task_captures_a_resolvable_custom_choice_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A custom multiple_choice template that IS a module attribute is a fact the
    prepare reproduces (choice_template reference), not a review flag."""

    def custom_mcq() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/quiz", split="test", sample_fields=module.record_to_sample
            ),
            solver=multiple_choice(template=module.CHOICE_TEMPLATE),
            scorer=choice(),
        )

    module = _install_fake_eval(monkeypatch, custom_mcq=custom_mcq)
    module.CHOICE_TEMPLATE = "Pick one of {letters}.\n{question}\n{choices}"  # type: ignore[attr-defined]

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:custom_mcq")

    assert facts.choice_template == f"{_FAKE_MODULE}:CHOICE_TEMPLATE"
    assert facts.unreproduced_solvers == ()


def test_captured_choice_template_lands_in_the_cases_row() -> None:
    rows = render_generated_rows(
        "quiz",
        _facts(
            mcq=True,
            prompt_template=None,
            scorer="inspect_ai.scorer:choice",
            scorer_kwargs={},
            choice_template=f"{_FAKE_MODULE}:CHOICE_TEMPLATE",
        ),
        HubDatasetFacts(revision="c" * 40, case_count=7, license="mit"),
    )

    assert f'choice_template="{_FAKE_MODULE}:CHOICE_TEMPLATE"' in rows.cases
    ast.parse(f"BENCHMARK_CASES = {{\n{rows.cases}}}")


def test_read_inspect_task_refuses_a_task_local_record_to_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row rule defined INSIDE the task function (truthfulqa's closure) can never
    be resolved by the dotted reference the row carries — refuse at import time,
    not with a dangling reference that fails at image build."""

    def closure_task() -> Task:
        module = sys.modules[_FAKE_MODULE]

        def record_to_sample(row: dict[str, Any]) -> Sample:
            return Sample(input=str(row["q"]), target=str(row["a"]))

        record_to_sample.__module__ = _FAKE_MODULE
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=record_to_sample
            ),
            solver=generate(),
            scorer=match(),
        )

    _install_fake_eval(monkeypatch, closured=closure_task)

    with pytest.raises(ImporterError, match="task-local"):
        read_inspect_task(f"{_FAKE_MODULE}:closured")


def test_rendered_row_lines_fit_the_lint_gate() -> None:
    """A long task_ref must never emit a line the 100-column lint gate rejects."""

    long_ref = "inspect_evals.some_very_long_package_name.some_very_long_package_name:the_task"
    rows = render_generated_rows(
        "long", _facts(task_ref=long_ref), HubDatasetFacts("c" * 40, 42, "cc-by-sa-4.0")
    )
    for row_text in (rows.pins, rows.cases, rows.benchmark):
        assert all(len(line) <= 100 for line in row_text.splitlines())


# ---------------------------------------------------------------------------
# dataset-kwarg reproduction (review round 2026-09-17 on this branch: every
# fact the importer reads but does not reproduce must refuse or flag — never
# silently drop benchmark identity)
# ---------------------------------------------------------------------------


def _task_with_dataset_kwargs(**dataset_kwargs: Any) -> Any:
    def task_fn() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums",
                split="test",
                sample_fields=module.record_to_sample,
                **dataset_kwargs,
            ),
            solver=generate(),
            scorer=match(),
        )

    return task_fn


def test_read_inspect_task_refuses_a_limit_the_prepare_would_ignore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An eval with limit=N examines N cases; preparing the full split would publish
    a DIFFERENT benchmark with every guard green (review blocker, 2026-09-17)."""

    _install_fake_eval(monkeypatch, limited=_task_with_dataset_kwargs(limit=500))

    with pytest.raises(ImporterError, match="limit"):
        read_inspect_task(f"{_FAKE_MODULE}:limited")


def test_read_inspect_task_records_an_unseeded_choice_shuffle_as_a_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1264 replaces the former refusal: shuffle_choices is now REPRODUCED —
    reading the task records the fact, and main() demands a pinned seed before any
    row is emitted (the unseeded refusal moved there, next to shuffle's).

    WHY True must not become a seed: bool is an int subtype — reading
    shuffle_choices=True as seed 1 would silently pin an order upstream never
    meant (inspect itself checks bool before int for exactly this reason)."""

    _install_fake_eval(monkeypatch, shuffled=_task_with_dataset_kwargs(shuffle_choices=True))

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:shuffled")

    assert facts.upstream_shuffle_choices is True
    assert facts.upstream_choice_shuffle_seed is None


def test_read_inspect_task_records_a_seeded_choice_shuffle_as_a_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An int shuffle_choices is inspect's seeded form — the seed is a fact."""

    _install_fake_eval(monkeypatch, seeded=_task_with_dataset_kwargs(shuffle_choices=9))

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:seeded")

    assert facts.upstream_shuffle_choices is True
    assert facts.upstream_choice_shuffle_seed == 9


def test_read_inspect_task_refuses_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """data_dir is a different load_dataset parameter than config — aliasing them
    loads the wrong data whenever they differ (gsm8k's 'main' was a coincidence)."""

    _install_fake_eval(monkeypatch, dirred=_task_with_dataset_kwargs(data_dir="data"))

    with pytest.raises(ImporterError, match="data_dir"):
        read_inspect_task(f"{_FAKE_MODULE}:dirred")


def test_read_inspect_task_records_an_upstream_shuffle_as_a_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_eval(monkeypatch, mixed=_task_with_dataset_kwargs(shuffle=True, seed=42))

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:mixed")

    assert facts.upstream_shuffle is True
    assert facts.upstream_shuffle_seed == 42


def test_read_inspect_task_ignores_benign_dataset_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto_id / trust / cached change how loading happens, never what the benchmark is."""

    _install_fake_eval(
        monkeypatch, benign=_task_with_dataset_kwargs(auto_id=True, trust=True, cached=False)
    )

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:benign")

    assert facts.dataset == "acme/sums"
    assert facts.upstream_shuffle is False


def test_read_inspect_task_binds_positional_hf_dataset_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """17 of 80 real call sites pass path positionally — a kwargs-only recorder
    would KeyError on path and silently pin split to '' (review should-fix 1)."""

    def positional() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset("acme/sums", "test", sample_fields=module.record_to_sample),
            solver=generate(),
            scorer=match(),
        )

    _install_fake_eval(monkeypatch, positional=positional)

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:positional")

    assert facts.dataset == "acme/sums"
    assert facts.split == "test"


def test_single_call_fallback_requires_the_task_to_hold_the_recorded_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An eval whose benchmark is a local dataset but whose fewshots load from HF must
    refuse — the fewshot split is NOT the benchmark (review should-fix 3)."""

    def json_quiz() -> Task:
        module = sys.modules[_FAKE_MODULE]
        module.hf_dataset(path="acme/sums", split="train", sample_fields=module.record_to_sample)
        return Task(
            dataset=[Sample(input="local exam", target="1")],
            solver=generate(),
            scorer=match(),
        )

    _install_fake_eval(monkeypatch, json_quiz=json_quiz)

    with pytest.raises(ImporterError, match="dataset"):
        read_inspect_task(f"{_FAKE_MODULE}:json_quiz")


def test_shuffling_eval_requires_a_pinned_seed(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """shuffle=True with no upstream seed means upstream order is random per run;
    an import must pin ONE order (a policy --shuffle-seed) or refuse.

    AIDEV-NOTE: ALWAYS pass --engine-src in importer main() tests — the default
    is the REAL package directory, and a red-phase run of this very test once
    wrote fake rows into it.
    """

    _install_fake_eval(monkeypatch, shuffling=_task_with_dataset_kwargs(shuffle=True))

    exit_code = importer_module.main(
        [f"{_FAKE_MODULE}:shuffling", "--key", "shuffling", "--engine-src", str(engine_src_copy)],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 1
    assert "shuffling" not in (engine_src_copy / "pins.py").read_text()


def test_an_upstream_shuffle_seed_is_reproduced_in_the_rows(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """An eval that shuffles with its own seed has a reproducible order — the row
    carries that seed (same permutation: seeded shuffle over an equal-length list)."""

    _install_fake_eval(monkeypatch, seeded=_task_with_dataset_kwargs(shuffle=True, seed=42))

    exit_code = importer_module.main(
        [f"{_FAKE_MODULE}:seeded", "--key", "seeded", "--engine-src", str(engine_src_copy)],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 0
    assert "SEEDED_SHUFFLE_SEED = 42" in (engine_src_copy / "pins.py").read_text()


def test_choice_shuffling_eval_requires_a_pinned_seed(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """shuffle_choices=True with no seed means each case's choice order is random
    per run upstream; an import must pin ONE order (--choice-shuffle-seed) or
    refuse — reproduced, never dropped (OME-1264)."""

    _install_fake_eval(monkeypatch, shuffled=_task_with_dataset_kwargs(shuffle_choices=True))

    exit_code = importer_module.main(
        [f"{_FAKE_MODULE}:shuffled", "--key", "shuffled", "--engine-src", str(engine_src_copy)],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 1
    # By the derived constant stem — prose in pins.py already says "shuffled".
    assert "SHUFFLED_DATASET" not in (engine_src_copy / "pins.py").read_text()


def test_upstream_row_seed_with_a_choice_shuffle_is_refused(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """Review blocker on PR #1031: the prepare step's row shuffle is Python's, upstream's
    is HF's — same seed, different order — and the choice shuffle draws each
    case's permutation from ONE stream in row order. So when upstream SEEDS a
    shuffle (it defined one benchmark) and both shuffles combine, the prepare step cannot
    reproduce that benchmark and must refuse, never ship a different one silently."""

    _install_fake_eval(
        monkeypatch, both=_task_with_dataset_kwargs(shuffle=True, seed=42, shuffle_choices=True)
    )

    exit_code = importer_module.main(
        [
            f"{_FAKE_MODULE}:both",
            "--key",
            "both",
            "--choice-shuffle-seed",
            "7",
            "--engine-src",
            str(engine_src_copy),
        ],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 1
    assert "BOTH_DATASET" not in (engine_src_copy / "pins.py").read_text()


def test_upstream_choice_seed_with_a_row_shuffle_is_refused(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """The symmetric bad cell: upstream pinned the CHOICE seed over the dataset's
    own row order, so adding any row shuffle (here a policy --shuffle-seed) moves
    every case's position and changes each permutation — refused, not shipped."""

    _install_fake_eval(monkeypatch, seededchoices=_task_with_dataset_kwargs(shuffle_choices=9))

    exit_code = importer_module.main(
        [
            f"{_FAKE_MODULE}:seededchoices",
            "--key",
            "seededchoices",
            "--shuffle-seed",
            "7",
            "--engine-src",
            str(engine_src_copy),
        ],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 1
    assert "SEEDEDCHOICES_DATASET" not in (engine_src_copy / "pins.py").read_text()


def test_policy_seeded_double_shuffle_is_allowed(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """The lab_bench cell stays importable: upstream seeds NEITHER shuffle, so
    there is no fixed upstream benchmark to miss — both policy seeds pin one, and
    both pins land in the rows."""

    _install_fake_eval(
        monkeypatch, policyboth=_task_with_dataset_kwargs(shuffle=True, shuffle_choices=True)
    )

    exit_code = importer_module.main(
        [
            f"{_FAKE_MODULE}:policyboth",
            "--key",
            "policyboth",
            "--shuffle-seed",
            "7",
            "--choice-shuffle-seed",
            "7",
            "--engine-src",
            str(engine_src_copy),
        ],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 0
    pins_text = (engine_src_copy / "pins.py").read_text()
    assert "POLICYBOTH_SHUFFLE_SEED = 7" in pins_text
    assert "POLICYBOTH_CHOICE_SHUFFLE_SEED = 7" in pins_text


def test_a_policy_choice_shuffle_seed_is_reproduced_in_the_rows(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """--choice-shuffle-seed pins one choice order as benchmark identity: the pin row
    and the CasesSpec field both land in the generated files."""

    _install_fake_eval(monkeypatch, shuffled=_task_with_dataset_kwargs(shuffle_choices=True))

    exit_code = importer_module.main(
        [
            f"{_FAKE_MODULE}:shuffled",
            "--key",
            "shuffled",
            "--choice-shuffle-seed",
            "7",
            "--engine-src",
            str(engine_src_copy),
        ],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 0
    assert "SHUFFLED_CHOICE_SHUFFLE_SEED = 7" in (engine_src_copy / "pins.py").read_text()
    assert (
        "choice_shuffle_seed=SHUFFLED_CHOICE_SHUFFLE_SEED,"
        in (engine_src_copy / "prepare.py").read_text()
    )


def test_an_upstream_choice_shuffle_seed_is_reproduced_in_the_rows(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """An eval that seeds its own choice shuffle is reproducible — the row carries
    that seed with no flag needed (same resolution order as shuffle/seed)."""

    _install_fake_eval(monkeypatch, seeded=_task_with_dataset_kwargs(shuffle_choices=9))

    exit_code = importer_module.main(
        [f"{_FAKE_MODULE}:seeded", "--key", "seeded", "--engine-src", str(engine_src_copy)],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 0
    assert "SEEDED_CHOICE_SHUFFLE_SEED = 9" in (engine_src_copy / "pins.py").read_text()


def test_choice_shuffle_seed_flag_is_refused_when_the_eval_pins_its_own(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """A seeded upstream (shuffle_choices=N) defines ONE benchmark — overriding it with
    a policy seed would silently prepare a benchmark upstream never produces (review
    finding on PR #1031). The flag is refused, same rationale as the stray-flag
    refusal one test down."""

    _install_fake_eval(monkeypatch, seeded=_task_with_dataset_kwargs(shuffle_choices=9))

    exit_code = importer_module.main(
        [
            f"{_FAKE_MODULE}:seeded",
            "--key",
            "seeded",
            "--choice-shuffle-seed",
            "7",
            "--engine-src",
            str(engine_src_copy),
        ],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 1
    assert "SEEDED_DATASET" not in (engine_src_copy / "pins.py").read_text()


def test_choice_shuffle_seed_flag_without_an_upstream_choice_shuffle_is_refused(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """Shuffling choices the eval does NOT shuffle would prepare a different benchmark —
    the stray policy flag refuses instead of silently deviating from upstream."""

    _install_fake_eval(monkeypatch, plain=_task_with_dataset_kwargs())

    exit_code = importer_module.main(
        [
            f"{_FAKE_MODULE}:plain",
            "--key",
            "plain",
            "--choice-shuffle-seed",
            "7",
            "--engine-src",
            str(engine_src_copy),
        ],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 1
    assert "plain" not in (engine_src_copy / "pins.py").read_text()


def test_read_inspect_task_records_data_files_and_a_features_pointer_as_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1264 extension 2: data_files is a literal fact; features is a
    Features SCHEMA living in a module constant (infinite_bench's `ft`), so the
    fact is a dotted POINTER at the eval's own attribute — the row points,
    never copies (same pattern as record_to_sample/system_message)."""

    schema = object()
    module = _install_fake_eval(
        monkeypatch,
        filed=_task_with_dataset_kwargs(data_files={"test": "test.jsonl"}, features=schema),
    )
    module.FEATURES = schema  # type: ignore[attr-defined]

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:filed")

    assert facts.data_files == {"test": "test.jsonl"}
    assert facts.features == f"{_FAKE_MODULE}:FEATURES"


def test_read_inspect_task_refuses_a_features_value_with_no_module_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inline Features(...) has no attribute the row could point at — refuse
    by name rather than serialize a schema the diff reviewer cannot anchor."""

    _install_fake_eval(monkeypatch, inlined=_task_with_dataset_kwargs(features=object()))

    with pytest.raises(ImporterError, match="features"):
        read_inspect_task(f"{_FAKE_MODULE}:inlined")


def test_read_inspect_task_refuses_an_exotic_data_files_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the shape the prepare step reproduces (dict[str, str]) is reproduced;
    anything else — even a bare str — refuses by name, never dropped."""

    _install_fake_eval(monkeypatch, exotic=_task_with_dataset_kwargs(data_files=123))

    with pytest.raises(ImporterError, match="data_files"):
        read_inspect_task(f"{_FAKE_MODULE}:exotic")


def test_data_files_and_features_are_reproduced_in_the_rows(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """The emitted rows carry the data_files pin and the features pointer, so
    the prepare step loads exactly the files and schema the eval declares."""

    schema = object()
    module = _install_fake_eval(
        monkeypatch,
        filed=_task_with_dataset_kwargs(data_files={"test": "test.jsonl"}, features=schema),
    )
    module.FEATURES = schema  # type: ignore[attr-defined]

    exit_code = importer_module.main(
        [f"{_FAKE_MODULE}:filed", "--key", "filed", "--engine-src", str(engine_src_copy)],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 42,
    )

    assert exit_code == 0
    assert 'FILED_DATA_FILES = {"test": "test.jsonl"}' in (engine_src_copy / "pins.py").read_text()
    assert f'features="{_FAKE_MODULE}:FEATURES"' in (engine_src_copy / "prepare.py").read_text()


# ---------------------------------------------------------------------------
# generated code is an injection sink (review should-fix 4): Hub-controlled
# strings must never be able to land an executable line in the emitted files
# ---------------------------------------------------------------------------


def test_generate_refuses_a_hostile_license_string(engine_src_copy: Path) -> None:
    hostile = 'mit"\nimport os  # pwned\nX = "'
    with pytest.raises(ImporterError, match="license"):
        write_generated_rows(
            "sums",
            _facts(),
            HubDatasetFacts(revision="c" * 40, case_count=42, license=hostile),
            engine_src=engine_src_copy,
        )


def test_generate_refuses_a_hostile_dataset_name(engine_src_copy: Path) -> None:
    with pytest.raises(ImporterError, match="dataset"):
        write_generated_rows(
            "sums",
            _facts(dataset='acme/sums"\nimport os\nY = "'),
            HubDatasetFacts(revision="c" * 40, case_count=42, license="mit"),
            engine_src=engine_src_copy,
        )


def test_generate_refuses_a_hostile_data_files_entry(engine_src_copy: Path) -> None:
    """data_files strings land in a generated dict literal — same injection
    sink, same charset guard (OME-1264 extension 2)."""

    hostile_facts = _facts(data_files={"test": 'x"\nimport os\nZ = "'})
    hostile_hub_facts = HubDatasetFacts(revision="d" * 40, case_count=7, license="apache-2.0")
    with pytest.raises(ImporterError, match="data_files"):
        write_generated_rows("quiz", hostile_facts, hostile_hub_facts, engine_src=engine_src_copy)


def test_generate_refuses_a_revision_that_is_not_a_commit_sha(engine_src_copy: Path) -> None:
    """The capture stage must never record 'None' or a short ref as benchmark identity."""

    with pytest.raises(ImporterError, match="revision"):
        write_generated_rows(
            "sums",
            _facts(),
            HubDatasetFacts(revision="None", case_count=42, license="mit"),
            engine_src=engine_src_copy,
        )


# ---------------------------------------------------------------------------
# round-trip: emitted rows must CONSTRUCT the real dataclasses (OME-1214). The
# ast.parse checks above catch template syntax bugs; only construction against
# the real spec catches a renamed or newly-required field.
# ---------------------------------------------------------------------------


def test_emitted_cases_row_constructs_the_real_cases_spec(engine_src_copy: Path) -> None:
    """An emitted prepare.py row must construct the real CasesSpec, so a spec
    change breaks here — in the spec-changer's own PR — not as a TypeError inside
    a generated file at the next import session.

    INVARIANT: the dataclasses ARE the schema — the emitted kwargs are checked by
    constructing the real spec, never against a parallel copy that could drift.
    """

    from screamingface_engine_inspect.prepare import CasesSpec

    # The maximal row: every optional kwarg the template can emit is emitted.
    rows = write_generated_rows(
        "sums",
        _facts(choice_template=f"{_FAKE_MODULE}:CHOICE_TEMPLATE"),
        HubDatasetFacts(revision="c" * 40, case_count=42, license="mit"),
        engine_src=engine_src_copy,
        shuffle_seed=7,
    )

    # The row reads pin constants — take them from the written copy, exactly as
    # prepare.py resolves them at import time.
    namespace: dict[str, Any] = {"CasesSpec": CasesSpec}
    exec(compile((engine_src_copy / "pins.py").read_text(), "pins.py", "exec"), namespace)
    exec(f"BENCHMARK_CASES = {{\n{rows.cases}}}", namespace)

    cases: Any = namespace["BENCHMARK_CASES"]["sums"]
    assert isinstance(cases, CasesSpec)
    assert cases.dataset == "acme/sums"
    assert cases.config == "main"
    assert cases.split == "test"
    assert cases.dataset_revision == "c" * 40
    assert cases.case_count == 42
    assert cases.record_to_sample == f"{_FAKE_MODULE}:record_to_sample"
    assert cases.prompt_template == f"{_FAKE_MODULE}:TEMPLATE"
    assert cases.choice_template == f"{_FAKE_MODULE}:CHOICE_TEMPLATE"
    assert cases.shuffle_seed == 7

    # The exec above resolves pin constants from ALL of pins.py, but the written
    # prepare.py resolves them through its import block — a constant the generated row
    # references that import_names forgot would NameError only at the next import
    # session (importer.py keeps the two lists independently; review finding on
    # this PR). Pin both directions, through the maximal row — the only one that
    # exercises the conditional shuffle_seed arm of both lists.
    referenced: set[str] = set(re.findall(r"\bSUMS_[A-Z_]+\b", rows.cases))
    assert referenced == set(rows.import_names)
    # Slice the pins import block by its own header — the first ")" in the file
    # sits inside the module docstring, far above the import.
    prepare_text: str = (engine_src_copy / "prepare.py").read_text()
    start: int = prepare_text.index(importer_module._PINS_IMPORT_HEADER)
    import_block: str = prepare_text[start : prepare_text.index(")", start)]
    assert all(name in import_block for name in rows.import_names)


def test_emitted_benchmark_row_constructs_the_real_benchmark_spec(engine_src_copy: Path) -> None:
    """An emitted benchmarks.py row must construct the real BenchmarkSpec, so a spec
    change breaks here — in the spec-changer's own PR — not at the next import.

    INVARIANT: same as the prepared cases round-trip — construction against the real
    dataclass is the schema check; no parallel copy.
    """

    from screamingface_engine_inspect.benchmarks import BenchmarkSpec

    rows = write_generated_rows(
        "sums",
        _facts(),
        HubDatasetFacts(revision="c" * 40, case_count=42, license="mit"),
        engine_src=engine_src_copy,
    )

    namespace: dict[str, Any] = {"BenchmarkSpec": BenchmarkSpec}
    exec(f"BENCHMARKS = (\n{rows.benchmark})", namespace)

    (benchmark,) = namespace["BENCHMARKS"]
    assert isinstance(benchmark, BenchmarkSpec)
    assert benchmark.key == "sums"
    assert benchmark.dataset_url == "https://huggingface.co/datasets/acme/sums"
    assert benchmark.scorer == "inspect_ai.scorer:match"
    assert dict(benchmark.scorer_kwargs) == {"numeric": True}
    # Free text ⇒ the draft-feedback offer is legitimate and declared (OME-796).
    assert benchmark.with_check_surface is True
    # Catalogue prose stays the importing agent's job — the tool emits TODOs.
    assert benchmark.title == "TODO"


def test_emitted_minimal_cases_row_constructs_the_real_cases_spec(
    engine_src_copy: Path,
) -> None:
    """The template's OTHER branch: a row with no prompt_template, no
    choice_template and no shuffle_seed must also construct the real spec.

    WHY a separate minimal variant: making an optional CasesSpec field
    required (dropping its default) keeps the maximal-row test green — only a
    row that OMITS the kwarg catches it (review finding on this PR).
    """

    from screamingface_engine_inspect.prepare import CasesSpec

    rows = write_generated_rows(
        "quiz",
        _facts(mcq=True, prompt_template=None, scorer="inspect_ai.scorer:choice", scorer_kwargs={}),
        HubDatasetFacts(revision="c" * 40, case_count=7, license="mit"),
        engine_src=engine_src_copy,
    )

    namespace: dict[str, Any] = {"CasesSpec": CasesSpec}
    exec(compile((engine_src_copy / "pins.py").read_text(), "pins.py", "exec"), namespace)
    exec(f"BENCHMARK_CASES = {{\n{rows.cases}}}", namespace)

    cases: Any = namespace["BENCHMARK_CASES"]["quiz"]
    assert isinstance(cases, CasesSpec)
    assert cases.dataset == "acme/sums"
    assert cases.case_count == 7
    # The omitted kwargs resolve through the spec's own defaults.
    assert cases.prompt_template is None
    assert cases.choice_template is None
    assert cases.shuffle_seed is None
    assert cases.choice_shuffle_seed is None


def test_emitted_choice_shuffled_cases_row_constructs_the_real_cases_spec(
    engine_src_copy: Path,
) -> None:
    """The choice_shuffle_seed arm of the template: its pin must be emitted, be in
    import_names, and construct the real CasesSpec (OME-1264)."""

    from screamingface_engine_inspect.prepare import CasesSpec

    rows = write_generated_rows(
        "quiz",
        _facts(mcq=True, prompt_template=None, scorer="inspect_ai.scorer:choice", scorer_kwargs={}),
        HubDatasetFacts(revision="c" * 40, case_count=7, license="mit"),
        engine_src=engine_src_copy,
        choice_shuffle_seed=7,
    )

    namespace: dict[str, Any] = {"CasesSpec": CasesSpec}
    exec(compile((engine_src_copy / "pins.py").read_text(), "pins.py", "exec"), namespace)
    exec(f"BENCHMARK_CASES = {{\n{rows.cases}}}", namespace)

    cases: Any = namespace["BENCHMARK_CASES"]["quiz"]
    assert isinstance(cases, CasesSpec)
    assert cases.choice_shuffle_seed == 7
    assert cases.shuffle_seed is None
    # Both directions of the pin-name contract (same check as the maximal row).
    referenced: set[str] = set(re.findall(r"\bQUIZ_[A-Z_]+\b", rows.cases))
    assert referenced == set(rows.import_names)


def test_emitted_data_files_cases_row_constructs_the_real_cases_spec(
    engine_src_copy: Path,
) -> None:
    """The data_files/features arm of the template: the pin plus the pointer
    must construct the real CasesSpec (OME-1264 extension 2)."""

    from screamingface_engine_inspect.prepare import CasesSpec

    rows = write_generated_rows(
        "filed",
        _facts(data_files={"test": "test.jsonl"}, features=f"{_FAKE_MODULE}:FEATURES"),
        HubDatasetFacts(revision="c" * 40, case_count=42, license="mit"),
        engine_src=engine_src_copy,
    )

    namespace: dict[str, Any] = {"CasesSpec": CasesSpec}
    exec(compile((engine_src_copy / "pins.py").read_text(), "pins.py", "exec"), namespace)
    exec(f"BENCHMARK_CASES = {{\n{rows.cases}}}", namespace)

    cases: Any = namespace["BENCHMARK_CASES"]["filed"]
    assert isinstance(cases, CasesSpec)
    assert cases.data_files == {"test": "test.jsonl"}
    assert cases.features == f"{_FAKE_MODULE}:FEATURES"
    referenced: set[str] = set(re.findall(r"\bFILED_[A-Z_]+\b", rows.cases))
    assert referenced == set(rows.import_names)


def test_emitted_mcq_benchmark_row_constructs_the_real_benchmark_spec(
    engine_src_copy: Path,
) -> None:
    """The benchmark template's OTHER branch: an MCQ row omits scorer_kwargs AND
    with_check_surface — it must still construct the real BenchmarkSpec.

    WHY a separate MCQ variant: dropping the default of either omitted field
    keeps the free-text-row test green — only this row catches it (review
    finding on this PR).
    """

    from screamingface_engine_inspect.benchmarks import BenchmarkSpec

    rows = write_generated_rows(
        "quiz",
        _facts(mcq=True, prompt_template=None, scorer="inspect_ai.scorer:choice", scorer_kwargs={}),
        HubDatasetFacts(revision="c" * 40, case_count=7, license="mit"),
        engine_src=engine_src_copy,
    )

    namespace: dict[str, Any] = {"BenchmarkSpec": BenchmarkSpec}
    exec(f"BENCHMARKS = (\n{rows.benchmark})", namespace)

    (benchmark,) = namespace["BENCHMARKS"]
    assert isinstance(benchmark, BenchmarkSpec)
    assert benchmark.key == "quiz"
    assert benchmark.scorer == "inspect_ai.scorer:choice"
    # The omitted kwargs resolve through the spec's own defaults (OME-796: MCQ
    # benchmarks never declare the draft-feedback offer).
    assert dict(benchmark.scorer_kwargs) == {}
    assert benchmark.with_check_surface is False


def test_injection_charsets_refuse_a_trailing_newline(engine_src_copy: Path) -> None:
    """`$` tolerates one trailing newline; the guards anchor with \\Z so a
    newline can never open a second line in generated code."""

    with pytest.raises(ImporterError, match="license"):
        write_generated_rows(
            "sums",
            _facts(),
            HubDatasetFacts(revision="c" * 40, case_count=42, license="mit\n"),
            engine_src=engine_src_copy,
        )


def test_read_inspect_task_binds_a_module_level_system_message_as_a_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1253 (owner-approved): an eval's system instruction kept in a module
    constant is delivered as LEADING INPUT TEXT at prepare time (a benchmark cannot
    address a candidate's system role — contracteval precedent), so the row
    POINTS at it as a fact instead of dropping it behind a review flag. An
    inline-literal system message still flags (the prior test)."""

    from inspect_ai.solver import system_message

    def storyteller() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            solver=[system_message(module.INSTRUCTIONS), generate()],
            scorer=match(numeric=True),
        )

    module = _install_fake_eval(monkeypatch, storyteller=storyteller)
    module.INSTRUCTIONS = "Choose the most plausible continuation for the story."  # type: ignore[attr-defined]

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:storyteller")

    assert facts.system_message == f"{_FAKE_MODULE}:INSTRUCTIONS"
    assert facts.unreproduced_solvers == ()


def _read_inspect_task_with_module_system_message(
    monkeypatch: pytest.MonkeyPatch, instructions: str, **params: Any
) -> InspectTaskFacts:
    """Read an eval whose system_message points at module.INSTRUCTIONS."""

    from inspect_ai.solver import system_message

    def storyteller() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            solver=[system_message(module.INSTRUCTIONS, **params), generate()],
            scorer=match(numeric=True),
        )

    module = _install_fake_eval(monkeypatch, storyteller=storyteller)
    module.INSTRUCTIONS = instructions  # type: ignore[attr-defined]
    return read_inspect_task(f"{_FAKE_MODULE}:storyteller")


def test_read_inspect_task_flags_a_system_message_that_fills_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1272: system_message(template, **params) sends the template AFTER
    str.format fills the params in. Binding the bare constant would prepare text
    the eval never sends — so the row gets no fact and the flag names the param."""

    facts: InspectTaskFacts = _read_inspect_task_with_module_system_message(
        monkeypatch, "Answer as {persona}.", persona="a patient tutor"
    )

    assert facts.system_message is None
    assert any(
        "system_message" in flag and "persona" in flag for flag in facts.unreproduced_solvers
    )


@pytest.mark.parametrize(
    "instructions",
    [
        # Filled at run time from sample metadata or the store, even with no params.
        "Answer as {persona}.",
        # str.format rewrites an escaped brace: the eval sends "{json}", not "{{json}}".
        "Reply in {{json}}.",
    ],
)
def test_read_inspect_task_flags_a_system_message_whose_text_str_format_rewrites(
    monkeypatch: pytest.MonkeyPatch, instructions: str
) -> None:
    """OME-1272: inspect runs every system message through str.format with the
    sample's metadata and store. Any brace in the text means the sent message can
    differ from the constant — per case, invisibly — so it flags instead of binding."""

    facts: InspectTaskFacts = _read_inspect_task_with_module_system_message(
        monkeypatch, instructions
    )

    assert facts.system_message is None
    assert any("system_message" in flag for flag in facts.unreproduced_solvers)


def test_read_inspect_task_flags_a_system_message_read_from_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OME-1272: a template that is a path to an existing file is READ by inspect
    (resource()), so the eval sends the file's contents. Binding the constant
    would prepare the path itself as the instruction."""

    prompt_file: Path = tmp_path / "system.txt"
    prompt_file.write_text("You are a careful accountant.")

    facts: InspectTaskFacts = _read_inspect_task_with_module_system_message(
        monkeypatch, str(prompt_file)
    )

    assert facts.system_message is None
    assert any("system_message" in flag for flag in facts.unreproduced_solvers)


def test_read_inspect_task_refuses_a_prompt_template_read_from_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OME-1272 (PR #1064 review): prompt_template() also READS a path through
    resource(), so the eval sends the file's template. The prepare step formats the
    constant's own text — a path with no {prompt} slot — so every case would
    become the path string. It refuses by name, like an unresolvable template."""

    template_file: Path = tmp_path / "user.txt"
    template_file.write_text("Solve: {prompt}")

    def from_file() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            solver=[prompt_template(module.TEMPLATE_PATH), generate()],
            scorer=match(numeric=True),
        )

    module = _install_fake_eval(monkeypatch, from_file=from_file)
    module.TEMPLATE_PATH = str(template_file)  # type: ignore[attr-defined]

    with pytest.raises(ImporterError, match="reads its template from a file"):
        read_inspect_task(f"{_FAKE_MODULE}:from_file")


def test_read_inspect_task_flags_a_chain_with_two_system_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1272 (PR #1064 review): inspect sends EVERY system message in the
    chain, but the row holds one pointer — the last used to win silently, so
    the prepare step dropped the first instruction. Now nothing binds and the flag
    says why."""

    from inspect_ai.solver import system_message

    def twice_instructed() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            solver=[
                system_message(module.PERSONA),
                system_message(module.INSTRUCTIONS),
                generate(),
            ],
            scorer=match(numeric=True),
        )

    module = _install_fake_eval(monkeypatch, twice_instructed=twice_instructed)
    module.PERSONA = "You are a careful accountant."  # type: ignore[attr-defined]
    module.INSTRUCTIONS = "Show your working."  # type: ignore[attr-defined]

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:twice_instructed")

    assert facts.system_message is None
    assert any("2 system messages" in flag for flag in facts.unreproduced_solvers)


def _read_inspect_task_with_setup_system_message(
    monkeypatch: pytest.MonkeyPatch, instructions: str
) -> InspectTaskFacts:
    """Read an eval whose system message lives in Task(setup=...)."""

    from inspect_ai.solver import system_message

    def set_up() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            setup=system_message(module.INSTRUCTIONS),
            solver=[generate()],
            scorer=match(numeric=True),
        )

    module = _install_fake_eval(monkeypatch, set_up=set_up)
    module.INSTRUCTIONS = instructions  # type: ignore[attr-defined]
    return read_inspect_task(f"{_FAKE_MODULE}:set_up")


def test_read_inspect_task_sees_a_system_message_in_task_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1272 (PR #1064 review): inspect runs Task(setup=...) before the
    solver chain, so a system message there reaches the candidate exactly like
    one in the chain. The walk used to skip setup, so the instruction vanished
    with no flag; a plain constant there now binds like any other."""

    facts: InspectTaskFacts = _read_inspect_task_with_setup_system_message(
        monkeypatch, "Choose the most plausible continuation for the story."
    )

    assert facts.system_message == f"{_FAKE_MODULE}:INSTRUCTIONS"
    assert facts.unreproduced_solvers == ()


def test_read_inspect_task_flags_a_rewritten_system_message_in_task_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The setup walk runs the same guard: a placeholder there flags, never binds."""

    facts: InspectTaskFacts = _read_inspect_task_with_setup_system_message(
        monkeypatch, "Answer as {persona}."
    )

    assert facts.system_message is None
    assert any("system_message" in flag for flag in facts.unreproduced_solvers)


@pytest.mark.parametrize("where", ["chain", "setup_and_chain"])
def test_read_inspect_task_refuses_a_task_with_two_prompt_templates(
    monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """OME-1272 (PR #1064 second review): inspect applies EVERY prompt_template in
    turn, each wrapping the previous one's output, but the row points at one
    template and the prepare step applies only it — the last one used to win silently.
    It refuses by name, like every other prompt template the prepare step cannot
    reproduce (an unresolvable one, a file path)."""

    def double_templated() -> Task:
        module = sys.modules[_FAKE_MODULE]
        outer: Any = prompt_template(module.OUTER)
        inner: Any = prompt_template(module.TEMPLATE)
        in_setup: bool = where == "setup_and_chain"
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            setup=outer if in_setup else None,
            solver=[inner, generate()] if in_setup else [outer, inner, generate()],
            scorer=match(numeric=True),
        )

    module = _install_fake_eval(monkeypatch, double_templated=double_templated)
    module.OUTER = "Think carefully.\n\n{prompt}"  # type: ignore[attr-defined]

    with pytest.raises(ImporterError, match="2 prompt templates"):
        read_inspect_task(f"{_FAKE_MODULE}:double_templated")


# ---------------------------------------------------------------------------
# model-graded scorers get the judge flag (OME-1240)
# ---------------------------------------------------------------------------


def test_a_model_graded_scorer_emits_the_judge_declaration_todo() -> None:
    """A judged eval must never emit a silently-failing row: the generated row carries a
    judge=JudgeSpec placeholder whose TODO model is refused at assembly by name."""

    rows = render_generated_rows(
        "judged",
        _facts(
            scorer="inspect_ai.scorer:model_graded_qa",
            scorer_kwargs={"model": "openai/gpt-4o", "template": "grade {answer}"},
        ),
        HubDatasetFacts(revision="c" * 40, case_count=7, license="mit"),
    )

    assert "TODO(review)" in rows.benchmark
    assert 'judge=JudgeSpec(model="TODO")' in rows.benchmark
    # The eval's own judge value is kept visible for the reviewer to replace.
    assert "openai/gpt-4o" in rows.benchmark
    ast.parse(f"BENCHMARKS = (\n{rows.benchmark})")


def test_a_string_match_scorer_emits_no_judge_lines() -> None:
    rows = render_generated_rows(
        "sums", _facts(), HubDatasetFacts(revision="c" * 40, case_count=42, license="mit")
    )
    assert "JudgeSpec" not in rows.benchmark


def test_a_custom_scorer_with_a_judge_model_kwarg_gets_the_judge_flag() -> None:
    """Detection keys on the KWARG, not the scorer name — frontierscience's custom
    scorer carries its judge under `model` and matched no model_graded_* name, so
    the importer emitted a silently-unjudged row (review finding, 2026-09-24)."""

    rows = render_generated_rows(
        "judged",
        _facts(
            scorer=f"{_FAKE_MODULE}:custom_scorer",
            scorer_kwargs={"model": None},
        ),
        HubDatasetFacts(revision="c" * 40, case_count=7, license="mit"),
    )
    assert 'judge=JudgeSpec(model="TODO")' in rows.benchmark
    assert "TODO(review)" in rows.benchmark


def test_a_judged_row_never_advertises_a_check_surface() -> None:
    """Assembly refuses judged rows with a draft-feedback offer (no check-cost knob yet) —
    the importer emitting both would strand the next import on a red gate it was
    told is already correct (review finding, 2026-09-24)."""

    rows = render_generated_rows(
        "judged",
        _facts(
            scorer="inspect_ai.scorer:model_graded_qa",
            scorer_kwargs={"model": "openai/gpt-4o"},
        ),
        HubDatasetFacts(revision="c" * 40, case_count=7, license="mit"),
    )
    assert "with_check_surface" not in rows.benchmark
    assert "keep_sample_metadata" in rows.benchmark  # the reviewer reminder rides the flag


# ---------------------------------------------------------------------------
# Question filter — evals that drop questions after loading (OME-1269)
# ---------------------------------------------------------------------------


def _filtering_task(subset: str = "kept", **dataset_kwargs: Any) -> Task:
    """pubmedqa's shape: load the split, then keep only some questions with a lambda.

    The keep-test rejects the probe's dummy question (target "A"), as every real
    one does — that rejection is what used to crash the import with "dataset is empty".
    """

    module = sys.modules[_FAKE_MODULE]
    dataset = module.hf_dataset(
        path="acme/sums",
        name="main",
        split="test",
        sample_fields=module.record_to_sample,
        **dataset_kwargs,
    )
    return Task(
        dataset=dataset.filter(
            lambda sample: sample.target not in ("A", "skip") and subset == "kept"
        ),
        solver=[prompt_template(module.TEMPLATE), generate()],
        scorer=match(numeric=True),
    )


def _dedupe_only_task() -> Task:
    """wmdp's shape: inspect_evals' duplicate-id remover is the only post-load filter."""

    from inspect_evals.utils.deps_utils import filter_duplicate_ids

    module = sys.modules[_FAKE_MODULE]
    dataset = module.hf_dataset(
        path="acme/sums", split="test", sample_fields=module.record_to_sample
    )
    return Task(dataset=filter_duplicate_ids(dataset), solver=generate(), scorer=match())


def _fewshot_filter_task() -> Task:
    """The filter trims the fewshot pool; the benchmark load is untouched."""

    module = sys.modules[_FAKE_MODULE]
    fewshots = module.hf_dataset(
        path="acme/sums", split="train", sample_fields=module.record_to_sample
    )
    fewshots.filter(lambda sample: sample.target != "skip")
    return _free_text_task()


def _filtering_two_loads_task() -> Task:
    """A filtered benchmark PLUS a second load — the question filter would feed both loads."""

    module = sys.modules[_FAKE_MODULE]
    module.hf_dataset(path="acme/sums", split="train", sample_fields=module.record_to_sample)
    return _filtering_task()


def test_read_inspect_task_reads_a_filtering_task_as_filtering_after_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 2: the probe's dummy question used to fail the eval's keep-test,
    and inspect crashed with "dataset is empty". Now the task builds, and the
    import names it as filtering after load with the args it ran with."""

    _install_fake_eval(monkeypatch, sums=_filtering_task)

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:sums", {"subset": "kept"})

    assert facts.filters_after_load is True
    assert facts.task_args == {"subset": "kept"}
    assert facts.dataset == "acme/sums"
    assert facts.prompt_template == f"{_FAKE_MODULE}:TEMPLATE"


def test_read_inspect_task_keeps_a_dedupe_only_task_on_todays_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Six live benchmarks (wmdp x3, mmlu, race_h, winogrande) run only the duplicate-id
    remover; sending them through their task would move their published revisions."""

    _install_fake_eval(monkeypatch, sums=_dedupe_only_task)

    assert read_inspect_task(f"{_FAKE_MODULE}:sums").filters_after_load is False


def test_read_inspect_task_ignores_a_filter_on_a_non_question_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the benchmark's questions matter — trimming a fewshot pool changes no benchmark."""

    _install_fake_eval(monkeypatch, sums=_fewshot_filter_task)

    assert read_inspect_task(f"{_FAKE_MODULE}:sums").filters_after_load is False


def test_read_inspect_task_refuses_a_filtering_task_that_loads_two_datasets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prepare step hands the pinned Samples to every load the task makes, so a second
    load would be fed the benchmark — refuse by name instead of preparing a wrong benchmark."""

    _install_fake_eval(monkeypatch, sums=_filtering_two_loads_task)

    with pytest.raises(ImporterError, match="loads 2 datasets"):
        read_inspect_task(f"{_FAKE_MODULE}:sums")


def test_read_inspect_task_refuses_a_filtering_task_with_a_seeded_choice_shuffle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upstream draws each case's choice order over ALL rows, before its filter; the
    prepare would draw over the kept rows only — a different benchmark for the same seed."""

    def seeded() -> Task:
        return _filtering_task(shuffle_choices=9)

    _install_fake_eval(monkeypatch, sums=seeded)

    with pytest.raises(ImporterError, match="choice-shuffle seed"):
        read_inspect_task(f"{_FAKE_MODULE}:sums")


def test_a_question_filter_row_names_the_task_and_its_args() -> None:
    rows = render_generated_rows(
        "sums",
        _facts(filters_after_load=True, task_args={"subset": "kept", "limit_to": 2}),
        HubDatasetFacts(revision="c" * 40, case_count=2, license="mit"),
    )

    assert f'question_filter_task="{_FAKE_MODULE}:sums",' in rows.cases
    assert 'question_filter_task_args={"limit_to": 2, "subset": "kept"},' in rows.cases
    ast.parse("x = {\n" + rows.cases + "}")


def test_a_row_without_a_question_filter_carries_no_task_field() -> None:
    """Every benchmark before OME-1269 must render exactly as it did."""

    rows = render_generated_rows(
        "sums", _facts(), HubDatasetFacts(revision="c" * 40, case_count=2, license="mit")
    )

    assert "question_filter_task=" not in rows.cases
    assert "question_filter_task_args=" not in rows.cases


def test_task_args_that_could_escape_the_row_are_refused(engine_src_copy: Path) -> None:
    with pytest.raises(ImporterError, match="injection guard"):
        _generate(engine_src_copy, filters_after_load=True, task_args={"subset": 'x"\nimport os'})


def test_a_question_filter_benchmark_counts_the_questions_the_eval_keeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The row's case count is the KEPT count (pubmedqa's 500, not 1,000 rows): the
    default counter runs the prepare step's own question filter over the pinned rows."""

    from screamingface_engine_inspect import prepare as prepare_module

    _install_fake_eval(monkeypatch, sums=_filtering_task)
    rows: list[dict[str, Any]] = [
        {"q": "1+1", "a": "2"},
        {"q": "dropped", "a": "skip"},
        {"q": "2+2", "a": "4"},
    ]
    monkeypatch.setattr(prepare_module, "_load_rows", lambda spec: rows)
    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:sums")

    assert importer_module._hub_count_rows(facts, "c" * 40) == 2


def test_main_imports_a_filtering_task_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    _install_fake_eval(monkeypatch, sums=_filtering_task)

    exit_code = importer_module.main(
        [f"{_FAKE_MODULE}:sums", "--key", "sums", "--engine-src", str(engine_src_copy)],
        dataset_info=lambda dataset, revision: _fake_info("a" * 40, "mit"),
        count_rows=lambda facts, revision: 2,
    )

    assert exit_code == 0
    prepare_text: str = (engine_src_copy / "prepare.py").read_text()
    assert f'question_filter_task="{_FAKE_MODULE}:sums",' in prepare_text


# ---------------------------------------------------------------------------
# multiple_choice(cot=True) — the chain-of-thought render (OME-1269, onet_m6)
# ---------------------------------------------------------------------------


def _cot_mcq_task(**solver_kwargs: Any) -> Any:
    def task_fn() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/quiz", split="test", sample_fields=module.record_to_sample
            ),
            solver=multiple_choice(**solver_kwargs),
            scorer=choice(),
        )

    return task_fn


def test_read_inspect_task_points_a_cot_mcq_at_inspects_own_cot_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cot=True swaps inspect's prompt for its "Think step by step" variant; before
    OME-1269 the importer ignored the flag, so the prepare step silently rendered the
    plain template — a different benchmark wording (onet_m6 hit this)."""

    from inspect_ai.solver._multiple_choice import SINGLE_ANSWER_TEMPLATE_COT

    from screamingface_engine_inspect.prepare import _resolve

    _install_fake_eval(monkeypatch, cot_mcq=_cot_mcq_task(cot=True))

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:cot_mcq")

    assert facts.choice_template == "inspect_ai.solver._multiple_choice:SINGLE_ANSWER_TEMPLATE_COT"
    assert _resolve(facts.choice_template) == SINGLE_ANSWER_TEMPLATE_COT
    assert facts.unreproduced_solvers == ()


def test_read_inspect_task_flags_cot_with_multiple_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    """The prepare step has no multi-answer render — flag it rather than guess a template."""

    _install_fake_eval(monkeypatch, cot_multi=_cot_mcq_task(cot=True, multiple_correct=True))

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:cot_multi")

    assert facts.choice_template is None
    assert any("cot" in flag for flag in facts.unreproduced_solvers)


# ---------------------------------------------------------------------------
# Gated datasets — the Hub's gate is observed, never typed (OME-1269, xstest)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hub_gated", "expected"), [("auto", True), ("manual", True), (False, False)]
)
def test_capture_records_whether_the_dataset_needs_an_hf_token(
    hub_gated: Any, expected: bool
) -> None:
    """The prepare step needs a token for a gated dataset; the importer reads the gate from
    the Hub (dataset_info.gated: False, "auto" or "manual") so the row says so."""

    info = types.SimpleNamespace(sha="c" * 40, card_data={"license": "cc-by-4.0"}, gated=hub_gated)

    hub_facts = read_hub_dataset_facts(
        _facts(), dataset_info=lambda dataset, revision: info, count_rows=lambda f, r: 3
    )

    assert hub_facts.needs_hf_token is expected


def test_a_row_needing_an_hf_token_says_so_and_a_public_row_does_not() -> None:
    token_row = render_generated_rows(
        "sums",
        _facts(),
        HubDatasetFacts(revision="c" * 40, case_count=3, license="mit", needs_hf_token=True),
    )
    public = render_generated_rows(
        "sums", _facts(), HubDatasetFacts(revision="c" * 40, case_count=3, license="mit")
    )

    assert "        needs_hf_token=True," in token_row.cases
    assert "needs_hf_token=" not in public.cases


def _dedupe_then_filter_task() -> Task:
    """Drops duplicates, THEN keeps a subset — the subset filter is the benchmark's."""

    from inspect_evals.utils.deps_utils import filter_duplicate_ids

    module = sys.modules[_FAKE_MODULE]
    dataset = module.hf_dataset(
        path="acme/sums", split="test", sample_fields=module.record_to_sample
    )
    deduped = filter_duplicate_ids(dataset)
    return Task(
        dataset=deduped.filter(lambda sample: sample.target != "A"),
        solver=generate(),
        scorer=match(),
    )


def test_read_inspect_task_flags_a_task_that_filters_after_dropping_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dedupe exemption covers the duplicate remover ONLY: an eval that dedupes and
    then keeps one subject (mmlu_0_shot with subjects) must still take the question filter, or
    the prepare step would ship every row while inspect runs the subset (review on PR #1110)."""

    _install_fake_eval(monkeypatch, sums=_dedupe_then_filter_task)

    assert read_inspect_task(f"{_FAKE_MODULE}:sums").filters_after_load is True


def test_read_inspect_task_refuses_a_filtering_task_that_numbers_rows_with_auto_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """inspect numbers auto_id rows 1..N at load; the prepare step's swapped loader does not,
    so a filter that reads ids would keep different questions (review on PR #1110)."""

    def numbered() -> Task:
        return _filtering_task(auto_id=True)

    _install_fake_eval(monkeypatch, sums=numbered)

    with pytest.raises(ImporterError, match="auto_id"):
        read_inspect_task(f"{_FAKE_MODULE}:sums")


def test_a_list_task_arg_is_refused_for_what_it_is(engine_src_copy: Path) -> None:
    """mmlu_0_shot(subjects=[...]) is not an injection attempt; the refusal must say
    the row has no place for a list (review on PR #1110)."""

    with pytest.raises(ImporterError, match="is a list") as refusal:
        _generate(engine_src_copy, filters_after_load=True, task_args={"subjects": ["anatomy"]})
    assert "injection" not in str(refusal.value)


def test_read_inspect_task_flags_an_evals_own_metrics_for_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A benchmark reports the mean per-case score. xstest reports refusal_rate instead,
    and the importer never looked, so the deviation went unnamed (review on PR #1112):
    a task's own metrics= must surface as a review item on the generated benchmark row."""

    from inspect_ai.scorer import accuracy

    def with_metrics() -> Task:
        task = _free_text_task()
        return Task(dataset=task.dataset, solver=task.solver, scorer=match(), metrics=[accuracy()])

    _install_fake_eval(monkeypatch, sums=with_metrics)

    facts: InspectTaskFacts = read_inspect_task(f"{_FAKE_MODULE}:sums")
    rows = render_generated_rows(
        "sums", facts, HubDatasetFacts(revision="c" * 40, case_count=3, license="mit")
    )

    assert facts.custom_metrics == ("inspect_ai/accuracy",)
    assert "TODO(review): the eval reports its own metric inspect_ai/accuracy" in rows.benchmark
    assert (
        "own metric"
        not in render_generated_rows(
            "sums", _facts(), HubDatasetFacts(revision="c" * 40, case_count=3, license="mit")
        ).benchmark
    )


# ── OME-1273: the four refusals that route to Task replay (spec R1) ─────────────

from inspect_ai.dataset import MemoryDataset  # noqa: E402

from screamingface_engine_inspect.importer import TaskReplayRoute  # noqa: E402


def test_a_module_with_no_hf_dataset_binding_routes_to_task_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _install_fake_eval(monkeypatch, sums=_free_text_task)
    del module.hf_dataset  # type: ignore[attr-defined]

    with pytest.raises(TaskReplayRoute, match="no hf_dataset binding"):
        read_inspect_task(f"{_FAKE_MODULE}:sums")


def test_a_task_that_never_calls_hf_dataset_routes_to_task_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def from_memory() -> Task:
        return Task(dataset=MemoryDataset([Sample(input="x", target="y")]), scorer=match())

    _install_fake_eval(monkeypatch, from_memory=from_memory)

    with pytest.raises(TaskReplayRoute, match="never called hf_dataset"):
        read_inspect_task(f"{_FAKE_MODULE}:from_memory")


def test_several_calls_none_the_tasks_dataset_route_to_task_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def two_loads_neither_held() -> Task:
        module = sys.modules[_FAKE_MODULE]
        for split in ("train", "test"):
            module.hf_dataset(path="acme/sums", split=split, sample_fields=module.record_to_sample)
        return Task(dataset=MemoryDataset([Sample(input="x", target="y")]), scorer=match())

    _install_fake_eval(monkeypatch, two=two_loads_neither_held)

    with pytest.raises(TaskReplayRoute, match="none is the Task's dataset"):
        read_inspect_task(f"{_FAKE_MODULE}:two")


def test_a_task_local_record_to_sample_routes_to_task_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def local_converter() -> Task:
        module = sys.modules[_FAKE_MODULE]

        def record_to_sample(row: dict[str, Any]) -> Sample:
            return Sample(input=str(row["q"]), target=str(row["a"]))

        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=record_to_sample
            ),
            scorer=match(),
        )

    _install_fake_eval(monkeypatch, local=local_converter)

    with pytest.raises(TaskReplayRoute, match="task-local"):
        read_inspect_task(f"{_FAKE_MODULE}:local")


def test_every_other_refusal_stays_a_plain_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec R1: only the four 'can't see the fetch' refusals route; a real mismatch never does."""

    def two_scorers() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(
                path="acme/sums", split="test", sample_fields=module.record_to_sample
            ),
            scorer=[match(), choice()],
        )

    _install_fake_eval(monkeypatch, two_scorers=two_scorers)

    with pytest.raises(ImporterError, match="exactly one scorer") as caught:
        read_inspect_task(f"{_FAKE_MODULE}:two_scorers")
    assert not isinstance(caught.value, TaskReplayRoute)


# ── OME-1273: the CLI imports by Task replay on a route or on request (R1, D12) ──

from collections.abc import Mapping  # noqa: E402

from screamingface_engine_inspect.case_sources import CaseSource  # noqa: E402
from screamingface_engine_inspect.import_replay import (  # noqa: E402
    TaskReplayFacts,
    TaskReplayImport,
)
from screamingface_engine_inspect.importer import main  # noqa: E402
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402


def _sealed_import(source: CaseSource | None = None) -> TaskReplayImport:
    """A sealed Task-replay import, as import_by_task_replay returns it — no child runs.

    Stand-in for the two replays: it proves the CLI writes what the import returns; the
    replays themselves are pinned in test_import_replay.py.
    """

    facts: TaskReplayFacts = TaskReplayFacts(
        task_ref=f"{_FAKE_MODULE}:sums",
        task_args={"cot": False},
        mcq=False,
        scorer="inspect_ai.scorer:match",
        scorer_kwargs={},
        custom_metrics=(),
        keep_sample_metadata=False,
    )
    return TaskReplayImport(
        declaration=TaskReplayCasesSpec(
            task=facts.task_ref, case_count=2, case_digest="e" * 64, task_args={"cot": False}
        ),
        case_sources=(source or CaseSource("url", "https://x.example/sums.jsonl", "unpinned"),),
        facts=facts,
    )


def test_main_imports_by_task_replay_when_the_reader_routes(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _install_fake_eval(monkeypatch, sums=_free_text_task)
    del module.hf_dataset  # type: ignore[attr-defined]
    seen: list[tuple[str, dict[str, Any] | None]] = []

    def fake_import(
        task_ref: str, task_args: Mapping[str, Any] | None, **_: Any
    ) -> TaskReplayImport:
        """Record the call the CLI made; return a sealed import."""

        seen.append((task_ref, dict(task_args) if task_args else None))
        return _sealed_import()

    code: int = main(
        [
            f"{_FAKE_MODULE}:sums",
            "--key",
            "sums_replayed",
            "--task-arg",
            "cot=False",
            "--engine-src",
            str(engine_src_copy),
        ],
        import_by_task_replay=fake_import,
    )

    assert code == 0
    assert seen == [(f"{_FAKE_MODULE}:sums", {"cot": False})]
    prepare_text: str = (engine_src_copy / "prepare.py").read_text()
    assert '"sums_replayed": TaskReplayCasesSpec(' in prepare_text
    assert 'task_args={"cot": False},' in prepare_text
    stderr: str = capsys.readouterr().err
    assert "importing by Task replay" in stderr
    assert "url https://x.example/sums.jsonl · pin unpinned" in stderr


def test_the_task_replay_flag_skips_the_hugging_face_reader(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """D12: bbh-like evals crash inside the reader's stand-in Sample, so no route fires."""

    def crashes_on_the_stand_in() -> Task:
        raise KeyError("the reader's stand-in Sample has no metadata")

    _install_fake_eval(monkeypatch, crashy=crashes_on_the_stand_in)

    code: int = main(
        [f"{_FAKE_MODULE}:crashy", "--key", "crashy", "--task-replay"]
        + ["--engine-src", str(engine_src_copy)],
        import_by_task_replay=lambda task_ref, task_args, **_: _sealed_import(),
    )

    assert code == 0
    assert '"crashy": TaskReplayCasesSpec(' in (engine_src_copy / "prepare.py").read_text()


def test_main_reports_a_task_replay_refusal_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _install_fake_eval(monkeypatch, sums=_free_text_task)
    del module.hf_dataset  # type: ignore[attr-defined]

    def refusing_import(
        task_ref: str, task_args: Mapping[str, Any] | None, **_: Any
    ) -> TaskReplayImport:
        """Refuse the way import_by_task_replay refuses an unseeded shuffle."""

        raise ImporterError(f"{task_ref}: two Task replays produced different Cases")

    code: int = main(
        [f"{_FAKE_MODULE}:sums", "--key", "x", "--engine-src", str(engine_src_copy)],
        import_by_task_replay=refusing_import,
    )

    assert code == 1
    assert "different Cases" in capsys.readouterr().err
    assert (engine_src_copy / "prepare.py").read_text() == (_SRC_DIR / "prepare.py").read_text()


def test_a_seed_flag_with_task_replay_is_refused(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--shuffle-seed and --choice-shuffle-seed drive the Hugging Face path's own shuffles; a
    Task-replay import takes the Task's order as built, so a seed would be silently inert
    (review finding on #1191). Refuse, naming the task args that do pin an order."""

    module = _install_fake_eval(monkeypatch, sums=_free_text_task)
    del module.hf_dataset  # type: ignore[attr-defined]
    calls: list[str] = []

    def never_called(
        task_ref: str, task_args: Mapping[str, Any] | None, **_: Any
    ) -> TaskReplayImport:
        calls.append(task_ref)
        raise AssertionError("the import must not run")

    code: int = main(
        [
            f"{_FAKE_MODULE}:sums",
            "--key",
            "x",
            "--task-replay",
            "--shuffle-seed",
            "7",
            "--engine-src",
            str(engine_src_copy),
        ],
        import_by_task_replay=never_called,
    )

    assert code == 1
    assert "do not apply to a Task-replay import" in capsys.readouterr().err
    assert calls == []
    assert (engine_src_copy / "prepare.py").read_text() == (_SRC_DIR / "prepare.py").read_text()


def test_main_writes_an_uncleared_card_license_as_todo(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """D13 end to end: the card's 'unknown' never lands as the license value."""

    module = _install_fake_eval(monkeypatch, sums=_free_text_task)
    del module.hf_dataset  # type: ignore[attr-defined]
    source: CaseSource = CaseSource("hugging-face", "bigbio/med_qa", "revision " + "d" * 40)

    code: int = main(
        [f"{_FAKE_MODULE}:sums", "--key", "medqa_like", "--engine-src", str(engine_src_copy)],
        import_by_task_replay=lambda task_ref, task_args, **_: _sealed_import(source),
        dataset_info=lambda dataset, revision: types.SimpleNamespace(
            card_data={"license": "UNKNOWN"}
        ),
    )

    prepare_text: str = (engine_src_copy / "prepare.py").read_text()
    assert code == 0
    assert '        license="TODO",' in prepare_text
    assert "the card says 'unknown', not a cleared license" in prepare_text


def test_the_command_reports_a_task_replay_refusal_as_an_error_line(
    tmp_path: Path, engine_src_copy: Path
) -> None:
    """Found on the first real import: under `python -m`, the importer module runs as
    __main__, so main's `except ImporterError` named a second copy of the class and a
    refusal raised from task_replay_rows escaped as a traceback."""

    import os
    import subprocess

    # Stand-in eval whose task raises: it proves a Task-replay refusal reaches main's error
    # line through the real command; it does not exercise any real eval's fetch.
    (tmp_path / "fake_cli_eval.py").write_text(
        "from inspect_ai import Task, task\n\n"
        "@task\n"
        "def broken() -> Task:\n"
        "    raise RuntimeError('upstream URL returned 404')\n",
        encoding="utf-8",
    )
    env: dict[str, str] = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, [str(tmp_path), os.environ.get("PYTHONPATH")])),
    }

    completed: subprocess.CompletedProcess[str] = subprocess.run(  # noqa: S603 — our own argv
        [
            sys.executable,
            "-m",
            "screamingface_engine_inspect.importer",
            "fake_cli_eval:broken",
            "--key",
            "broken",
            "--task-replay",
            "--engine-src",
            str(engine_src_copy),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert completed.returncode == 1
    assert "ERROR: fake_cli_eval:broken: replay failed" in completed.stderr
    assert "Traceback" not in completed.stderr.split("ERROR:")[-1]


def test_the_two_task_replay_declarations_reach_the_import(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """Spec R18, R19: only the importing agent knows which Samples to leave out and that a
    Benchmark has no answer key; both flags reach both replays through the one seam."""

    _install_fake_eval(monkeypatch, sums=_free_text_task)
    seen: list[dict[str, Any]] = []

    def fake_import(
        task_ref: str, task_args: Mapping[str, Any] | None, **options: Any
    ) -> TaskReplayImport:
        """Record the options the CLI passed; return a sealed import."""

        seen.append(options)
        return _sealed_import()

    code: int = main(
        [
            f"{_FAKE_MODULE}:sums",
            "--key",
            "sums_gappy",
            "--task-replay",
            "--excluded-sample-id",
            "sums:14",
            "--excluded-sample-id",
            "sums:58",
            "--no-answer-key",
            "--engine-src",
            str(engine_src_copy),
        ],
        import_by_task_replay=fake_import,
    )

    assert code == 0
    assert seen == [{"excluded_sample_ids": ("sums:14", "sums:58"), "has_answer_key": False}]


def test_without_the_flags_an_import_excludes_nothing_and_keeps_its_key(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    _install_fake_eval(monkeypatch, sums=_free_text_task)
    seen: list[dict[str, Any]] = []

    def fake_import(
        task_ref: str, task_args: Mapping[str, Any] | None, **options: Any
    ) -> TaskReplayImport:
        """Record the options the CLI passed; return a sealed import."""

        seen.append(options)
        return _sealed_import()

    main(
        [f"{_FAKE_MODULE}:sums", "--key", "s", "--task-replay"]
        + ["--engine-src", str(engine_src_copy)],
        import_by_task_replay=fake_import,
    )

    assert seen == [{"excluded_sample_ids": None, "has_answer_key": True}]


def test_the_task_replay_declarations_are_refused_on_the_hugging_face_path(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Hugging Face path writes no Task-replay declaration, so the flags would be silently
    inert there; its rows take their exclusion and key opt-in by hand (the import how-to)."""

    _install_fake_eval(monkeypatch, sums=_free_text_task)

    code: int = main(
        [f"{_FAKE_MODULE}:sums", "--key", "x", "--no-answer-key"]
        + ["--engine-src", str(engine_src_copy)],
    )

    assert code == 1
    assert "only apply to a Task-replay import" in capsys.readouterr().err
    assert (engine_src_copy / "prepare.py").read_text() == (_SRC_DIR / "prepare.py").read_text()
