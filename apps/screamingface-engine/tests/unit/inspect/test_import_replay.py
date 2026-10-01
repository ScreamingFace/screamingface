# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The import-mode Task replay: a clean child calls the task function, records the Case
Sources, reads the solver and scorer facts, and renders the Cases (spec R2, R3).

INVARIANT: the import child and the image-side child render a Case with the same writer, so
the Case Digest the importer records is the one Case Preparation will compute.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.case_sources import CaseSource  # noqa: E402
from screamingface_engine_inspect.import_replay import (  # noqa: E402
    ImportReplay,
    replay_for_import,
)
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec, case_digest  # noqa: E402
from screamingface_engine_inspect.task_replay import TaskReplayError, replayed_cases  # noqa: E402

#: A stand-in eval whose tasks fetch through a recorded primitive: json_dataset reads its file
#: through inspect_ai._util.file.file, which the recorder sees as a `file` Case Source. It
#: proves the import child's wiring; it does not prove any real eval's fetch is seen.
FAKE_EVAL: str = textwrap.dedent(
    """
    import os
    from inspect_ai import Task, task
    from inspect_ai.dataset import FieldSpec, MemoryDataset, Sample, json_dataset
    from inspect_ai.scorer import Score, Target, accuracy, choice, match, scorer
    from inspect_ai.solver import (
        Generate, TaskState, generate, multiple_choice, prompt_template, solver,
    )

    TEMPLATE = "Answer with the number only.\\n\\n{prompt}\\n"
    DATA = os.environ["FAKE_IMPORT_EVAL_DATA"]
    QUIZ = os.environ["FAKE_IMPORT_EVAL_QUIZ"]

    @task
    def arithmetic(extra: bool = False) -> Task:
        # the stand-in's one Case Source: a JSONL file read through inspect_ai's file()
        dataset = json_dataset(DATA, FieldSpec(input="q", target="a", id="id"))
        if extra:
            dataset = MemoryDataset(list(dataset) + [Sample(id=3, input="1 plus 1?", target="2")])
        return Task(dataset=dataset, solver=[prompt_template(TEMPLATE), generate()],
                    scorer=match(numeric=True))

    @task
    def quiz() -> Task:
        return Task(dataset=json_dataset(QUIZ, FieldSpec(input="q", target="a", id="id",
                                                        choices="choices")),
                    solver=multiple_choice(), scorer=choice())

    @solver
    def house_multiple_choice():
        # mmlu's shape: multiple_choice hidden inside the eval's own solver
        inner = multiple_choice()

        async def solve(state: TaskState, generate: Generate) -> TaskState:
            return await inner(state, generate)

        return solve

    @task
    def wrapped_quiz() -> Task:
        return Task(dataset=json_dataset(QUIZ, FieldSpec(input="q", target="a", id="id",
                                                        choices="choices")),
                    solver=house_multiple_choice(), scorer=choice())

    @scorer(metrics=[accuracy()])
    def topic_scorer():
        # an eval's own scorer that reads the Sample metadata, as chembench's does
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1 if state.metadata["topic"] else 0)

        return score

    @task
    def own_scorer() -> Task:
        return Task(dataset=json_dataset(DATA, FieldSpec(input="q", target="a", id="id",
                                                        metadata=["topic"])),
                    scorer=topic_scorer())

    @task
    def from_memory() -> Task:
        # yields Samples with no fetch at all: spec R4 refuses it
        return Task(dataset=MemoryDataset([Sample(id=1, input="x", target="y")]), scorer=match())

    @task
    def empty() -> Task:
        # a task whose dataset holds no Samples (json_dataset refuses an empty file itself)
        return Task(dataset=MemoryDataset([]), scorer=match())

    @task
    def no_ids() -> Task:
        # Samples with no id: inspect numbers them itself at eval time
        # WHY a converter: FieldSpec reads an `id` column by default
        return Task(dataset=json_dataset(DATA, lambda row: Sample(input=row["q"], target=row["a"])),
                    scorer=match())

    @task
    def shuffled() -> Task:
        # an unseeded shuffle over four rows: the two runs disagree 23 times in 24
        dataset = json_dataset(os.environ["FAKE_IMPORT_EVAL_DATA4"],
                               FieldSpec(input="q", target="a", id="id"))
        dataset.shuffle()
        return Task(dataset=dataset, scorer=match())

    @task
    def broken() -> Task:
        raise RuntimeError("upstream URL returned 404")
    """
)

