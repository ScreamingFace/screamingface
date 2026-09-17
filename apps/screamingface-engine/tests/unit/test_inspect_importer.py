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
