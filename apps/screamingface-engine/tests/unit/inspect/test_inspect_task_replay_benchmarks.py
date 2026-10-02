# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The first Task-replay Benchmarks (OME-1273): agieval, medqa and mgsm_en grade with no network.

FEATURE: Task-replay Imported Benchmarks. Their Cases come from calling each eval's own task
function at image build (sealed by a Case Digest); grading must then read only the prepared
Cases in the image and download nothing (spec R16, R17).

INVARIANT: every test here that grades runs under `no_network`, so a scorer that reaches the
internet fails in CI instead of in a run pod that has no egress.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    ImportedBenchmark,
    imported_benchmark,
)
from screamingface_engine_inspect.envelopes import CHECK_SCHEMA, build_case_grade  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    LICENSE_TODO,
    TASK_REPLAY_CASES,
    PreparedCase,
    _write_cases,
)
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Url4Node  # noqa: E402

#: The multiple-choice keys: graded by inspect's own choice scorer against the answer key.
_MCQ_KEYS: tuple[str, ...] = (
    "agieval_lsat_ar",
    "agieval_lsat_lr",
    "agieval_lsat_rc",
    "agieval_sat_math",
    "agieval_sat_en",
    "agieval_sat_en_without_passage",
    "agieval_aqua_rat",
    "agieval_logiqa_en",
    "medqa",
)

#: Two hand-written Cases per family, in the shape the shared writer prepares. WHY by hand:
#: the real Cases need the network to fetch; these stand in for any two Cases of the family
#: and prove the grading path, not the content of the real ones. Case ids are 1..N (the
#: writer numbers them; upstream Sample ids never reach a Case).
_MCQ_CASES: list[PreparedCase] = [
    {
        "case": {"id": 1, "case_id": "1", "input": "Which seat is free?\n\nA) 1\nB) 2"},
        "grading_material": {"target": "B", "choices": ["1", "2"]},
    },
    {
        "case": {"id": 2, "case_id": "2", "input": "Who sits last?\n\nA) Ann\nB) Bo"},
        "grading_material": {"target": "A", "choices": ["Ann", "Bo"]},
    },
]
_FREE_TEXT_CASES: list[PreparedCase] = [
    {
        "case": {"id": 1, "case_id": "1", "input": "What is 6 times 7?"},
        "grading_material": {"target": "42"},
    },
    {
        "case": {"id": 2, "case_id": "2", "input": "What is 2 plus 2?"},
        "grading_material": {"target": "4"},
    },
]


def _node(benchmark: ImportedBenchmark, cases: list[PreparedCase], root: Path) -> Url4Node:
    """A url4 node serving the Benchmark over two prepared Cases in its asset layout."""

    _write_cases(cases, root / benchmark.benchmark.id)
    node: Url4Node = Url4Node("test")
    benchmark.benchmark.install(node, root)
    return node


async def _call(node: Url4Node, route: str, payload: str, intent: str) -> str:
    """Drive one route the way a run does: the payload as context, the intent as the ask."""

    result = await node.evaluate(
        render(
            expr(
                src(text(payload), name="payload", weight=0.0),
                RelExpr(path=route, context="$payload", intent=Text(intent)),
                intent=Text(""),
            )
        )
    )
    return result.text


def _row(case_id: int, answer: str) -> dict[str, object]:
    """One graded-answer row, as the run hands the aggregate route a Candidate's answer."""

    record: dict[str, object] = {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "answer": answer,
        "status": "completed",
        "refusal": None,
        "finish_reason": "stop",
        "execution": None,
    }
    return graded_answer_payload(
        case_id,
        encode_candidate_invocation(answer, "stop", None),
        [build_case_grade(case_id, [record])],
    )


async def _scores(node: Url4Node, benchmark: ImportedBenchmark, answers: list[str]) -> list[object]:
    """Grade one answer per Case through the shared aggregate; return each Case's score."""

    rows: str = json.dumps([_row(index, answer) for index, answer in enumerate(answers, start=1)])
    result = json.loads(
        await _call(node, benchmark.aggregate_route, rows, f"aggregate:{len(answers)}")
    )
    return [case["grade"]["score"] for case in result["cases"]]


@pytest.mark.parametrize("key", [*_MCQ_KEYS, "mgsm_en"])
def test_declaration_is_sealed_licensed_and_registered(key: str) -> None:
    """The seal the image build checks, the owner's license decision, and a live registration."""

    spec = TASK_REPLAY_CASES[key]
    benchmark: ImportedBenchmark = imported_benchmark(key)

    assert spec.license != LICENSE_TODO
    assert benchmark.benchmark.case_count == spec.case_count > 0
    assert benchmark.benchmark.id == f"inspect-{key}"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", _MCQ_KEYS)
