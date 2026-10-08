# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""MuSiQue-Ans as a LOCAL inspect Task (OME-1513) — the first Benchmark we author in inspect's
shape and feed to the importer instead of hand-building a folder.

What these tests pin, and why:

- conservation: the Benchmark's grade hook gives exactly the numbers the paper's own scorer
  gives for the same reply — the vendored `AnswerMetric` / `SupportMetric` are the oracle, so
  "our number means what the paper's number means" is a test, not a promise;
- the reply reader: the LAST `Answer:` / `Supporting paragraphs:` wins, however a model wraps
  or orders the labels, and a reply with no label is graded as a whole, never dropped;
- the prompt bytes: a synthetic row renders to a pinned literal — the prompt is Benchmark
  identity on a judge-free Benchmark;
- absent Sample metadata never raises — the no-network grading lane feeds stand-in Cases
  without metadata; the paper's metric then scores "cited nothing, expected nothing" as
  support F1 1.0 and any citation as 0.0 (production Cases always carry the key: it is in
  the Case Digest);
- the row: origin `screamingface` (no inspect porter list), three Named Scores in the
  published order, answer F1 the headline.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.model import ChatMessageUser, ModelOutput  # noqa: E402
from inspect_ai.scorer import Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.provenance import provenance_gaps  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    _task_replay_pins,
    imported_benchmark,
)
from screamingface_engine_inspect.local_tasks import source_digest, task_source_pin  # noqa: E402
from screamingface_engine_inspect.local_tasks.musique.musique import (  # noqa: E402
    CASE_TEMPLATE,
    _record_to_sample,
    extract_answer,
    extract_support,
    musique_answer_em,
    musique_answer_f1,
    musique_support_f1,
)
from screamingface_engine_inspect.local_tasks.musique.vendor.answer import (  # noqa: E402
    AnswerMetric,
)
from screamingface_engine_inspect.local_tasks.musique.vendor.support import (  # noqa: E402
    SupportMetric,
)
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES  # noqa: E402

# (reply, gold answer + aliases, gold supporting paragraph numbers). The three replies are
# hand-written to hit three outcomes: everything right, a partial answer with one support hit,
# and a reply that never wrote either label.
_GOLD: list[str] = ["Miquette Giraudy", "Giraudy"]
_SUPPORT: list[int] = [5, 10]
_CASES: list[str] = [
    "Paragraph 10 is Steve Hillage's album; the spouse is in 5.\n"
    "Supporting paragraphs: 5, 10\n"
    "Answer: Miquette Giraudy",
    "Supporting paragraphs: 10\nAnswer: Giraudy, Miquette's partner",
    "I think it is Steve Hillage.",
]


def _paper_scores(reply: str) -> tuple[float, float, float]:
    """The oracle: the paper's own accumulators over ONE reply — (answer F1, exact, support F1)."""

    answer: AnswerMetric = AnswerMetric()
    answer(extract_answer(reply), _GOLD)
    exact, f1 = answer.get_metric()
    support: SupportMetric = SupportMetric()
    support(extract_support(reply), _SUPPORT)
    _, support_f1 = support.get_metric()
    return float(f1), float(exact), float(support_f1)


def _request(case_id: int, reply: str, material: dict[str, Any]) -> GradeRequest:
    return GradeRequest(
        case_id=case_id,
        input=TextPayload(text="q"),
        answer=TextPayload(text=reply),
        row={"case": {"status": "answered"}},
        material=material,
    )


async def _score_with(scorer: Any, reply: str, metadata: dict[str, Any] | None) -> float:
    """inspect's own (state, target) → Score call, as the scorer adapter makes it."""

    state = TaskState(
        model="screamingface/candidate",  # type: ignore[arg-type]
        sample_id=1,
        epoch=1,
        input="q",
        messages=[ChatMessageUser(content="q")],
        output=ModelOutput.from_content(model="screamingface/candidate", content=reply),
        metadata=metadata,
    )
    score: Score = await scorer(state, Target(_GOLD))
    return float(score.value)  # type: ignore[arg-type]


# ── conservation: the grade hook returns the paper's numbers ──────────────────────────────


