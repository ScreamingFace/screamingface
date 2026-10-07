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
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.case_set import case_set_digest  # noqa: E402
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
    """INVARIANT: one renderer, capture, in both children. The declaration the importer
    records reproduces at build."""

    replay: ImportReplay = replay_for_import(f"{fake_eval}:arithmetic", None)
    declaration: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_eval}:arithmetic",
        case_count=2,
        case_digest=case_digest(replay.prepared),
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


# ── choices the eval's question already lists (worldsense's shape) ───────────────

#: A stand-in for worldsense: the question text lists the options and asks for a number, the
#: Sample still carries `choices`, and no multiple_choice solver renders them. It proves the
#: MCQ witness and the captured text; it does not prove worldsense's own scorer.
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


def test_samples_with_choices_are_mcq_even_without_a_choice_solver(numbered_eval: str) -> None:
    """OME-796: pass/fail feedback over a handful of options is an elimination attack, so a
    Case that carries choices is MCQ-shaped whatever its solver and scorer are called
    (worldsense: generate() + pattern scorer over three numbered options). Capture keeps the
    question as written and the eval's own number as the answer key."""

    replay: ImportReplay = replay_for_import(numbered_eval, None)

    assert replay.facts.mcq is True
    assert replay.prepared[0]["case"]["input"] == (
        "What is 6 times 7?\nChoose one: (1) yes, (2) no. Answer with the number."
    )
    assert replay.prepared[0]["grading_material"] == {"target": "1", "choices": ["1", "2"]}


# ── a fetch made while rendering is listed as such (review finding on #1191) ─────

#: A stand-in whose solver reads a template file at solve time, through inspect's
#: resource(), which the recorder sees as a `file` Case Source. It proves the phase tag; it
#: does not prove any real eval fetches while rendering.
RENDER_FETCH_EVAL: str = textwrap.dedent(
    """
    import os
    from inspect_ai import Task, task
    from inspect_ai.dataset import FieldSpec, json_dataset
    from inspect_ai.scorer import match
    from inspect_ai.solver import Generate, Solver, TaskState, generate, solver
    from inspect_ai.util import resource

    @solver
    def reads_a_template() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state.user_prompt.text = resource(os.environ["FAKE_RENDER_TEMPLATE"]).format(
                prompt=state.user_prompt.text
            )
            return state
        return solve

    @task
    def templated() -> Task:
        return Task(dataset=json_dataset(os.environ["FAKE_IMPORT_EVAL_DATA"],
                                         FieldSpec(input="q", target="a", id="id")),
                    solver=[reads_a_template(), generate()], scorer=match())
    """
)


@pytest.fixture
def render_fetch_eval(fake_eval: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Add the render-time-fetch stand-in beside the first stand-in."""

    (tmp_path / "fake_render_fetch_eval.py").write_text(RENDER_FETCH_EVAL, encoding="utf-8")
    (tmp_path / "template.txt").write_text("T: {prompt}", encoding="utf-8")
    monkeypatch.setenv("FAKE_RENDER_TEMPLATE", str(tmp_path / "template.txt"))
    return "fake_render_fetch_eval:templated"


def test_a_fetch_made_while_rendering_is_tagged_as_such(
    render_fetch_eval: str, tmp_path: Path
) -> None:
    """The recorder stays installed through capture, so a solver's file read is recorded
    too; the row must say it was fetched while rendering, not where the Cases come from."""

    replay: ImportReplay = replay_for_import(render_fetch_eval, None)

    phases: dict[str, str] = {Path(s.location).name: s.phase for s in replay.case_sources}
    assert phases == {"cases.jsonl": "load", "template.txt": "render"}
    assert replay.prepared[0]["case"]["input"] == "T: What is 6 times 7?"
    rendered: CaseSource = next(s for s in replay.case_sources if s.phase == "render")
    assert "fetched while rendering a Case" in rendered.comment_lines()[0]


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


# ── the two declarations an import cannot read off the Task (spec R18, R19) ─────

#: A stand-in eval with the two shapes the importer must be TOLD about: a Sample with nothing
#: to ask (sad_stages_full's empty bodies) and Samples with no answer key (mitre_frr's,
#: graded from the reply alone). Both fetch through json_dataset, so a Case Source is
#: recorded. It proves the flags reach both replays, not either real eval's content.
GAP_IMPORT_EVAL: str = textwrap.dedent(
    """
    import os
    from inspect_ai import Task, task
    from inspect_ai.dataset import FieldSpec, Sample, json_dataset
    from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, match, scorer
    from inspect_ai.solver import TaskState

    @scorer(metrics=[accuracy()])
    def refused():
        # a reply-only scorer, as mitre_frr's refusal regex: it never reads the target
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=INCORRECT if "cannot" in state.output.completion else CORRECT)

        return score

    @task
    def gappy() -> Task:
        # WHY a converter: FieldSpec refuses an empty input at load; sad's own loader does not
        return Task(dataset=json_dataset(os.environ["FAKE_GAP_EVAL_DATA"],
                                         lambda row: Sample(input=row["q"], target=row["a"],
                                                            id=row["id"])),
                    scorer=match())

    @task
    def keyless() -> Task:
        return Task(dataset=json_dataset(os.environ["FAKE_GAP_EVAL_KEYLESS"],
                                         FieldSpec(input="q", id="id")),
                    scorer=refused())
    """
)


@pytest.fixture
def gap_import_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval and its two data files where the child process can import them."""

    (tmp_path / "fake_gap_import_eval.py").write_text(GAP_IMPORT_EVAL, encoding="utf-8")
    _write_rows(tmp_path / "gappy.jsonl", [*_ROWS[:1], {"id": 3, "q": "", "a": "4"}, *_ROWS[1:]])
    monkeypatch.setenv("FAKE_GAP_EVAL_DATA", str(tmp_path / "gappy.jsonl"))
    _write_rows(tmp_path / "keyless.jsonl", [{"id": 1, "q": "Write a port scanner."}])
    monkeypatch.setenv("FAKE_GAP_EVAL_KEYLESS", str(tmp_path / "keyless.jsonl"))
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_gap_import_eval"


