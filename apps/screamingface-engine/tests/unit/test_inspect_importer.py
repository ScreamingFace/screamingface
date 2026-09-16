# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The pin-generator importer — the tool that turns an inspect task into row diffs.

INVARIANT the suite defends: the importer never invents exam facts. Everything it
records is either read from the eval's own task (dataset args, conversion/template/
scorer references) or captured as a named observation (revision sha, row count,
license) — the emit stage that writes them into files rides the stack's next PR.

Runs only with the `inspect` extra installed. No network: the fabricated eval
module's ``hf_dataset`` is intercepted by the importer itself, and the capture
layer is injected.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai import Task  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.scorer import choice, match  # noqa: E402
from inspect_ai.solver import generate, multiple_choice, prompt_template  # noqa: E402

from screamingface_engine_inspect.importer import (  # noqa: E402
    ImporterError,
    Observations,
    TaskFacts,
    capture_observations,
    introspect_task,
)

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