_ROWS: list[dict[str, object]] = [
    {"id": 1, "q": "What is 6 times 7?", "a": "42", "topic": "times"},
    {"id": 2, "q": "What is 2 plus 2?", "a": "4", "topic": "plus"},
]
#: The MCQ stand-in's rows. WHY a separate file: inspect's FieldSpec reads a `choices`
#: column by default, which would turn the free-text tasks into MCQ ones.
_QUIZ_ROWS: list[dict[str, object]] = [
    {"id": 1, "q": "What is 6 times 7?", "a": "B", "choices": ["41", "42"]},
    {"id": 2, "q": "What is 2 plus 2?", "a": "A", "choices": ["4", "5"]},
]


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    """Write the stand-in eval's JSONL data file."""

    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


@pytest.fixture
def fake_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval and its data where the child process can import them."""

    (tmp_path / "fake_import_eval.py").write_text(FAKE_EVAL, encoding="utf-8")
    _write_rows(tmp_path / "cases.jsonl", _ROWS)
    monkeypatch.setenv("FAKE_IMPORT_EVAL_DATA", str(tmp_path / "cases.jsonl"))
    _write_rows(tmp_path / "quiz.jsonl", _QUIZ_ROWS)
    monkeypatch.setenv("FAKE_IMPORT_EVAL_QUIZ", str(tmp_path / "quiz.jsonl"))
    _write_rows(
        tmp_path / "cases4.jsonl",
        [
            *_ROWS,
            {"id": 3, "q": "What is 1 plus 1?", "a": "2"},
            {"id": 4, "q": "What is 3 times 3?", "a": "9"},
        ],
    )
    monkeypatch.setenv("FAKE_IMPORT_EVAL_DATA4", str(tmp_path / "cases4.jsonl"))
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_import_eval"


def test_the_child_returns_cases_case_sources_and_facts(fake_eval: str, tmp_path: Path) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:arithmetic", None)

    assert [item["case"]["input"] for item in replay.prepared] == [
        "Answer with the number only.\n\nWhat is 6 times 7?\n",
        "Answer with the number only.\n\nWhat is 2 plus 2?\n",
    ]
    assert replay.case_sources == (
        CaseSource("file", str((tmp_path / "cases.jsonl").resolve()), "unpinned"),
    )
    assert replay.sample_ids == ("1", "2")
    assert replay.facts.prompt_template == f"{fake_eval}:TEMPLATE"
    assert replay.facts.scorer == "inspect_ai.scorer:match"
    assert replay.facts.scorer_kwargs == {"numeric": True}
    assert replay.facts.mcq is False
    assert replay.facts.keep_sample_metadata is False


def test_an_mcq_task_reports_its_choice_scorer_and_mcq(fake_eval: str) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:quiz", None)

    assert replay.facts.mcq is True
    assert replay.facts.scorer == "inspect_ai.scorer:choice"
    assert replay.prepared[0]["grading_material"]["choices"] == ["41", "42"]


def test_a_wrapped_mcq_solver_is_still_mcq_by_its_choice_scorer(fake_eval: str) -> None:
    """Review Focus 7: mmlu hides multiple_choice in its own solver; the choice scorer still
    testifies, so the row never offers mid-run feedback on an MCQ Benchmark (OME-796)."""

    replay: ImportReplay = replay_for_import(f"{fake_eval}:wrapped_quiz", None)

    assert replay.facts.mcq is True


def test_an_evals_own_scorer_keeps_the_sample_metadata(fake_eval: str) -> None:
    """D11: an eval's own scorer may read state.metadata, and metadata sits inside the Case
    Digest, so the import decides it, not a later hand edit."""

    replay: ImportReplay = replay_for_import(f"{fake_eval}:own_scorer", None)

    assert replay.facts.scorer == f"{fake_eval}:topic_scorer"
    assert replay.facts.keep_sample_metadata is True
    assert [item["grading_material"]["metadata"] for item in replay.prepared] == [
        {"topic": "times"},
        {"topic": "plus"},
    ]


def test_task_args_reach_the_task_function(fake_eval: str) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:arithmetic", {"extra": True})

    assert len(replay.prepared) == 3
    assert replay.facts.task_args == {"extra": True}


def test_the_import_child_and_the_image_child_render_the_same_cases(fake_eval: str) -> None:
    """INVARIANT: one writer. The declaration the importer records reproduces at build."""

    replay: ImportReplay = replay_for_import(f"{fake_eval}:arithmetic", None)
    declaration: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_eval}:arithmetic",
        case_count=2,
        case_digest=case_digest(replay.prepared),
        prompt_template=replay.facts.prompt_template,
    )

    assert case_digest(replayed_cases(declaration)) == declaration.case_digest


def test_a_task_that_raises_is_a_named_replay_failure(fake_eval: str) -> None:
    with pytest.raises(TaskReplayError, match="upstream URL returned 404"):
        replay_for_import(f"{fake_eval}:broken", None)


def test_a_task_with_no_fetch_records_no_case_source(fake_eval: str) -> None:
    """The refusal itself lives in import_by_task_replay; the child just reports none."""

    replay: ImportReplay = replay_for_import(f"{fake_eval}:from_memory", None)

    assert replay.case_sources == ()


def test_a_sample_with_no_id_reports_none_not_the_text_none(fake_eval: str) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:no_ids", None)

    assert replay.sample_ids == (None, None)


# ── the double run and the import refusals (spec R4) ────────────────────────────

from screamingface_engine_inspect.import_replay import (  # noqa: E402
    TaskReplayImport,
    import_by_task_replay,
)
from screamingface_engine_inspect.importer import ImporterError  # noqa: E402


def test_an_import_seals_the_cases_with_a_digest_both_runs_agree_on(fake_eval: str) -> None:
    imported: TaskReplayImport = import_by_task_replay(f"{fake_eval}:arithmetic", None)

    assert imported.declaration.case_count == 2
    assert len(imported.declaration.case_digest) == 64
    assert imported.declaration.prompt_template == f"{fake_eval}:TEMPLATE"
    assert imported.declaration.task_args is None
    assert case_digest(replayed_cases(imported.declaration)) == imported.declaration.case_digest


def test_the_sealed_declaration_keeps_the_metadata_its_digest_covers(fake_eval: str) -> None:
    """D11: run 2 renders with the same keep_sample_metadata run 1 sealed under."""

    imported: TaskReplayImport = import_by_task_replay(f"{fake_eval}:own_scorer", None)

    assert imported.declaration.keep_sample_metadata is True


def test_the_second_run_takes_the_image_side_path(
    fake_eval: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review Focus 4: run 2 is what the image build will do, so the written declaration is
    proven to reproduce, not just the import child."""

    from screamingface_engine_inspect import import_replay

    calls: list[TaskReplayCasesSpec] = []
    original = import_replay.replayed_cases

    def spy(spec: TaskReplayCasesSpec, **kwargs: float) -> list[dict[str, object]]:
        """Record the declaration the image-side replay received."""

        calls.append(spec)
        return original(spec, **kwargs)  # type: ignore[return-value]

    monkeypatch.setattr(import_replay, "replayed_cases", spy)

    imported: TaskReplayImport = import_by_task_replay(f"{fake_eval}:arithmetic", None)

    assert calls == [imported.declaration]