@pytest.mark.asyncio
async def test_the_grade_hook_gives_the_papers_own_numbers_for_three_replies() -> None:
    hook = imported_benchmark("musique").aggregation().grade_case
    material: dict[str, Any] = {"target": _GOLD, "metadata": {"supporting_idx": _SUPPORT}}
    for case_id, reply in enumerate(_CASES, start=1):
        outcome: CaseGradeOutcome = await hook(_request(case_id, reply, material))
        f1, exact, support_f1 = _paper_scores(reply)
        assert outcome.failure_code is None, outcome.checks
        assert outcome.scores == {
            "musique_answer_f1": f1,
            "musique_answer_em": exact,
            "musique_support_f1": support_f1,
        }
        assert outcome.score == f1
    # The three replies really hit three outcomes (the oracle is not trivially all-zero).
    firsts = [_paper_scores(reply)[0] for reply in _CASES]
    assert firsts[0] == 1.0 and 0.0 < firsts[1] < 1.0 and firsts[2] == 0.0


# ── the reply reader ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("reply", "answer", "support"),
    [
        # the LAST label wins: a model may say "the answer:" while reasoning
        (
            "maybe the answer: Hillage? No.\nSupporting paragraphs: 10, 5, 5\nAnswer: Giraudy",
            "Giraudy",
            [5, 10],
        ),
        # markdown-wrapped label, value on the same line
        ("Supporting paragraphs: 5\n**Answer:** Giraudy", "** Giraudy", [5]),
        # label alone on its line: the next non-empty line is the value
        ("Supporting paragraphs:\n5, 10\nAnswer:\n\nGiraudy", "Giraudy", [5, 10]),
        # labels in the other order, each value stops at the other label
        ("Answer: Giraudy Supporting paragraphs: 5", "Giraudy", [5]),
        # labels match in any case — "ANSWER:" is what several models emit
        ("SUPPORTING PARAGRAPHS: 10\nANSWER: Giraudy", "Giraudy", [10]),
        # no label at all: the whole reply is the answer, the support set is empty
        ("I think it is Steve Hillage.", "I think it is Steve Hillage.", []),
        # a label with nothing after it commits to the empty answer
        ("Answer:", "", []),
    ],
)
def test_the_reply_reader_takes_the_last_committed_lines(
    reply: str, answer: str, support: list[int]
) -> None:
    assert extract_answer(reply) == answer
    assert extract_support(reply) == support


# ── the prompt bytes ──────────────────────────────────────────────────────────────────────


def test_a_row_renders_to_the_pinned_prompt_bytes() -> None:
    """INVARIANT: these bytes are Benchmark identity (they sit inside the Case Digest); an edit
    here is a new Benchmark, so the literal below is the review act."""

    row: dict[str, Any] = {
        "id": "2hop__1_2",
        "question": "Who is the spouse?",
        "answer": "Miquette Giraudy",
        "answer_aliases": ["Giraudy"],
        "paragraphs": [
            {"idx": 0, "title": "A", "paragraph_text": "First.", "is_supporting": False},
            {"idx": 1, "title": "B", "paragraph_text": "Second.", "is_supporting": True},
        ],
    }
    sample: Sample = _record_to_sample(row)
    assert sample.input == (
        "Answer the question using the numbered paragraphs below.\n"
        "\n"
        "[0] A\nFirst.\n"
        "\n"
        "[1] B\nSecond.\n"
        "\n"
        "Question: Who is the spouse?\n"
        "\n"
        "Think it through if that helps, then end your reply with these two lines, in this order:\n"
        "Supporting paragraphs: <the numbers of the paragraphs you used, comma-separated>\n"
        "Answer: <the answer, in as few words as possible>"
    )
    assert sample.target == ["Miquette Giraudy", "Giraudy"]
    assert sample.metadata == {"supporting_idx": [1], "hop_type": "2hop"}
    assert CASE_TEMPLATE.endswith("Answer: <the answer, in as few words as possible>")


# ── absent metadata never raises ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_support_f1_without_metadata_never_raises_and_scores_by_the_papers_rule() -> None:
    """WHY: the no-network grading lane feeds stand-in Cases with no Sample metadata; a raise
    there would show as a grading failure on a Benchmark that grades fine in production.
    The empty gold list is the paper's own metric's input, so a reply that cites paragraphs
    scores 0.0 and one that cites none scores 1.0 ("cited nothing, expected nothing") — not
    a blanket 0.0 (review finding on #1292). Production never hits this: `supporting_idx`
    is in every Case's metadata and the Case Digest."""

    assert await _score_with(musique_support_f1(), _CASES[0], None) == 0.0
    assert await _score_with(musique_support_f1(), "Answer: Kalamazoo", None) == 1.0
    assert await _score_with(musique_support_f1(), _CASES[0], {"supporting_idx": [5, 10]}) == 1.0
    assert await _score_with(musique_answer_f1(), _CASES[0], None) == 1.0
    assert await _score_with(musique_answer_em(), _CASES[1], None) == 0.0