async def test_a_multiple_choice_benchmark_grades_with_no_network(
    key: str, tmp_path: Path, no_network: None
) -> None:
    """Spec R17: the right letter scores 1.0 and a wrong one 0.0, with outbound network blocked."""

    benchmark: ImportedBenchmark = imported_benchmark(key)
    node: Url4Node = _node(benchmark, _MCQ_CASES, tmp_path)

    assert await _scores(node, benchmark, ["ANSWER: B", "ANSWER: B"]) == [1.0, 0.0]


@pytest.mark.asyncio
async def test_mgsm_en_grades_the_number_with_no_network(tmp_path: Path, no_network: None) -> None:
    """mgsm's numeric match reads the last number of the answer; spec R17 as above."""

    benchmark: ImportedBenchmark = imported_benchmark("mgsm_en")
    node: Url4Node = _node(benchmark, _FREE_TEXT_CASES, tmp_path)

    assert await _scores(node, benchmark, ["6 * 7 = 42\nAnswer: 42", "Answer: 5"]) == [1.0, 0.0]


def test_mgsm_en_offers_mid_run_feedback_and_the_mcq_rows_do_not() -> None:
    """OME-796: pass/fail feedback over a handful of options is an elimination attack."""

    assert imported_benchmark("mgsm_en").benchmark.check_surface is not None
    for key in _MCQ_KEYS:
        assert imported_benchmark(key).benchmark.check_surface is None


# ── OME-1273: the plain packages ─────────────────────────────────────────────────

#: The multiple-choice keys graded by inspect's choice scorer (worldsense has its own).
_PLAIN_MCQ_KEYS: tuple[str, ...] = (
    "bbq",
    "piqa",
    "cybermetric_80",
    "cybermetric_500",
    "cybermetric_2000",
    "cybermetric_10000",
    "sevenllm_mcq_zh",
    "sevenllm_mcq_en",
)

#: Two worldsense-shaped Cases: the question lists its own numbered options and the answer
#: key is the number, as capture serves them (the Task's chain is a bare generate()).
#: Stand-ins: they prove the grading path, not the content of the real 40,176.
_NUMBERED_CASES: list[PreparedCase] = [
    {
        "case": {"id": 1, "case_id": "1", "input": "Ann is before Bo. (1) yes (2) no (3) unsure"},
        "grading_material": {
            "target": "1",
            "choices": ["1", "2", "3"],
            "metadata": {"tuple_ID": 1, "problemname": "Compl.trivial", "problemsize": 3},
        },
    },
    {
        "case": {"id": 2, "case_id": "2", "input": "Bo is before Ann. (1) yes (2) no (3) unsure"},
        "grading_material": {
            "target": "2",
            "choices": ["1", "2", "3"],
            "metadata": {"tuple_ID": 2, "problemname": "Compl.trivial", "problemsize": 3},
        },
    },
]


@pytest.mark.parametrize("key", [*_PLAIN_MCQ_KEYS, "worldsense"])
def test_plain_package_declaration_is_sealed_licensed_and_registered(key: str) -> None:
    """The seal, the owner's license decision, and a live registration with no check surface."""

    spec = TASK_REPLAY_CASES[key]
    benchmark: ImportedBenchmark = imported_benchmark(key)

    assert spec.license != LICENSE_TODO
    assert benchmark.benchmark.case_count == spec.case_count > 0
    assert benchmark.benchmark.check_surface is None  # OME-796: every one is choice-shaped


@pytest.mark.asyncio
@pytest.mark.parametrize("key", _PLAIN_MCQ_KEYS)
async def test_a_plain_package_grades_with_no_network(
    key: str, tmp_path: Path, no_network: None
) -> None:
    """Spec R17: the right letter scores 1.0 and a wrong one 0.0, with outbound network blocked."""

    benchmark: ImportedBenchmark = imported_benchmark(key)
    node: Url4Node = _node(benchmark, _MCQ_CASES, tmp_path)

    assert await _scores(node, benchmark, ["ANSWER: B", "ANSWER: B"]) == [1.0, 0.0]


@pytest.mark.asyncio
async def test_worldsense_grades_the_number_with_no_network(
    tmp_path: Path, no_network: None
) -> None:
    """worldsense's own pattern scorer reads the leading number of the answer (spec R17)."""

    benchmark: ImportedBenchmark = imported_benchmark("worldsense")
    node: Url4Node = _node(benchmark, _NUMBERED_CASES, tmp_path)

    assert await _scores(node, benchmark, ["1", "1"]) == [1.0, 0.0]