def test_a_task_that_raises_is_refused_by_name(fake_eval: str) -> None:
    with pytest.raises(ImporterError, match="upstream URL returned 404"):
        import_by_task_replay(f"{fake_eval}:broken", None)


def test_samples_with_no_case_source_are_refused(fake_eval: str) -> None:
    """A fetch nobody can see is a fetch nobody can review."""

    with pytest.raises(ImporterError, match="no Case Source was recorded"):
        import_by_task_replay(f"{fake_eval}:from_memory", None)


def test_no_samples_is_refused(fake_eval: str) -> None:
    """Spec R4. inspect's Task refuses an empty dataset before ours can (inspect 0.3.263), and
    its reason reaches the importer's error intact; import_by_task_replay's own "yielded no
    Samples" check is the backstop for an inspect that stops refusing."""

    with pytest.raises(ImporterError, match="dataset is empty|yielded no Samples"):
        import_by_task_replay(f"{fake_eval}:empty", None)


def test_two_samples_sharing_an_id_are_refused(fake_eval: str, tmp_path: Path) -> None:
    _write_rows(tmp_path / "cases.jsonl", [dict(_ROWS[0]), {**_ROWS[1], "id": 1}])

    with pytest.raises(ImporterError, match="share the id 1"):
        import_by_task_replay(f"{fake_eval}:arithmetic", None)