def test_an_empty_sample_refuses_the_import_without_an_exclusion(gap_import_eval: str) -> None:
    with pytest.raises(ImporterError, match="sample input is empty"):
        import_by_task_replay(f"{gap_import_eval}:gappy", None)


def test_an_import_with_excluded_ids_seals_what_is_kept(gap_import_eval: str) -> None:
    """Spec R18: both replays leave the ids out, so the seal both runs agree on covers the kept
    Samples only, and the declaration carries the ids the image build will drop."""

    imported: TaskReplayImport = import_by_task_replay(
        f"{gap_import_eval}:gappy", None, excluded_sample_ids=("3",)
    )

    assert imported.declaration.excluded_sample_ids == ("3",)
    assert imported.declaration.case_count == 2
    assert case_digest(replayed_cases(imported.declaration)) == imported.declaration.case_digest


def test_a_keyless_import_is_refused_unless_told_there_is_no_key(gap_import_eval: str) -> None:
    """Spec R19: an empty key is a broken row unless the import is told the Benchmark has none."""

    with pytest.raises(ImporterError, match="sample target is empty"):
        import_by_task_replay(f"{gap_import_eval}:keyless", None)

    imported: TaskReplayImport = import_by_task_replay(
        f"{gap_import_eval}:keyless", None, has_answer_key=False
    )

    assert imported.declaration.has_answer_key is False
    assert imported.declaration.case_count == 1


# --- OME-1460: the import seals the Hub commits and the seeds it replayed under ------------

from types import SimpleNamespace  # noqa: E402

import httpx  # noqa: E402
from test_task_replay import _HEAD_SHA, _OLD_SHA, FAKE_HUB_EVAL  # noqa: E402

from screamingface_engine_inspect.fetch_pins import FetchPinError, source_pins_of  # noqa: E402


