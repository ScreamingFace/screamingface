# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The pin-generator importer — the tool that turns an inspect task into row diffs.

INVARIANT the suite defends: the importer never invents exam facts. Everything it
writes is either read from the eval's own task (dataset args, conversion/template/
scorer references) or captured as a named observation (revision sha, row count,
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
    ImporterError,
    Observations,
    TaskFacts,
    capture_observations,
    generate_rows,
    introspect_task,
    render_fragments,
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
    """Two hf_dataset calls; only the one the Task holds is the exam."""

    module = sys.modules[_FAKE_MODULE]
    module.hf_dataset(
        path="acme/sums",
        name="main",
        split="train",
        sample_fields=module.record_to_sample,
    )
    return _free_text_task()


# ---------------------------------------------------------------------------
# introspect_task
# ---------------------------------------------------------------------------


def test_introspect_reads_the_free_text_task_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_eval(monkeypatch, sums=_free_text_task)

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:sums")

    assert facts.dataset == "acme/sums"
    assert facts.config == "main"
    assert facts.split == "test"
    assert facts.pinned_revision == "deadbeef" * 5
    assert facts.record_to_sample == f"{_FAKE_MODULE}:record_to_sample"
    assert facts.prompt_template == f"{_FAKE_MODULE}:TEMPLATE"
    assert facts.mcq is False
    assert facts.scorer == "inspect_ai.scorer:match"
    assert facts.scorer_kwargs == {"numeric": True}


def test_introspect_reads_the_mcq_task(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_eval(monkeypatch, quiz=_mcq_task)

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:quiz")

    assert facts.mcq is True
    assert facts.prompt_template is None
    assert facts.pinned_revision is None
    assert facts.config == ""
    assert facts.scorer == "inspect_ai.scorer:choice"
    assert facts.scorer_kwargs == {}
    # The DEFAULT choice template is fully baked — no review flag.
    assert facts.custom_solvers == ()


def test_introspect_picks_the_dataset_the_task_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fewshot eval calls hf_dataset twice; the exam is the Task's dataset."""

    _install_fake_eval(monkeypatch, sums=_fewshot_task)

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:sums")

    assert facts.split == "test"


def test_introspect_flags_a_system_message_the_bake_would_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System instructions have no bake channel — vanishing silently would change
    the imported exam (review finding on PR 965)."""

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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:instructed")

    assert any("system_message" in flag for flag in facts.custom_solvers)


def test_introspect_flags_a_custom_choice_template(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bake renders MCQ with the default SINGLE_ANSWER template; a custom one
    must surface for review, not silently change the exam (review finding on PR 965)."""

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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:custom_mcq")

    assert any("custom choice template" in flag for flag in facts.custom_solvers)
    # The default-template MCQ task stays unflagged — see the mcq test above.


def test_introspect_refuses_a_task_that_never_loads_hf(monkeypatch: pytest.MonkeyPatch) -> None:
    def local_task() -> Task:
        return Task(dataset=[Sample(input="q", target="1")], solver=generate(), scorer=match())

    _install_fake_eval(monkeypatch, local=local_task)

    with pytest.raises(ImporterError, match="hf_dataset"):
        introspect_task(f"{_FAKE_MODULE}:local")


def test_introspect_binds_through_the_vendored_hf_dataset_shim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """inspect_evals ≥0.20 routes hf_dataset through its ``(*args, **kwargs)`` retry
    shim; binding against the shim buries every real kwarg in the VAR_KEYWORD
    bucket, and the conserved-kwargs guard then refuses the ENTIRE hf family as
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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:sums")

    assert facts.dataset == "acme/sums"
    assert facts.config == "main"
    assert facts.split == "test"
    assert facts.pinned_revision == "deadbeef" * 5
    assert facts.record_to_sample == f"{_FAKE_MODULE}:record_to_sample"


def test_introspect_refuses_an_unknown_variadic_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the vendored shim is verified pass-through — identity, not shape. A
    wrapper that mutated kwargs before forwarding would make the conserved-kwargs
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
        introspect_task(f"{_FAKE_MODULE}:sums")


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
        introspect_task(f"{_FAKE_MODULE}:sums")


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
        introspect_task(f"{_FAKE_MODULE}:sums")


def test_introspect_resolves_a_prompt_template_from_a_sibling_module(
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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:shared")

    assert facts.prompt_template == f"{sibling_name}:SHARED_TEMPLATE"


def test_introspect_refuses_an_ambiguous_sibling_template(
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
        introspect_task(f"{_FAKE_MODULE}:ambiguous")


# ---------------------------------------------------------------------------
# capture_observations
# ---------------------------------------------------------------------------


def _facts(**overrides: Any) -> TaskFacts:
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
        "custom_solvers": (),
    }
    base.update(overrides)
    return TaskFacts(**base)


def _fake_info(sha: str, license_id: str | None) -> Any:
    return types.SimpleNamespace(sha=sha, card_data={"license": license_id})


def test_capture_records_head_sha_when_upstream_does_not_pin() -> None:
    obs: Observations = capture_observations(
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

    obs: Observations = capture_observations(
        _facts(pinned_revision="main"),
        dataset_info=info_of,
        count_rows=lambda facts, revision: 321,
    )

    # The pin names WHICH revision to resolve; the stored value is its sha —
    # and the license was read at that same revision, not at HEAD.
    assert seen == ["main"]
    assert obs.revision == "a" * 40


def test_capture_keeps_an_upstream_sha_pin() -> None:
    obs: Observations = capture_observations(
        _facts(pinned_revision="b" * 40),
        dataset_info=lambda dataset, revision: _fake_info(revision or "", "mit"),
        count_rows=lambda facts, revision: 321,
    )

    assert obs.revision == "b" * 40


# ---------------------------------------------------------------------------
# render_fragments
# ---------------------------------------------------------------------------


def test_rendered_fragments_are_valid_python_and_carry_the_facts() -> None:
    fragments = render_fragments(
        "sums", _facts(), Observations(revision="c" * 40, case_count=42, license="mit")
    )

    ast.parse(fragments.pins)
    ast.parse(f"SNAPSHOTS = {{\n{fragments.snapshot}}}")
    ast.parse(f"BOARDS = (\n{fragments.board})")
    assert 'SUMS_DATASET = "acme/sums"' in fragments.pins
    assert f'SUMS_DATASET_REVISION = "{"c" * 40}"' in fragments.pins
    assert "SUMS_CASE_COUNT = 42" in fragments.pins
    assert "license: mit" in fragments.pins
    assert f'record_to_sample="{_FAKE_MODULE}:record_to_sample"' in fragments.snapshot
    assert f'prompt_template="{_FAKE_MODULE}:TEMPLATE"' in fragments.snapshot
    # Free text ⇒ the check surface is legitimate and declared.
    assert "with_check_surface=True" in fragments.board
    assert 'scorer="inspect_ai.scorer:match"' in fragments.board
    assert 'scorer_kwargs={"numeric": True}' in fragments.board
    # Catalogue prose is the dev's, never invented by the tool.
    assert "TODO" in fragments.board


def test_mcq_fragments_refuse_the_check_surface() -> None:
    """OME-796: pass/fail feedback over a handful of options is an elimination attack."""

    fragments = render_fragments(
        "quiz",
        _facts(mcq=True, prompt_template=None, scorer="inspect_ai.scorer:choice", scorer_kwargs={}),
        Observations(revision="c" * 40, case_count=7, license="mit"),
    )

    assert "with_check_surface" not in fragments.board
    assert "prompt_template" not in fragments.snapshot


def test_mcq_detection_follows_the_solver_not_the_scorer_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """lab_bench grades its MCQ exams with its OWN scorer (precision_choice), so
    keying mcq on the scorer name reads them as free-text and hands an MCQ board
    the check surface — an elimination attack (OME-796). MCQ-ness is the exam's
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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:custom_graded_mcq")

    assert facts.mcq is True
    assert facts.scorer.endswith(":house_grader")


def test_mcq_detection_sees_through_a_custom_solver_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detects MCQ when a custom wrapper hides the multiple_choice solver but the
    choice scorer proves the shape (the mmlu family case, OME-796 guard): mmlu's
    mmlu_multiple_choice calls multiple_choice() INSIDE its own @solver, so the
    registry walk never meets it — reading such an exam as free-text would hand
    an MCQ board the check surface (the elimination attack)."""

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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:wrapper_graded_mcq")

    assert facts.mcq is True


def test_board_row_renders_str_scorer_kwargs_format_safe() -> None:
    """The first str scorer kwarg (lab_bench's no_answer) must emit DOUBLE-quoted
    — repr's single quotes would fail the ruff-format gate on the emitted file."""

    fragments = render_fragments(
        "quiz",
        _facts(
            mcq=True,
            prompt_template=None,
            scorer="inspect_evals.lab_bench.lab_bench:precision_choice",
            scorer_kwargs={"no_answer": "Insufficient information."},
        ),
        Observations(revision="c" * 40, case_count=7, license="mit"),
    )

    assert '"no_answer": "Insufficient information."' in fragments.board
    ast.parse(f"BOARDS = (\n{fragments.board})")


def test_custom_solver_gets_a_review_flag() -> None:
    """A solver the importer cannot classify must be pointed out, not papered over."""

    fragments = render_fragments(
        "quiz",
        _facts(custom_solvers=("inspect_evals/mmlu_multiple_choice",)),
        Observations(revision="c" * 40, case_count=7, license="mit"),
    )

    assert "TODO(review)" in fragments.snapshot
    assert "mmlu_multiple_choice" in fragments.snapshot


# ---------------------------------------------------------------------------
# generate_rows — in-place insertion at the anchors
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine_src_copy(tmp_path: Path) -> Path:
    """A working copy of the real three files — the insertion contract's ground truth."""

    for name in ("pins.py", "prepare.py", "boards.py"):
        shutil.copy(_SRC_DIR / name, tmp_path / name)
    return tmp_path


def _generate(engine_src: Path, key: str = "sums", **fact_overrides: Any) -> None:
    generate_rows(
        key,
        _facts(**fact_overrides),
        Observations(revision="c" * 40, case_count=42, license="mit"),
        engine_src=engine_src,
    )


def test_generate_rows_lands_all_three_rows_in_parseable_files(engine_src_copy: Path) -> None:
    _generate(engine_src_copy)

    pins = (engine_src_copy / "pins.py").read_text()
    prepare = (engine_src_copy / "prepare.py").read_text()
    boards = (engine_src_copy / "boards.py").read_text()
    for text, name in ((pins, "pins.py"), (prepare, "prepare.py"), (boards, "boards.py")):
        ast.parse(text, filename=name)
    assert 'SUMS_DATASET = "acme/sums"' in pins
    assert '"sums": SnapshotSpec(' in prepare
    assert 'key="sums"' in boards
    # The SnapshotSpec entry reads the pins constants; the import block must carry them.
    assert "SUMS_CASE_COUNT," in prepare


def test_generate_rows_refuses_a_key_that_already_exists(engine_src_copy: Path) -> None:
    with pytest.raises(ImporterError, match="gsm8k"):
        _generate(engine_src_copy, key="gsm8k")


def test_generated_snapshot_row_resolves_against_the_real_spec(
    engine_src_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The inserted entry must construct a real SnapshotSpec when the file executes."""

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
    generate_rows(
        "sums",
        _facts(),
        Observations(revision="c" * 40, case_count=42, license="proprietary"),
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


def test_main_wires_introspection_capture_and_insertion(
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
    assert '"sums": SnapshotSpec(' in (engine_src_copy / "prepare.py").read_text()
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
# generate_rows hardening (review round 2 on PR 966)
# ---------------------------------------------------------------------------


def test_generate_rows_refuses_a_colliding_pin_prefix(engine_src_copy: Path) -> None:
    """ "foo-bar" and "foo_bar" both derive FOO_BAR_* constants — the second import
    would silently shadow the first board's dataset/revision/count."""

    _generate(engine_src_copy, key="foo-bar")
    with pytest.raises(ImporterError, match="FOO_BAR"):
        _generate(engine_src_copy, key="foo_bar")


def test_generate_rows_writes_nothing_when_an_anchor_is_missing(engine_src_copy: Path) -> None:
    """All insertion points are validated BEFORE any write: a broken boards.py anchor
    must not leave pins/prepare half-imported (a retry would then hit 'already
    exists' with no clean way back)."""

    boards_path = engine_src_copy / "boards.py"
    intact = boards_path.read_text()
    anchor_line = next(
        line for line in intact.splitlines() if importer_module._BOARDS_ANCHOR in line
    )
    boards_path.write_text(intact.replace(anchor_line + "\n", ""))
    pins_before = (engine_src_copy / "pins.py").read_text()
    prepare_before = (engine_src_copy / "prepare.py").read_text()

    with pytest.raises(ImporterError, match="boards.py"):
        _generate(engine_src_copy)

    assert (engine_src_copy / "pins.py").read_text() == pins_before
    assert (engine_src_copy / "prepare.py").read_text() == prepare_before
    # Restoring the anchor makes the SAME import succeed — no stale half-state.
    boards_path.write_text(intact)
    _generate(engine_src_copy)
    assert '"sums": SnapshotSpec(' in (engine_src_copy / "prepare.py").read_text()


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
# boards force: mmlu_pro / winogrande / race_h)
# ---------------------------------------------------------------------------


def test_introspect_captures_a_resolvable_custom_choice_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A custom multiple_choice template that IS a module attribute is a fact the
    bake reproduces (choice_template reference), not a review flag."""

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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:custom_mcq")

    assert facts.choice_template == f"{_FAKE_MODULE}:CHOICE_TEMPLATE"
    assert facts.custom_solvers == ()


def test_captured_choice_template_lands_in_the_snapshot_row() -> None:
    fragments = render_fragments(
        "quiz",
        _facts(
            mcq=True,
            prompt_template=None,
            scorer="inspect_ai.scorer:choice",
            scorer_kwargs={},
            choice_template=f"{_FAKE_MODULE}:CHOICE_TEMPLATE",
        ),
        Observations(revision="c" * 40, case_count=7, license="mit"),
    )

    assert f'choice_template="{_FAKE_MODULE}:CHOICE_TEMPLATE"' in fragments.snapshot
    ast.parse(f"SNAPSHOTS = {{\n{fragments.snapshot}}}")


def test_introspect_refuses_a_task_local_record_to_sample(
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
        introspect_task(f"{_FAKE_MODULE}:closured")


def test_rendered_fragment_lines_fit_the_lint_gate() -> None:
    """A long task_ref must never emit a line the 100-column lint gate rejects."""

    long_ref = "inspect_evals.some_very_long_package_name.some_very_long_package_name:the_task"
    fragments = render_fragments(
        "long", _facts(task_ref=long_ref), Observations("c" * 40, 42, "cc-by-sa-4.0")
    )
    for fragment in (fragments.pins, fragments.snapshot, fragments.board):
        assert all(len(line) <= 100 for line in fragment.splitlines())


# ---------------------------------------------------------------------------
# dataset-kwarg conservation (review round 2026-09-17 on this branch: every
# fact the importer reads but does not reproduce must refuse or flag — never
# silently drop exam identity)
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


def test_introspect_refuses_a_limit_the_bake_would_ignore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An eval with limit=N examines N cases; baking the full split would publish
    a DIFFERENT exam with every guard green (review blocker, 2026-09-17)."""

    _install_fake_eval(monkeypatch, limited=_task_with_dataset_kwargs(limit=500))

    with pytest.raises(ImporterError, match="limit"):
        introspect_task(f"{_FAKE_MODULE}:limited")


def test_introspect_records_an_unseeded_choice_shuffle_as_a_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1264 replaces the former refusal: shuffle_choices is now CONSERVED —
    introspection records the fact, and main() demands a pinned seed before any
    row is emitted (the unseeded refusal moved there, next to shuffle's).

    WHY True must not become a seed: bool is an int subtype — reading
    shuffle_choices=True as seed 1 would silently pin an order upstream never
    meant (inspect itself checks bool before int for exactly this reason)."""

    _install_fake_eval(monkeypatch, shuffled=_task_with_dataset_kwargs(shuffle_choices=True))

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:shuffled")

    assert facts.upstream_shuffle_choices is True
    assert facts.upstream_choice_shuffle_seed is None


def test_introspect_records_a_seeded_choice_shuffle_as_a_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An int shuffle_choices is inspect's seeded form — the seed is a fact."""

    _install_fake_eval(monkeypatch, seeded=_task_with_dataset_kwargs(shuffle_choices=9))

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:seeded")

    assert facts.upstream_shuffle_choices is True
    assert facts.upstream_choice_shuffle_seed == 9


def test_introspect_refuses_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """data_dir is a different load_dataset parameter than config — aliasing them
    loads the wrong data whenever they differ (gsm8k's 'main' was a coincidence)."""

    _install_fake_eval(monkeypatch, dirred=_task_with_dataset_kwargs(data_dir="data"))

    with pytest.raises(ImporterError, match="data_dir"):
        introspect_task(f"{_FAKE_MODULE}:dirred")


def test_introspect_records_an_upstream_shuffle_as_a_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_eval(monkeypatch, mixed=_task_with_dataset_kwargs(shuffle=True, seed=42))

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:mixed")

    assert facts.upstream_shuffle is True
    assert facts.upstream_shuffle_seed == 42


def test_introspect_ignores_benign_dataset_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto_id / trust / cached change how loading happens, never what the exam is."""

    _install_fake_eval(
        monkeypatch, benign=_task_with_dataset_kwargs(auto_id=True, trust=True, cached=False)
    )

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:benign")

    assert facts.dataset == "acme/sums"
    assert facts.upstream_shuffle is False


def test_introspect_binds_positional_hf_dataset_arguments(
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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:positional")

    assert facts.dataset == "acme/sums"
    assert facts.split == "test"


def test_single_call_fallback_requires_the_task_to_hold_the_recorded_exam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An eval whose exam is a local dataset but whose fewshots load from HF must
    refuse — the fewshot split is NOT the exam (review should-fix 3)."""

    def json_exam() -> Task:
        module = sys.modules[_FAKE_MODULE]
        module.hf_dataset(path="acme/sums", split="train", sample_fields=module.record_to_sample)
        return Task(
            dataset=[Sample(input="local exam", target="1")],
            solver=generate(),
            scorer=match(),
        )

    _install_fake_eval(monkeypatch, json_exam=json_exam)

    with pytest.raises(ImporterError, match="dataset"):
        introspect_task(f"{_FAKE_MODULE}:json_exam")


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
    refuse — conserved, never dropped (OME-1264)."""

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
    """Review blocker on PR #1031: the bake's row shuffle is Python's, upstream's
    is HF's — same seed, different order — and the choice shuffle draws each
    case's permutation from ONE stream in row order. So when upstream SEEDS a
    shuffle (it defined one exam) and both shuffles combine, the bake cannot
    reproduce that exam and must refuse, never ship a different one silently."""

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
    there is no fixed upstream exam to miss — both policy seeds pin one, and
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
    """--choice-shuffle-seed pins one choice order as exam identity: the pin row
    and the SnapshotSpec field both land in the generated files."""

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
    """A seeded upstream (shuffle_choices=N) defines ONE exam — overriding it with
    a policy seed would silently bake an exam upstream never produces (review
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
    """Shuffling choices the eval does NOT shuffle would bake a different exam —
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


def test_introspect_records_data_files_and_a_features_pointer_as_facts(
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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:filed")

    assert facts.data_files == {"test": "test.jsonl"}
    assert facts.features == f"{_FAKE_MODULE}:FEATURES"


def test_introspect_refuses_a_features_value_with_no_module_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inline Features(...) has no attribute the row could point at — refuse
    by name rather than serialize a schema the diff reviewer cannot anchor."""

    _install_fake_eval(monkeypatch, inlined=_task_with_dataset_kwargs(features=object()))

    with pytest.raises(ImporterError, match="features"):
        introspect_task(f"{_FAKE_MODULE}:inlined")


def test_introspect_refuses_an_exotic_data_files_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the shape the bake reproduces (dict[str, str]) is conserved;
    anything else — even a bare str — refuses by name, never dropped."""

    _install_fake_eval(monkeypatch, exotic=_task_with_dataset_kwargs(data_files=123))

    with pytest.raises(ImporterError, match="data_files"):
        introspect_task(f"{_FAKE_MODULE}:exotic")


def test_data_files_and_features_are_reproduced_in_the_rows(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path
) -> None:
    """The emitted rows carry the data_files pin and the features pointer, so
    the bake loads exactly the files and schema the eval declares."""

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
        generate_rows(
            "sums",
            _facts(),
            Observations(revision="c" * 40, case_count=42, license=hostile),
            engine_src=engine_src_copy,
        )


def test_generate_refuses_a_hostile_dataset_name(engine_src_copy: Path) -> None:
    with pytest.raises(ImporterError, match="dataset"):
        generate_rows(
            "sums",
            _facts(dataset='acme/sums"\nimport os\nY = "'),
            Observations(revision="c" * 40, case_count=42, license="mit"),
            engine_src=engine_src_copy,
        )


def test_generate_refuses_a_hostile_data_files_entry(engine_src_copy: Path) -> None:
    """data_files strings land in a generated dict literal — same injection
    sink, same charset guard (OME-1264 extension 2)."""

    hostile_facts = _facts(data_files={"test": 'x"\nimport os\nZ = "'})
    hostile_observations = Observations(revision="d" * 40, case_count=7, license="apache-2.0")
    with pytest.raises(ImporterError, match="data_files"):
        generate_rows("quiz", hostile_facts, hostile_observations, engine_src=engine_src_copy)


def test_generate_refuses_a_revision_that_is_not_a_commit_sha(engine_src_copy: Path) -> None:
    """The capture stage must never record 'None' or a short ref as exam identity."""

    with pytest.raises(ImporterError, match="revision"):
        generate_rows(
            "sums",
            _facts(),
            Observations(revision="None", case_count=42, license="mit"),
            engine_src=engine_src_copy,
        )


# ---------------------------------------------------------------------------
# round-trip: emitted rows must CONSTRUCT the real dataclasses (OME-1214). The
# ast.parse checks above catch template syntax bugs; only construction against
# the real spec catches a renamed or newly-required field.
# ---------------------------------------------------------------------------


def test_emitted_snapshot_row_constructs_the_real_snapshot_spec(engine_src_copy: Path) -> None:
    """An emitted prepare.py row must construct the real SnapshotSpec, so a spec
    change breaks here — in the spec-changer's own PR — not as a TypeError inside
    a generated file at the next import session.

    INVARIANT: the dataclasses ARE the schema — the emitted kwargs are checked by
    constructing the real spec, never against a parallel copy that could drift.
    """

    from screamingface_engine_inspect.prepare import SnapshotSpec

    # The maximal row: every optional kwarg the template can emit is emitted.
    fragments = generate_rows(
        "sums",
        _facts(choice_template=f"{_FAKE_MODULE}:CHOICE_TEMPLATE"),
        Observations(revision="c" * 40, case_count=42, license="mit"),
        engine_src=engine_src_copy,
        shuffle_seed=7,
    )

    # The row reads pin constants — take them from the written copy, exactly as
    # prepare.py resolves them at import time.
    namespace: dict[str, Any] = {"SnapshotSpec": SnapshotSpec}
    exec(compile((engine_src_copy / "pins.py").read_text(), "pins.py", "exec"), namespace)
    exec(f"SNAPSHOTS = {{\n{fragments.snapshot}}}", namespace)

    snapshot: Any = namespace["SNAPSHOTS"]["sums"]
    assert isinstance(snapshot, SnapshotSpec)
    assert snapshot.dataset == "acme/sums"
    assert snapshot.config == "main"
    assert snapshot.split == "test"
    assert snapshot.dataset_revision == "c" * 40
    assert snapshot.case_count == 42
    assert snapshot.record_to_sample == f"{_FAKE_MODULE}:record_to_sample"
    assert snapshot.prompt_template == f"{_FAKE_MODULE}:TEMPLATE"
    assert snapshot.choice_template == f"{_FAKE_MODULE}:CHOICE_TEMPLATE"
    assert snapshot.shuffle_seed == 7

    # The exec above resolves pin constants from ALL of pins.py, but the written
    # prepare.py resolves them through its import block — a constant the fragment
    # references that import_names forgot would NameError only at the next import
    # session (importer.py keeps the two lists independently; review finding on
    # this PR). Pin both directions, through the maximal row — the only one that
    # exercises the conditional shuffle_seed arm of both lists.
    referenced: set[str] = set(re.findall(r"\bSUMS_[A-Z_]+\b", fragments.snapshot))
    assert referenced == set(fragments.import_names)
    # Slice the pins import block by its own header — the first ")" in the file
    # sits inside the module docstring, far above the import.
    prepare_text: str = (engine_src_copy / "prepare.py").read_text()
    start: int = prepare_text.index(importer_module._PINS_IMPORT_HEADER)
    import_block: str = prepare_text[start : prepare_text.index(")", start)]
    assert all(name in import_block for name in fragments.import_names)


def test_emitted_board_row_constructs_the_real_board_spec(engine_src_copy: Path) -> None:
    """An emitted boards.py row must construct the real BoardSpec, so a spec
    change breaks here — in the spec-changer's own PR — not at the next import.

    INVARIANT: same as the snapshot round-trip — construction against the real
    dataclass is the schema check; no parallel copy.
    """

    from screamingface_engine_inspect.boards import BoardSpec

    fragments = generate_rows(
        "sums",
        _facts(),
        Observations(revision="c" * 40, case_count=42, license="mit"),
        engine_src=engine_src_copy,
    )

    namespace: dict[str, Any] = {"BoardSpec": BoardSpec}
    exec(f"BOARDS = (\n{fragments.board})", namespace)

    (board,) = namespace["BOARDS"]
    assert isinstance(board, BoardSpec)
    assert board.key == "sums"
    assert board.dataset_url == "https://huggingface.co/datasets/acme/sums"
    assert board.scorer == "inspect_ai.scorer:match"
    assert dict(board.scorer_kwargs) == {"numeric": True}
    # Free text ⇒ the check surface is legitimate and declared (OME-796).
    assert board.with_check_surface is True
    # Catalogue prose stays the importing agent's job — the tool emits TODOs.
    assert board.title == "TODO"


def test_emitted_minimal_snapshot_row_constructs_the_real_snapshot_spec(
    engine_src_copy: Path,
) -> None:
    """The template's OTHER branch: a row with no prompt_template, no
    choice_template and no shuffle_seed must also construct the real spec.

    WHY a separate minimal variant: making an optional SnapshotSpec field
    required (dropping its default) keeps the maximal-row test green — only a
    row that OMITS the kwarg catches it (review finding on this PR).
    """

    from screamingface_engine_inspect.prepare import SnapshotSpec

    fragments = generate_rows(
        "quiz",
        _facts(mcq=True, prompt_template=None, scorer="inspect_ai.scorer:choice", scorer_kwargs={}),
        Observations(revision="c" * 40, case_count=7, license="mit"),
        engine_src=engine_src_copy,
    )

    namespace: dict[str, Any] = {"SnapshotSpec": SnapshotSpec}
    exec(compile((engine_src_copy / "pins.py").read_text(), "pins.py", "exec"), namespace)
    exec(f"SNAPSHOTS = {{\n{fragments.snapshot}}}", namespace)

    snapshot: Any = namespace["SNAPSHOTS"]["quiz"]
    assert isinstance(snapshot, SnapshotSpec)
    assert snapshot.dataset == "acme/sums"
    assert snapshot.case_count == 7
    # The omitted kwargs resolve through the spec's own defaults.
    assert snapshot.prompt_template is None
    assert snapshot.choice_template is None
    assert snapshot.shuffle_seed is None
    assert snapshot.choice_shuffle_seed is None


def test_emitted_choice_shuffled_snapshot_row_constructs_the_real_snapshot_spec(
    engine_src_copy: Path,
) -> None:
    """The choice_shuffle_seed arm of the template: its pin must be emitted, be in
    import_names, and construct the real SnapshotSpec (OME-1264)."""

    from screamingface_engine_inspect.prepare import SnapshotSpec

    fragments = generate_rows(
        "quiz",
        _facts(mcq=True, prompt_template=None, scorer="inspect_ai.scorer:choice", scorer_kwargs={}),
        Observations(revision="c" * 40, case_count=7, license="mit"),
        engine_src=engine_src_copy,
        choice_shuffle_seed=7,
    )

    namespace: dict[str, Any] = {"SnapshotSpec": SnapshotSpec}
    exec(compile((engine_src_copy / "pins.py").read_text(), "pins.py", "exec"), namespace)
    exec(f"SNAPSHOTS = {{\n{fragments.snapshot}}}", namespace)

    snapshot: Any = namespace["SNAPSHOTS"]["quiz"]
    assert isinstance(snapshot, SnapshotSpec)
    assert snapshot.choice_shuffle_seed == 7
    assert snapshot.shuffle_seed is None
    # Both directions of the pin-name contract (same check as the maximal row).
    referenced: set[str] = set(re.findall(r"\bQUIZ_[A-Z_]+\b", fragments.snapshot))
    assert referenced == set(fragments.import_names)


def test_emitted_data_files_snapshot_row_constructs_the_real_snapshot_spec(
    engine_src_copy: Path,
) -> None:
    """The data_files/features arm of the template: the pin plus the pointer
    must construct the real SnapshotSpec (OME-1264 extension 2)."""

    from screamingface_engine_inspect.prepare import SnapshotSpec

    fragments = generate_rows(
        "filed",
        _facts(data_files={"test": "test.jsonl"}, features=f"{_FAKE_MODULE}:FEATURES"),
        Observations(revision="c" * 40, case_count=42, license="mit"),
        engine_src=engine_src_copy,
    )

    namespace: dict[str, Any] = {"SnapshotSpec": SnapshotSpec}
    exec(compile((engine_src_copy / "pins.py").read_text(), "pins.py", "exec"), namespace)
    exec(f"SNAPSHOTS = {{\n{fragments.snapshot}}}", namespace)

    snapshot: Any = namespace["SNAPSHOTS"]["filed"]
    assert isinstance(snapshot, SnapshotSpec)
    assert snapshot.data_files == {"test": "test.jsonl"}
    assert snapshot.features == f"{_FAKE_MODULE}:FEATURES"
    referenced: set[str] = set(re.findall(r"\bFILED_[A-Z_]+\b", fragments.snapshot))
    assert referenced == set(fragments.import_names)


def test_emitted_mcq_board_row_constructs_the_real_board_spec(engine_src_copy: Path) -> None:
    """The board template's OTHER branch: an MCQ row omits scorer_kwargs AND
    with_check_surface — it must still construct the real BoardSpec.

    WHY a separate MCQ variant: dropping the default of either omitted field
    keeps the free-text-row test green — only this row catches it (review
    finding on this PR).
    """

    from screamingface_engine_inspect.boards import BoardSpec

    fragments = generate_rows(
        "quiz",
        _facts(mcq=True, prompt_template=None, scorer="inspect_ai.scorer:choice", scorer_kwargs={}),
        Observations(revision="c" * 40, case_count=7, license="mit"),
        engine_src=engine_src_copy,
    )

    namespace: dict[str, Any] = {"BoardSpec": BoardSpec}
    exec(f"BOARDS = (\n{fragments.board})", namespace)

    (board,) = namespace["BOARDS"]
    assert isinstance(board, BoardSpec)
    assert board.key == "quiz"
    assert board.scorer == "inspect_ai.scorer:choice"
    # The omitted kwargs resolve through the spec's own defaults (OME-796: MCQ
    # boards never declare the check surface).
    assert dict(board.scorer_kwargs) == {}
    assert board.with_check_surface is False


def test_injection_charsets_refuse_a_trailing_newline(engine_src_copy: Path) -> None:
    """`$` tolerates one trailing newline; the guards anchor with \\Z so a
    newline can never open a second line in generated code."""

    with pytest.raises(ImporterError, match="license"):
        generate_rows(
            "sums",
            _facts(),
            Observations(revision="c" * 40, case_count=42, license="mit\n"),
            engine_src=engine_src_copy,
        )


def test_introspect_binds_a_module_level_system_message_as_a_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1253 (owner-approved): an eval's system instruction kept in a module
    constant is delivered as LEADING INPUT TEXT at bake time (a benchmark cannot
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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:storyteller")

    assert facts.system_message == f"{_FAKE_MODULE}:INSTRUCTIONS"
    assert facts.custom_solvers == ()


def _introspect_module_system_message(
    monkeypatch: pytest.MonkeyPatch, instructions: str, **params: Any
) -> TaskFacts:
    """Introspect an eval whose system_message points at module.INSTRUCTIONS."""

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
    return introspect_task(f"{_FAKE_MODULE}:storyteller")


def test_introspect_flags_a_system_message_that_fills_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1272: system_message(template, **params) sends the template AFTER
    str.format fills the params in. Binding the bare constant would bake text
    the eval never sends — so the row gets no fact and the flag names the param."""

    facts: TaskFacts = _introspect_module_system_message(
        monkeypatch, "Answer as {persona}.", persona="a patient tutor"
    )

    assert facts.system_message is None
    assert any("system_message" in flag and "persona" in flag for flag in facts.custom_solvers)


@pytest.mark.parametrize(
    "instructions",
    [
        # Filled at run time from sample metadata or the store, even with no params.
        "Answer as {persona}.",
        # str.format rewrites an escaped brace: the eval sends "{json}", not "{{json}}".
        "Reply in {{json}}.",
    ],
)
def test_introspect_flags_a_system_message_whose_text_str_format_rewrites(
    monkeypatch: pytest.MonkeyPatch, instructions: str
) -> None:
    """OME-1272: inspect runs every system message through str.format with the
    sample's metadata and store. Any brace in the text means the sent message can
    differ from the constant — per case, invisibly — so it flags instead of binding."""

    facts: TaskFacts = _introspect_module_system_message(monkeypatch, instructions)

    assert facts.system_message is None
    assert any("system_message" in flag for flag in facts.custom_solvers)


def test_introspect_flags_a_system_message_read_from_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OME-1272: a template that is a path to an existing file is READ by inspect
    (resource()), so the eval sends the file's contents. Binding the constant
    would bake the path itself as the instruction."""

    prompt_file: Path = tmp_path / "system.txt"
    prompt_file.write_text("You are a careful accountant.")

    facts: TaskFacts = _introspect_module_system_message(monkeypatch, str(prompt_file))

    assert facts.system_message is None
    assert any("system_message" in flag for flag in facts.custom_solvers)


def test_introspect_refuses_a_prompt_template_read_from_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OME-1272 (PR #1064 review): prompt_template() also READS a path through
    resource(), so the eval sends the file's template. The bake formats the
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
        introspect_task(f"{_FAKE_MODULE}:from_file")


def test_introspect_flags_a_chain_with_two_system_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1272 (PR #1064 review): inspect sends EVERY system message in the
    chain, but the row holds one pointer — the last used to win silently, so
    the bake dropped the first instruction. Now nothing binds and the flag
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

    facts: TaskFacts = introspect_task(f"{_FAKE_MODULE}:twice_instructed")

    assert facts.system_message is None
    assert any("2 system messages" in flag for flag in facts.custom_solvers)


def _introspect_setup_system_message(
    monkeypatch: pytest.MonkeyPatch, instructions: str
) -> TaskFacts:
    """Introspect an eval whose system message lives in Task(setup=...)."""

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
    return introspect_task(f"{_FAKE_MODULE}:set_up")


def test_introspect_sees_a_system_message_in_task_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1272 (PR #1064 review): inspect runs Task(setup=...) before the
    solver chain, so a system message there reaches the candidate exactly like
    one in the chain. The walk used to skip setup, so the instruction vanished
    with no flag; a plain constant there now binds like any other."""

    facts: TaskFacts = _introspect_setup_system_message(
        monkeypatch, "Choose the most plausible continuation for the story."
    )

    assert facts.system_message == f"{_FAKE_MODULE}:INSTRUCTIONS"
    assert facts.custom_solvers == ()


def test_introspect_flags_a_rewritten_system_message_in_task_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The setup walk runs the same guard: a placeholder there flags, never binds."""

    facts: TaskFacts = _introspect_setup_system_message(monkeypatch, "Answer as {persona}.")

    assert facts.system_message is None
    assert any("system_message" in flag for flag in facts.custom_solvers)


@pytest.mark.parametrize("where", ["chain", "setup_and_chain"])
def test_introspect_refuses_a_task_with_two_prompt_templates(
    monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """OME-1272 (PR #1064 second review): inspect applies EVERY prompt_template in
    turn, each wrapping the previous one's output, but the row points at one
    template and the bake applies only it — the last one used to win silently.
    It refuses by name, like every other prompt template the bake cannot
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
        introspect_task(f"{_FAKE_MODULE}:double_templated")


# ---------------------------------------------------------------------------
# model-graded scorers get the judge flag (OME-1240)
# ---------------------------------------------------------------------------


def test_a_model_graded_scorer_emits_the_judge_declaration_todo() -> None:
    """A judged eval must never emit a silently-failing row: the fragment carries a
    judge=JudgeSpec placeholder whose TODO model is refused at assembly by name."""

    fragments = render_fragments(
        "judged",
        _facts(
            scorer="inspect_ai.scorer:model_graded_qa",
            scorer_kwargs={"model": "openai/gpt-4o", "template": "grade {answer}"},
        ),
        Observations(revision="c" * 40, case_count=7, license="mit"),
    )

    assert "TODO(review)" in fragments.board
    assert 'judge=JudgeSpec(model="TODO")' in fragments.board
    # The eval's own judge value is kept visible for the reviewer to replace.
    assert "openai/gpt-4o" in fragments.board
    ast.parse(f"BOARDS = (\n{fragments.board})")


def test_a_string_match_scorer_emits_no_judge_lines() -> None:
    fragments = render_fragments(
        "sums", _facts(), Observations(revision="c" * 40, case_count=42, license="mit")
    )
    assert "JudgeSpec" not in fragments.board


def test_a_custom_scorer_with_a_judge_model_kwarg_gets_the_judge_flag() -> None:
    """Detection keys on the KWARG, not the scorer name — frontierscience's custom
    scorer carries its judge under `model` and matched no model_graded_* name, so
    the importer emitted a silently-unjudged row (review finding, 2026-09-24)."""

    fragments = render_fragments(
        "judged",
        _facts(
            scorer=f"{_FAKE_MODULE}:custom_scorer",
            scorer_kwargs={"model": None},
        ),
        Observations(revision="c" * 40, case_count=7, license="mit"),
    )
    assert 'judge=JudgeSpec(model="TODO")' in fragments.board
    assert "TODO(review)" in fragments.board


def test_a_judged_row_never_advertises_a_check_surface() -> None:
    """Assembly refuses judged rows with a check surface (no check-cost knob yet) —
    the importer emitting both would strand the next import on a red gate it was
    told is already correct (review finding, 2026-09-24)."""

    fragments = render_fragments(
        "judged",
        _facts(
            scorer="inspect_ai.scorer:model_graded_qa",
            scorer_kwargs={"model": "openai/gpt-4o"},
        ),
        Observations(revision="c" * 40, case_count=7, license="mit"),
    )
    assert "with_check_surface" not in fragments.board
    assert "keep_sample_metadata" in fragments.board  # the reviewer reminder rides the flag