#: Two worldsense Cases of its commonest shape (83% of them are two-way): the question ends
#: in a TRUE/FALSE ask and the answer key is the word. Stand-ins, as above.
_TRUE_FALSE_CASES: list[PreparedCase] = [
    {
        "case": {
            "id": 1,
            "case_id": "1",
            "input": "Ann sits left of Bo. Bo sits left of Cy. Is Ann left of Cy? TRUE or FALSE",
        },
        "grading_material": {
            "target": "TRUE",
            "choices": ["TRUE", "FALSE"],
            "metadata": {"tuple_ID": 3, "problemname": "Infer.trivial", "problemsize": 3},
        },
    },
    {
        "case": {
            "id": 2,
            "case_id": "2",
            "input": "Ann sits left of Bo. Is Bo left of Ann? TRUE or FALSE",
        },
        "grading_material": {
            "target": "FALSE",
            "choices": ["TRUE", "FALSE"],
            "metadata": {"tuple_ID": 4, "problemname": "Infer.trivial", "problemsize": 2},
        },
    },
]


@pytest.mark.asyncio
async def test_worldsense_grades_a_true_false_answer_with_no_network(
    tmp_path: Path, no_network: None
) -> None:
    """worldsense's own pattern scorer also reads TRUE/FALSE, the shape most of its Cases
    take; the numbered shape above covers the other 17% (spec R17)."""

    benchmark: ImportedBenchmark = imported_benchmark("worldsense")
    node: Url4Node = _node(benchmark, _TRUE_FALSE_CASES, tmp_path)

    assert await _scores(node, benchmark, ["TRUE", "TRUE"]) == [1.0, 0.0]


def test_worldsense_keeps_the_metadata_its_scorer_reads() -> None:
    """Its own scorer reads state.metadata, so the metadata sits inside the Case Digest."""

    assert TASK_REPLAY_CASES["worldsense"].keep_sample_metadata is True
    assert TASK_REPLAY_CASES["worldsense"].task_args == {"shuffle": False}


# ── OME-1273: SAD-mini ───────────────────────────────────────────────────────────

#: SAD-mini's four importable tasks (stages_full is refused: three Samples have an
#: empty body). Each is graded by the eval's own lenient scorer, which reads the reply's first
#: characters — "(B)", "B" or the option's text — and credits any other reply with
#: 1/options, the chance term of the paper's SAD score.
_SAD_KEYS: tuple[str, ...] = (
    "sad_facts_llms",
    "sad_facts_human_defaults",
    "sad_influence",
    "sad_stages_oversight",
)

#: The seed every sad row passes to its task: the eval shuffles each Sample's options and
#: draws the stages tasks' question wording per Sample with Python's random, unseeded by
#: default, so without it the two replays would disagree and nothing could be sealed.
_SAD_SEED: int = 7


@pytest.mark.parametrize("key", _SAD_KEYS)
def test_sad_declaration_is_sealed_licensed_registered_and_seeded(key: str) -> None:
    """The seal, the owner's license decision, a live registration with no check surface
    (OME-796: every SAD-mini task is choice-shaped), and the seed the seal depends on."""

    spec = TASK_REPLAY_CASES[key]
    benchmark: ImportedBenchmark = imported_benchmark(key)

    assert spec.license != LICENSE_TODO
    assert benchmark.benchmark.case_count == spec.case_count > 0
    assert benchmark.benchmark.check_surface is None
    assert spec.task_args == {"seed": _SAD_SEED}


@pytest.mark.asyncio
@pytest.mark.parametrize("key", _SAD_KEYS)
async def test_a_sad_benchmark_grades_with_no_network(
    key: str, tmp_path: Path, no_network: None
) -> None:
    """Spec R17: the eval's own lenient scorer reads the reply's first characters, so "(B)"
    scores 1.0 against B and 0.0 against A, with outbound network blocked."""

    benchmark: ImportedBenchmark = imported_benchmark(key)
    node: Url4Node = _node(benchmark, _MCQ_CASES, tmp_path)

    assert await _scores(node, benchmark, ["(B)", "(B)"]) == [1.0, 0.0]


@pytest.mark.asyncio
async def test_sad_reads_only_the_start_of_a_reply(tmp_path: Path, no_network: None) -> None:
    """The eval asks for the label and nothing else, and its scorer reads only the start of
    the reply: inspect's usual "ANSWER: B" begins with "A", so it is read as option A and
    graded wrong against B; a reply in no recognised form earns 1/options, the chance term
    of the paper's SAD score — so the board's mean per-case score IS the SAD score."""

    benchmark: ImportedBenchmark = imported_benchmark("sad_facts_llms")
    node: Url4Node = _node(benchmark, _MCQ_CASES, tmp_path)

    assert await _scores(node, benchmark, ["ANSWER: B", "no idea"]) == [0.0, 0.5]