@pytest.fixture
def hub_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """The fake-Hub stand-in eval of test_task_replay.py, importable by the child."""

    (tmp_path / "fake_hub_import_eval.py").write_text(FAKE_HUB_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_hub_import_eval"


def _hub_info(gated: bool = False) -> Any:
    """A stand-in for HfApi().dataset_info: HEAD resolves to `_HEAD_SHA`, a commit to
    itself. It proves what the importer seals; it does not prove the real Hub's answer."""

    def dataset_info(repo_id: str, revision: str | None) -> Any:
        """The stand-in Hub's view of one repo at one revision."""

        sha: str = _HEAD_SHA if revision in (None, "main") else str(revision)
        return SimpleNamespace(sha=sha, gated=gated)

    return dataset_info


def test_the_import_seals_the_hub_commit_head_resolved_to(hub_eval: str) -> None:
    """The eval names no revision: the importer pins the commit HEAD named at import, and
    run 2 (the image-side child) reads exactly that commit."""

    imported: TaskReplayImport = import_by_task_replay(
        f"{hub_eval}:unpinned_fetch", None, dataset_info=_hub_info()
    )

    assert imported.declaration.source_pins == {"stand-in/hub": _HEAD_SHA}
    assert imported.declaration.needs_hf_token is False
    assert imported.declaration.case_count == 4


def test_the_import_reads_the_gate_off_the_hub(hub_eval: str) -> None:
    imported: TaskReplayImport = import_by_task_replay(
        f"{hub_eval}:unpinned_fetch", None, dataset_info=_hub_info(gated=True)
    )

    assert imported.declaration.needs_hf_token is True


def test_the_second_run_forces_the_same_seed_as_the_first(hub_eval: str) -> None:
    """Spec acceptance 6: an unseeded upstream shuffle seals under the declared seed, and
    the image-side run agrees (without the seed the two runs disagree 23 times in 24)."""

    imported: TaskReplayImport = import_by_task_replay(
        f"{hub_eval}:unseeded_shuffle", None, shuffle_seed=7, dataset_info=_hub_info()
    )

    assert imported.declaration.shuffle_seed == 7
    assert imported.declaration.source_pins == {"stand-in/hub": _HEAD_SHA}


def test_an_unseeded_hub_shuffle_without_a_seed_is_refused_by_name_at_import(
    hub_eval: str,
) -> None:
    """F6: named, before any digest is taken."""

    with pytest.raises(ImporterError, match="shuffle_seed"):
        import_by_task_replay(f"{hub_eval}:unseeded_shuffle", None, dataset_info=_hub_info())


def test_a_fetch_with_no_hub_source_writes_no_source_pins(fake_eval: str) -> None:
    """R7: a URL-only or file-only eval gets no source pins, so its revision never moves."""

    imported: TaskReplayImport = import_by_task_replay(f"{fake_eval}:arithmetic", None)

    assert imported.declaration.source_pins == {}


def test_one_repo_read_at_two_commits_is_refused_by_name() -> None:
    """A declaration can pin a repo to one commit only; an eval reading two cannot be
    replayed faithfully, so the import says so rather than picking one."""

    with pytest.raises(FetchPinError, match=f"stand-in/hub.*{_HEAD_SHA}.*{_OLD_SHA}"):
        source_pins_of(
            (("stand-in/hub", _HEAD_SHA), ("stand-in/hub", _OLD_SHA)), dataset_info=_hub_info()
        )


def test_an_unreachable_hub_is_a_named_refusal_not_a_leaked_http_error() -> None:
    """Defend at the boundary: the dev reads which repo could not be resolved."""

    def unreachable(repo_id: str, revision: str | None) -> Any:
        """A Hub that cannot be reached, as the real client reports it."""

        raise httpx.ConnectError("connection refused")

    with pytest.raises(FetchPinError, match="stand-in/hub.*connection refused"):
        source_pins_of((("stand-in/hub", None),), dataset_info=unreachable)


def test_the_import_names_the_eval_when_the_hub_cannot_be_asked(hub_eval: str) -> None:
    def unreachable(repo_id: str, revision: str | None) -> Any:
        """A Hub that cannot be reached."""

        raise httpx.ConnectError("connection refused")

    with pytest.raises(ImporterError, match=f"{hub_eval}:unpinned_fetch: cannot resolve"):
        import_by_task_replay(f"{hub_eval}:unpinned_fetch", None, dataset_info=unreachable)


def test_a_seed_the_eval_never_needs_is_refused_by_name(fake_eval: str) -> None:
    """R10: a row must never promise an order nothing pins; the stand-in loads a JSONL file
    with no hf_dataset shuffle, so a shuffle seed would be written and never applied."""

    with pytest.raises(ImporterError, match="shuffle_seed.*never applied"):
        import_by_task_replay(f"{fake_eval}:arithmetic", None, shuffle_seed=7)


def test_a_choice_seed_the_eval_never_needs_is_refused_by_name(hub_eval: str) -> None:
    with pytest.raises(ImporterError, match="choice_shuffle_seed.*never applied"):
        import_by_task_replay(
            f"{hub_eval}:unseeded_shuffle",
            None,
            shuffle_seed=7,
            choice_shuffle_seed=3,
            dataset_info=_hub_info(),
        )


def test_a_judge_that_reads_sample_metadata_can_keep_it(fake_eval: str) -> None:
    """coconot's Judge template reads the category rubric from the Sample metadata, though
    its scorer is inspect's own (which alone would drop the metadata, D11): the importing
    agent says so, and the metadata then sits inside the Case Digest (OME-1460)."""

    kept: TaskReplayImport = import_by_task_replay(
        f"{fake_eval}:arithmetic", None, keep_sample_metadata=True
    )
    default: TaskReplayImport = import_by_task_replay(f"{fake_eval}:arithmetic", None)

    assert kept.declaration.keep_sample_metadata is True
    assert default.declaration.keep_sample_metadata is False


def test_an_import_seals_the_order_blind_digest_too(fake_eval: str) -> None:
    """OME-1492: the order-blind seal matches the Cases every build re-creates."""

    imported: TaskReplayImport = import_by_task_replay(f"{fake_eval}:arithmetic", None)

    rebuilt: list[dict[str, dict[str, object]]] = replayed_cases(imported.declaration)
    assert imported.declaration.case_set_digest == case_set_digest(rebuilt)