# ── the row ───────────────────────────────────────────────────────────────────────────────


def test_the_row_is_our_own_benchmark_with_three_named_scores_and_no_porter_list() -> None:
    spec = next(row for row in BENCHMARKS if row.key == "musique")
    benchmark = imported_benchmark("musique")
    assert benchmark.benchmark.id == "musique"  # the bare key: nothing came from inspect_evals
    assert benchmark.benchmark.origin == "screamingface"
    assert benchmark.benchmark.inspect_contributors is None
    assert provenance_gaps(benchmark.benchmark) == []
    assert benchmark.named_scores == (
        "musique_answer_f1",
        "musique_answer_em",
        "musique_support_f1",
    )
    assert spec.scorer.endswith(":musique_answer_f1")
    # OME-1475 spec D14: no Draft Feedback; the importer's free-text default was overridden.
    assert spec.with_check_surface is False
    assert TASK_REPLAY_CASES["musique"].keep_sample_metadata is True
    assert TASK_REPLAY_CASES["musique"].case_count == 2417


# ── the Task's own source is Benchmark identity ──────────────────────────────────────────


def test_a_local_tasks_source_is_pinned_into_its_revision() -> None:
    """INVARIANT (review finding on #1292): for an inspect_evals import the marking scheme is
    pinned by `inspect-evals==<version>`; for a local Task it is OUR file, so its bytes must be
    in the revision or the grading rule could change under a published score."""

    pins = _task_replay_pins(TASK_REPLAY_CASES["musique"])
    source = [pin for pin in pins if pin.startswith("task_source=")]
    assert len(source) == 1 and len(source[0]) == len("task_source=") + 64
    # an inspect_evals import carries no such pin — its scorer is the pinned package's
    assert not [p for p in _task_replay_pins(TASK_REPLAY_CASES["gsm8k"]) if "task_source" in p]


def test_a_package_with_no_python_files_is_refused_a_digest(tmp_path: Path) -> None:
    """WHY: sha256 of nothing is a valid-looking digest; a mislocated package would pin
    "no source" and the revision would never move when the real source changed."""

    (tmp_path / "README.md").write_text("prose only")
    with pytest.raises(ValueError, match="no .py files"):
        source_digest(tmp_path)


def test_every_task_outside_inspect_evals_is_source_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHY: a Task elsewhere in the plugin or in a third-party package has no
    `inspect-evals==` pin to lean on; without a source pin its grading rule could change under
    a published score with no test failing. Only inspect_evals' own Tasks are exempt."""

    # a stand-in third-party Task package on sys.path: one module, one function
    package = tmp_path / "thirdparty_tasks"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "task.py").write_text("def task():\n    return None\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    pins = task_source_pin("thirdparty_tasks.task:task")
    assert len(pins) == 1 and pins[0] == f"task_source={source_digest(package)}"
    assert task_source_pin("inspect_evals.gsm8k.gsm8k:gsm8k") == ()
    with pytest.raises(ValueError, match="cannot be located"):
        task_source_pin("no_such_package.task:task")


def test_one_byte_in_the_task_package_moves_the_source_digest(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    (package / "vendor").mkdir(parents=True)
    (package / "task.py").write_text("x = 1\n")
    (package / "vendor" / "metric.py").write_text("y = 2\n")
    (package / "README.md").write_text("prose is not identity\n")
    before: str = source_digest(package)
    (package / "README.md").write_text("prose changed\n")
    assert source_digest(package) == before, "only .py files are the marking scheme"
    (package / "vendor" / "metric.py").write_text("y = 3\n")
    assert source_digest(package) != before, "a vendored grader edit is a new Benchmark"
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "task.cpython-312.pyc").write_bytes(b"\x00")
    assert source_digest(package) == source_digest(package), "stable across runs"


# ── the hop type rides to the Report ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_headline_check_carries_the_cases_hop_type() -> None:
    """WHY: the dev set mixes 2-, 3- and 4-hop questions; a per-hop view of a run (the paper's
    Table 5) needs the hop type on each Case's row, not only inside the Case Digest."""

    hook = imported_benchmark("musique").aggregation().grade_case
    material: dict[str, Any] = {
        "target": _GOLD,
        "metadata": {"supporting_idx": _SUPPORT, "hop_type": "2hop"},
    }
    outcome: CaseGradeOutcome = await hook(_request(1, _CASES[0], material))
    headline = outcome.checks[0]
    assert headline["evidence"][0]["metadata"]["hop_type"] == "2hop"