def test_samples_with_no_id_are_not_duplicates(fake_eval: str) -> None:
    """inspect numbers id-less Samples itself at eval time, so they cannot collide."""

    imported: TaskReplayImport = import_by_task_replay(f"{fake_eval}:no_ids", None)

    assert imported.declaration.case_count == 2


def test_two_runs_that_disagree_are_refused(fake_eval: str) -> None:
    """An unseeded shuffle passes once and would go SKIPPED at every build (spec R4).

    WHY three attempts: the stand-in shuffles four rows, so the two runs agree by chance
    1 time in 24 per attempt; three attempts leave 1 in 13,824.
    """

    refusal: ImporterError | None = None
    for _ in range(3):
        try:
            import_by_task_replay(f"{fake_eval}:shuffled", None)
        except ImporterError as exc:
            refusal = exc
            break

    assert refusal is not None
    assert "different Cases" in str(refusal)


# ── a verified choice-template constant for a template built at run time (PR 4) ──

#: A stand-in eval that builds its choice template inside the task function, as agieval does
#: (`MULTIPLE_CHOICE_TEMPLATE_EN.format(fewshot_string="", ...)`), so no module attribute
#: holds it. It proves the override wiring; it does not prove agieval's own template.
COMPUTED_TEMPLATE_EVAL: str = textwrap.dedent(
    """
    import os
    from inspect_ai import Task, task
    from inspect_ai.dataset import FieldSpec, json_dataset
    from inspect_ai.scorer import choice
    from inspect_ai.solver import multiple_choice

    PARTS = "{fewshot}Pick one of {letters}.\\n\\n{question}\\n\\n{choices}"

    @task
    def computed_quiz() -> Task:
        template = PARTS.format(fewshot="", letters="{letters}", question="{question}",
                                choices="{choices}")
        return Task(dataset=json_dataset(os.environ["FAKE_IMPORT_EVAL_QUIZ"],
                                         FieldSpec(input="q", target="a", id="id",
                                                   choices="choices")),
                    solver=multiple_choice(template=template), scorer=choice())
    """
)

#: Our side's constants: the faithful copy, and one that drifted by a word.
TEMPLATE_CONSTANTS: str = textwrap.dedent(
    """
    RENDERED = "Pick one of {letters}.\\n\\n{question}\\n\\n{choices}"
    DRIFTED = "Choose one of {letters}.\\n\\n{question}\\n\\n{choices}"
    """
)


@pytest.fixture
def computed_template_eval(fake_eval: str, tmp_path: Path) -> str:
    """Add the computed-template stand-in and our constants beside the first stand-in."""

    (tmp_path / "fake_computed_eval.py").write_text(COMPUTED_TEMPLATE_EVAL, encoding="utf-8")
    (tmp_path / "fake_template_constants.py").write_text(TEMPLATE_CONSTANTS, encoding="utf-8")
    return "fake_computed_eval:computed_quiz"


def test_a_run_time_template_is_flagged_without_a_constant(computed_template_eval: str) -> None:
    """Without the override the Case would be rendered with inspect's default template."""

    replay: ImportReplay = replay_for_import(computed_template_eval, None)

    assert replay.facts.choice_template is None
    assert any("custom choice template" in flag for flag in replay.facts.unreproduced_solvers)


def test_a_verified_template_constant_renders_the_cases(computed_template_eval: str) -> None:
    """The constant equals what the Task holds, so the Cases carry the eval's own wording."""

    replay: ImportReplay = replay_for_import(
        computed_template_eval, None, choice_template="fake_template_constants:RENDERED"
    )

    assert replay.facts.choice_template == "fake_template_constants:RENDERED"
    assert replay.facts.unreproduced_solvers == ()
    assert replay.prepared[0]["case"]["input"].startswith("Pick one of A,B.")


def test_a_template_constant_that_differs_from_the_task_is_refused(
    computed_template_eval: str,
) -> None:
    """INVARIANT: the override can point at the eval's wording, never invent a prompt."""

    with pytest.raises(ImporterError, match="does not equal the template"):
        import_by_task_replay(
            computed_template_eval, None, choice_template="fake_template_constants:DRIFTED"
        )


# ── choices the eval's question already lists (worldsense's shape, PR 5a) ────────

#: A stand-in for worldsense: the question text lists the options and asks for a number, the
#: Sample still carries `choices`, and no multiple_choice solver renders them. It proves the
#: writer keeps the question as written; it does not prove worldsense's own scorer.
NUMBERED_OPTIONS_EVAL: str = textwrap.dedent(
    """
    from inspect_ai import Task, task
    from inspect_ai.dataset import FieldSpec, MemoryDataset, Sample, json_dataset
    from inspect_ai.scorer import match
    from inspect_ai.solver import generate
    import os

    @task
    def numbered() -> Task:
        rows = json_dataset(os.environ["FAKE_IMPORT_EVAL_DATA"],  # the one Case Source
                            FieldSpec(input="q", target="a", id="id"))
        samples = [
            Sample(id=row.id, target="1", choices=["1", "2"],
                   input=f"{row.input}\\nChoose one: (1) yes, (2) no. Answer with the number.")
            for row in rows
        ]
        return Task(dataset=MemoryDataset(samples), solver=generate(), scorer=match())
    """
)


@pytest.fixture
def numbered_eval(fake_eval: str, tmp_path: Path) -> str:
    """Add the numbered-options stand-in beside the first stand-in."""

    (tmp_path / "fake_numbered_eval.py").write_text(NUMBERED_OPTIONS_EVAL, encoding="utf-8")
    return "fake_numbered_eval:numbered"


def test_options_the_question_already_lists_are_not_rendered_again(numbered_eval: str) -> None:
    """INVARIANT: the Case asks exactly what the eval asks — no MCQ template on top, and the
    eval's own number answer stays the target (no letter is forced on it)."""

    imported: TaskReplayImport = import_by_task_replay(numbered_eval, None)
    replay: ImportReplay = replay_for_import(numbered_eval, None)

    assert imported.declaration.render_choices is False
    assert replay.prepared[0]["case"]["input"] == (
        "What is 6 times 7?\nChoose one: (1) yes, (2) no. Answer with the number."
    )
    assert replay.prepared[0]["grading_material"] == {"target": "1", "choices": ["1", "2"]}


def test_an_mcq_task_still_renders_its_options(fake_eval: str) -> None:
    """The multiple_choice solver renders the options, so the Case must too."""

    imported: TaskReplayImport = import_by_task_replay(f"{fake_eval}:quiz", None)

    assert imported.declaration.render_choices is True


def test_samples_with_choices_are_mcq_even_without_a_choice_solver(numbered_eval: str) -> None:
    """OME-796: pass/fail feedback over a handful of options is an elimination attack, so a
    Case that carries choices is MCQ-shaped whatever its solver and scorer are called
    (worldsense: generate() + pattern scorer over three numbered options)."""

    replay: ImportReplay = replay_for_import(numbered_eval, None)

    assert replay.facts.mcq is True
    assert replay.facts.render_choices is False
