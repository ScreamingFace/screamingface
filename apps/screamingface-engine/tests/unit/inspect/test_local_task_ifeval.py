# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""IFEval as a LOCAL inspect Task (OME-1527) — the hand-built folder, moved.

What these tests pin, and why:

- conservation: four canned Cases (real official rows, canned replies) are checked exactly as
  the hand-built grader checked them — the same strict and loose verdict per instruction, the
  same descriptions, the same Case scores — and the run publishes the hand-built numbers: the
  headline 0.5, instruction-level strict 0.4444, prompt-level loose 0.5, instruction-level
  loose 0.5556 and pass_rate 0.4444. The literals were produced by driving the hand-built
  check route and `grade.aggregate` on these replies at 1bc092ff6, before the folder was
  deleted, so "same exam, same score" is a test;
- the Draft Feedback record, byte for byte: in a Corrective Loop the words go into the next
  round's prompt, so the record the check surface returns must be the hand-built route's
  bytes. The four literals below are that route's output on the same drafts. Before the
  deletion the same comparison ran over 11,505 drafts (the 176 recorded replies of the ifeval
  golden against its 50 Cases, plus five drafts against all 541 Cases): 0 differ;
- the pooled instruction-level accuracy, never a mean of Case fractions (the worked example
  of the metric's docstring), and an abstained Case's Score (marked ``candidate_abstained``,
  with or without its instructions) counted as a failed prompt whatever its verdicts say;
- the tokenizers: Cases whose checker counts sentences or words grade with the punkt and
  punkt_tab the image build packs into the bundle, with the network off (R8's proof);
- the Candidate's prompt: the official prompt of every row, byte for byte, with the one known
  Hub divergence (official key 2785) patched and any other refused, and changed instruction
  ids or arguments refused for every key;
- the rows: id `ifeval`, origin `screamingface`, no answer key, no judge, Draft Feedback on
  with the scorer's own words, four Named Scores headline first, the pooled whole-run metric.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import hashlib
import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

import nltk  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.scorer import SampleScore, Score  # noqa: E402
from local_ifeval_helpers import write_ifeval_bundle  # noqa: E402
from test_local_task_draco import _abstained_row  # noqa: E402
from test_whole_run_metric import _row  # noqa: E402

from screamingface_engine.benchmarks.case_records import CANDIDATE_ABSTAINED  # noqa: E402
from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine.benchmarks.nltk_data import NLTK_DATA_DIR  # noqa: E402
from screamingface_engine.benchmarks.provenance import provenance_gaps  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    OWNER_ALLOWED_DRAFT_FEEDBACK,
    imported_benchmark,
)
from screamingface_engine_inspect.local_tasks.ifeval.ifeval import (  # noqa: E402
    ifeval_accuracy,
    official_rows,
    record_to_sample,
    verify_against_official,
)
from screamingface_engine_inspect.local_tasks.ifeval.vendor import instructions_util  # noqa: E402
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES, prepared_case  # noqa: E402
from screamingface_engine_inspect.single_shot import benchmark_aggregate_async  # noqa: E402
from screamingface_engine_inspect.task_replay import _prepare_nltk_data  # noqa: E402
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Url4Node  # noqa: E402

_OFFICIAL: dict[int, dict[str, Any]] = {row["key"]: row for row in official_rows()}

#: Four canned Cases: (official key, reply). One instruction met (1001); none of three met
#: strictly but one loosely, once the line holding the comma is dropped (1000); the one row
#: whose "#" letter the official checker would randomize, honoured literally (1122); one of
#: three met, which makes the Draft Feedback's unrounded third (142).
_CASES: list[tuple[int, str]] = [
    (1001, "Hark thy journey begins in Tokyo."),
    (1000, "**Raymond**, a count.\n*Section one*"),
    (1122, "new drop tonight #playboy #style #night #fun"),
    (142, "a cat walked in"),
]

#: What the hand-built grader recorded for each Case: (strict, loose, descriptions).
#: Captured from `benchmarks/ifeval` at 1bc092ff6 before its deletion.
_HAND_BUILT: list[tuple[list[bool], list[bool], list[str]]] = [
    ([True], [True], ["In your entire response, refrain from the use of any commas."]),
    (
        [False, False, False],
        [True, False, False],
        [
            "In your entire response, refrain from the use of any commas.",
            "Highlight at least 3 sections in your answer with markdown, i.e. *highlighted "
            "section*.",
            "Answer with at least 300 words.",
        ],
    ),
    (
        [True, True],
        [True, True],
        [
            "Your entire response should be in English, and in all lowercase letters. No "
            "capital letters are allowed.",
            "In your response, the letter # should appear at least 4 times.",
        ],
    ),
    (
        [False, False, True],
        [False, False, True],
        [
            "Wrap your entire response with double quotation marks.",
            "In your response, the word knock should appear at least 2 times.",
            "Include keywords ['cat'] in the response.",
        ],
    ),
]

#: The hand-built run over the four Cases: Case scores, headline, run metrics.
_HAND_BUILT_CASE_SCORES: list[float] = [1.0, 0.0, 1.0, 0.0]
_HAND_BUILT_HEADLINE: float = 0.5
_HAND_BUILT_METRICS: dict[str, float] = {
    "inst_level_strict_accuracy": 0.4444,
    "prompt_level_loose_accuracy": 0.5,
    "inst_level_loose_accuracy": 0.5556,
    "pass_rate": 0.4444,
}

#: The hand-built check-surface record for each canned draft, exactly as its route returned it.
_HAND_BUILT_DRAFT_FEEDBACK: list[str] = [
    '{"schema":"screamingface.check-surface.v1","passed":true,"satisfaction":1.0,"feedback":"",'
    '"answer":"Hark thy journey begins in Tokyo.","invocation":"{\\"schema\\":\\"screamingface.'
    'candidate-invocation.v1\\",\\"status\\":\\"completed\\",\\"output\\":\\"Hark thy journey '
    'begins in Tokyo.\\",\\"finish_reason\\":\\"stop\\",\\"refusal\\":null,\\"execution\\":null}"}',
    '{"schema":"screamingface.check-surface.v1","passed":false,"satisfaction":0.0,"feedback":"The '
    "answer failed these requirements: In your entire response, refrain from the use of any "
    "commas. | Highlight at least 3 sections in your answer with markdown, i.e. *highlighted "
    'section*. | Answer with at least 300 words.","answer":"**Raymond**, a count.\\n*Section one*'
    '","invocation":"{\\"schema\\":\\"screamingface.candidate-invocation.v1\\",\\"status\\":\\"'
    'completed\\",\\"output\\":\\"**Raymond**, a count.\\\\n*Section one*\\",\\"finish_reason\\":'
    '\\"stop\\",\\"refusal\\":null,\\"execution\\":null}"}',
    '{"schema":"screamingface.check-surface.v1","passed":true,"satisfaction":1.0,"feedback":"",'
    '"answer":"new drop tonight #playboy #style #night #fun","invocation":"{\\"schema\\":\\"'
    'screamingface.candidate-invocation.v1\\",\\"status\\":\\"completed\\",\\"output\\":\\"new '
    'drop tonight #playboy #style #night #fun\\",\\"finish_reason\\":\\"stop\\",\\"refusal\\":'
    'null,\\"execution\\":null}"}',
    '{"schema":"screamingface.check-surface.v1","passed":false,"satisfaction":0.3333333333333333,'
    '"feedback":"The answer failed these requirements: Wrap your entire response with double '
    'quotation marks. | In your response, the word knock should appear at least 2 times.",'
    '"answer":"a cat walked in","invocation":"{\\"schema\\":\\"screamingface.candidate-'
    'invocation.v1\\",\\"status\\":\\"completed\\",\\"output\\":\\"a cat walked in\\",\\"'
    'finish_reason\\":\\"stop\\",\\"refusal\\":null,\\"execution\\":null}"}',
]

#: sha256 of the hand-built bundle's 541 Candidate prompts (`json.dumps` of the `input` list of
#: its `cases.json`, prepared at 1bc092ff6 before the deletion).
_HAND_BUILT_PROMPTS_SHA256: str = "9ca48d2272ccbb0b215b4a5ec199d83e998fc07af16cc26095934c7567d805ee"

#: The Named Scores, headline first: the paper's published order.
_NAMED_SCORES: tuple[str, ...] = (
    "prompt_level_strict_accuracy",
    "inst_level_strict_accuracy",
    "prompt_level_loose_accuracy",
    "inst_level_loose_accuracy",
)


def _bundle_rows() -> list[tuple[str, list[str], list[dict[str, Any]]]]:
    """The four canned Cases' official prompts and instructions, in Case order."""

    return [
        (
            _OFFICIAL[key]["prompt"],
            _OFFICIAL[key]["instruction_id_list"],
            _OFFICIAL[key]["kwargs"],
        )
        for key, _ in _CASES
    ]


def _material(index: int) -> dict[str, Any]:
    """Case ``index``'s Grading Material as the real row prepares it, after its JSON round trip."""

    row: dict[str, Any] = _OFFICIAL[_CASES[index - 1][0]]
    sample: Sample = record_to_sample(row, index)
    case = prepared_case(sample, index, str(sample.input), TASK_REPLAY_CASES["ifeval"])
    return json.loads(json.dumps(case["grading_material"]))


async def _grade(index: int) -> CaseGradeOutcome:
    """Grade canned Case ``index`` through ifeval's real per-Case grading hook."""

    key, reply = _CASES[index - 1]
    hook = imported_benchmark("ifeval").aggregation().grade_case
    return await hook(
        GradeRequest(
            case_id=index,
            input=TextPayload(text=_OFFICIAL[key]["prompt"]),
            answer=TextPayload(text=reply),
            row={"case": {"status": "answered"}},
            material=_material(index),
        )
    )


# ── conservation: the hand-built grader's numbers, pinned as literals ─────────────────────


@pytest.mark.asyncio
async def test_each_case_is_checked_as_the_hand_built_grader_checked_it() -> None:
    """Strict and loose verdict per instruction, the checker's descriptions, the Case score and
    the Case's four Named Scores, Case by Case (the "#" row honoured literally)."""

    for index, (strict, loose, descriptions) in enumerate(_HAND_BUILT, start=1):
        outcome: CaseGradeOutcome = await _grade(index)
        assert outcome.failure_code is None, outcome.checks
        records: list[dict[str, Any]] = outcome.checks[0]["evidence"][0]["metadata"]["instructions"]
        assert [record["strict"] for record in records] == strict, index
        assert [record["loose"] for record in records] == loose, index
        assert [record["description"] for record in records] == descriptions, index
        assert outcome.score == _HAND_BUILT_CASE_SCORES[index - 1], index
        assert outcome.scores == {
            "prompt_level_strict_accuracy": float(all(strict)),
            "inst_level_strict_accuracy": sum(strict) / len(strict),
            "prompt_level_loose_accuracy": float(all(loose)),
            "inst_level_loose_accuracy": sum(loose) / len(loose),
        }


@pytest.mark.asyncio
async def test_the_run_publishes_the_hand_built_numbers_with_pooled_named_scores(
    tmp_path: Path,
) -> None:
    """The headline guarantee: the same replies score 0.5 here and in the hand-built Benchmark,
    beside the same four run metrics under the same keys (the Report's card reads
    ``pass_rate``). The instruction-level Named Scores carry the POOLED numbers (4 of 9
    instructions met strictly: 0.4444), never the mean of the Case fractions ((1 + 0 + 1 +
    1/3) / 4 = 0.5833)."""

    write_ifeval_bundle(tmp_path, _bundle_rows())
    rows: str = json.dumps([_row(index, reply) for index, (_, reply) in enumerate(_CASES, 1)])

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("ifeval"), rows, tmp_path, case_ids=(1, 2, 3, 4)
    )

    assert result["score"] == _HAND_BUILT_HEADLINE
    assert [case["grade"]["score"] for case in result["cases"]] == _HAND_BUILT_CASE_SCORES
    # The hand-built keys and values, plus the tally's own count of the Cases it saw.
    assert result["metrics"] == {**_HAND_BUILT_METRICS, "correct": 2, "scored_cases": 4}
    assert result["scores"] == {
        "prompt_level_strict_accuracy": 0.5,
        "inst_level_strict_accuracy": 0.4444,
        "prompt_level_loose_accuracy": 0.5,
        "inst_level_loose_accuracy": 0.5556,
    }
    assert list(result["scores"]) == list(_NAMED_SCORES)


def test_instruction_level_accuracy_is_pooled_over_the_runs_instructions() -> None:
    """Worked example: Case A follows 1 of 1 instruction, Case B 0 of 3 strictly and 1 of 3
    loosely → instruction-level strict 1/4 = 0.25 (the Case mean would say 0.5), loose 2/4."""

    def case(strict: list[bool], loose: list[bool]) -> SampleScore:
        records: list[dict[str, Any]] = [
            {"id": "x", "description": "d", "strict": met, "loose": loosely}
            for met, loosely in zip(strict, loose, strict=True)
        ]
        return SampleScore(score=Score(value=0, metadata={"instructions": records}))

    # Any: inspect types a metric's input as list[Score]; it is handed SampleScores at run time.
    tally: Any = ifeval_accuracy()
    numbers: Any = tally([case([True], [True]), case([False] * 3, [True, False, False])])

    assert numbers == {
        "prompt_level_strict_accuracy": 0.5,
        "inst_level_strict_accuracy": 0.25,
        "prompt_level_loose_accuracy": 0.5,
        "inst_level_loose_accuracy": 0.5,
        "pass_rate": 0.25,
    }


def _verdicts(strict: list[bool], loose: list[bool]) -> list[dict[str, Any]]:
    """Per-instruction records as the scorer files them in a Score's metadata."""

    return [
        {"id": "x", "description": "d", "strict": met, "loose": loosely}
        for met, loosely in zip(strict, loose, strict=True)
    ]


def test_an_abstained_score_fails_its_prompt_and_every_listed_instruction() -> None:
    """WHY: the lane hands the metric an abstained Case's Score zeroed and marked
    ``candidate_abstained``, keeping the checker's verdicts on the empty answer in its metadata;
    an abstain earns nothing, so those verdicts never count, even when they say "met". Case A
    follows 1 of 1; abstained Case B lists 3 instructions all marked met → strict and loose
    prompt-level 1/2, instruction-level 1/4 (crediting B's verdicts would say 4/4)."""

    followed: SampleScore = SampleScore(
        score=Score(value=0, metadata={"instructions": _verdicts([True], [True])})
    )
    abstained: SampleScore = SampleScore(
        score=Score(
            value=0.0,
            metadata={
                "instructions": _verdicts([True] * 3, [True] * 3),
                CANDIDATE_ABSTAINED: True,
            },
        )
    )
    # Any: inspect types a metric's input as list[Score]; it is handed SampleScores at run time.
    tally: Any = ifeval_accuracy()

    assert tally([followed, abstained]) == {
        "prompt_level_strict_accuracy": 0.5,
        "inst_level_strict_accuracy": 0.25,
        "prompt_level_loose_accuracy": 0.5,
        "inst_level_loose_accuracy": 0.25,
        "pass_rate": 0.25,
    }


def test_a_bare_abstained_score_is_one_failed_prompt_with_no_instructions() -> None:
    """When inspect filed no Score for an abstained Case, the metric gets a bare 0.0 marked
    ``candidate_abstained`` with no ``instructions``: it fails one prompt and adds no
    instructions (the count is unknown, and a guessed one would be a wrong number). Case A
    follows 1 of 1 → prompt-level 1/2, instruction-level 1/1. Unmarked, the same bare Score is
    still refused: only the abstain mark excuses missing verdicts."""

    followed: SampleScore = SampleScore(
        score=Score(value=0, metadata={"instructions": _verdicts([True], [True])})
    )
    bare: SampleScore = SampleScore(score=Score(value=0.0, metadata={CANDIDATE_ABSTAINED: True}))
    # Any: inspect types a metric's input as list[Score]; it is handed SampleScores at run time.
    tally: Any = ifeval_accuracy()

    assert tally([followed, bare]) == {
        "prompt_level_strict_accuracy": 0.5,
        "inst_level_strict_accuracy": 1.0,
        "prompt_level_loose_accuracy": 0.5,
        "inst_level_loose_accuracy": 1.0,
        "pass_rate": 1.0,
    }
    with pytest.raises(KeyError, match="instructions"):
        tally([followed, SampleScore(score=Score(value=0.0))])


@pytest.mark.asyncio
async def test_an_abstained_case_costs_one_case_and_its_instructions(tmp_path: Path) -> None:
    """WHY (OME-1289): a Fusion that found no answer costs one Case, never a hole in the mean.
    Case 1 answers and passes; Case 4 abstains, so it scores 0.0 in every column, and the pooled
    tally counts its three instructions as unmet (the empty answer meets none): 1 of 4."""

    write_ifeval_bundle(tmp_path, _bundle_rows())
    rows: str = json.dumps([_row(1, _CASES[0][1]), _abstained_row(4)])

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("ifeval"), rows, tmp_path, case_ids=(1, 4)
    )

    answered, abstained = result["cases"]
    assert (answered["status"], answered["grade"]["score"]) == ("scored", 1.0)
    assert (abstained["status"], abstained["grade"]["score"]) == ("scored", 0.0)
    assert abstained.get("abstained") is True
    assert abstained["grade"]["scores"] == dict.fromkeys(_NAMED_SCORES, 0.0)
    assert result["score"] == 0.5
    assert result["metrics"]["inst_level_strict_accuracy"] == 0.25


# ── the tokenizer corpus: fetched at image build, read offline at grading ─────────────────

#: Three Cases whose checker tokenizes with nltk: (official key, reply). Key 3739 asks for
#: fewer than 3 sentences (punkt's sentence splitter counts them), key 2849 for at least 2
#: all-capital words (nltk's word tokenizer, which reads punkt_tab, finds them).
_TOKENIZED_CASES: list[tuple[int, str]] = [
    # 2 sentences, because punkt knows "Mr." ends no sentence; splitting on every full stop
    # would count 3 and fail it.
    (3739, "It is Mr. Green. He is jealous."),
    (2849, "THE GUY from NANTUCKET."),
    (3739, "One cat. Two dogs. Three birds."),
]


def _no_network(*_: Any, **__: Any) -> None:
    """The grading job's egress: none."""

    raise OSError("network disabled in this test")


@pytest.mark.asyncio
async def test_ifeval_grades_with_the_bundled_tokenizers_and_no_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """64 of the 541 Cases tokenize with nltk, and the grading job has no network, so their
    checker must read the punkt and punkt_tab the image build packed into the bundle.

    The build half is the real one: Case Preparation's own nltk step downloads both resources
    into the bundle and checks they seal to the row's pinned digest (so this test needs the
    network, as the image build does, and fails loudly without it; it never skips). The
    grading half runs with sockets and nltk's downloader refused, nltk's search path emptied
    (no machine corpus can answer) and its loaded tokenizers forgotten: before the installer
    points nltk at the bundle, counting sentences raises LookupError; after, the three Cases
    grade as the checker says.
    """

    bundle: Path = tmp_path / "ifeval"
    write_ifeval_bundle(
        bundle,
        [
            (
                _OFFICIAL[key]["prompt"],
                _OFFICIAL[key]["instruction_id_list"],
                _OFFICIAL[key]["kwargs"],
            )
            for key, _ in _TOKENIZED_CASES
        ],
    )
    # WHY a fresh path list: nltk's search path is process-wide; the build's download
    # registers the bundle in it, and a developer's ~/nltk_data must not answer either way.
    monkeypatch.setattr(nltk.data, "path", [])
    _prepare_nltk_data(TASK_REPLAY_CASES["ifeval"], bundle)

    # The grading job is another process: nothing on its path, nothing loaded yet.
    monkeypatch.setattr(nltk.data, "path", [])
    monkeypatch.setattr(nltk.data, "_resource_cache", {})
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(nltk, "download", _no_network)
    instructions_util._get_sentence_tokenizer.cache_clear()
    nltk.tokenize._get_punkt_tokenizer.cache_clear()
    try:
        with pytest.raises(LookupError):
            instructions_util.count_sentences("One. Two.")

        imported_benchmark("ifeval").benchmark.install(Url4Node("ifeval-offline"), tmp_path)
        rows: str = json.dumps(
            [_row(index, reply) for index, (_, reply) in enumerate(_TOKENIZED_CASES, 1)]
        )
        result: dict[str, Any] = await benchmark_aggregate_async(
            imported_benchmark("ifeval"), rows, bundle, case_ids=(1, 2, 3)
        )
    finally:
        # The tokenizers loaded from this test's bundle must not outlive it.
        instructions_util._get_sentence_tokenizer.cache_clear()
        nltk.tokenize._get_punkt_tokenizer.cache_clear()

    assert nltk.data.path == [str(bundle / NLTK_DATA_DIR)]
    assert [case["status"] for case in result["cases"]] == ["scored"] * 3
    assert [case["grade"]["score"] for case in result["cases"]] == [1.0, 1.0, 0.0]


# ── the Draft Feedback record: the hand-built route's bytes ───────────────────────────────


async def _check_surface(node: Url4Node, route: str, payload: str, intent: str) -> str:
    """Call the check-surface route as a compiled Corrective Loop does; its text back."""

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


@pytest.mark.asyncio
async def test_the_draft_feedback_record_is_the_hand_built_one_byte_for_byte(
    tmp_path: Path,
) -> None:
    """INVARIANT: one changed character (the satisfaction's digits, the separator, the opening
    words) would move every later Candidate request of a Corrective Loop, and its golden."""

    write_ifeval_bundle(tmp_path / "ifeval", _bundle_rows())
    benchmark = imported_benchmark("ifeval")
    node = Url4Node("ifeval-draft-feedback")
    benchmark.benchmark.install(node, tmp_path)

    for (key, reply), expected in zip(_CASES, _HAND_BUILT_DRAFT_FEEDBACK, strict=True):
        payload: str = json.dumps(
            {
                "input": _OFFICIAL[key]["prompt"],
                "invocation": encode_candidate_invocation(reply, "stop", None),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        record: str = await _check_surface(node, benchmark.check_surface_route, payload, "check")
        assert record == expected, key
        # The words the loop pastes into the next round: the record's feedback, untouched.
        words: str = await _check_surface(node, benchmark.check_surface_route, record, "feedback")
        assert words == json.loads(expected)["feedback"], key


@pytest.mark.asyncio
async def test_an_abstained_draft_is_checked_and_fails(tmp_path: Path) -> None:
    """A Corrective round that abstained is still a checkable draft (OME-1289, AB-D7): the check
    surface accepts the marked record and fails it, so the loop can try another round."""

    write_ifeval_bundle(tmp_path / "ifeval", _bundle_rows())
    benchmark = imported_benchmark("ifeval")
    node = Url4Node("ifeval-abstained-draft")
    benchmark.benchmark.install(node, tmp_path)
    payload: str = json.dumps(
        {
            "input": _OFFICIAL[1001]["prompt"],
            "invocation": encode_candidate_invocation("", "stop", None, abstained=True),
        }
    )

    record: dict[str, Any] = json.loads(
        await _check_surface(node, benchmark.check_surface_route, payload, "check")
    )

    assert (record["passed"], record["satisfaction"]) == (False, 0.0)
    assert record["feedback"].startswith("The answer failed these requirements: ")


# ── the Candidate's prompt ────────────────────────────────────────────────────────────────


def test_every_prompt_is_the_hand_built_one_with_the_official_text() -> None:
    """INVARIANT: the 541 inputs equal the hand-built `cases.json` byte for byte (the import also
    compared every prompt, instruction list and argument set against the hand-built bundle:
    0 of 541 differ). The Hub rows equal the official file but for key 2785, so the loader's
    output is rendered here from the vendored official rows."""

    rows: list[dict[str, Any]] = official_rows()
    samples: list[Sample] = [
        record_to_sample(row, case_id)
        for case_id, row in enumerate(verify_against_official(rows, rows), start=1)
    ]

    inputs: list[str] = [str(sample.input) for sample in samples]
    assert len(inputs) == 541
    assert hashlib.sha256(json.dumps(inputs).encode()).hexdigest() == _HAND_BUILT_PROMPTS_SHA256


def test_the_one_known_hub_divergence_is_patched_and_any_other_refused() -> None:
    """Key 2785: the Hub prompt asks for "at least one placeholder" while its own arguments
    (and the official prompt) require 3; the official text wins. A prompt differing anywhere
    else means the pin or the official file changed: refused, never patched quietly."""

    official: list[dict[str, Any]] = official_rows()
    hub: list[dict[str, Any]] = [dict(row) for row in official]
    shinto: dict[str, Any] = next(row for row in hub if row["key"] == 2785)
    shinto["prompt"] = shinto["prompt"].replace(
        "at least 3 placeholders", "at least one placeholder"
    )

    patched: list[dict[str, Any]] = verify_against_official(hub, official)
    assert next(row for row in patched if row["key"] == 2785) == _OFFICIAL[2785]

    hub[0] = {**hub[0], "prompt": hub[0]["prompt"] + " "}
    with pytest.raises(ValueError, match=f"key {hub[0]['key']}: the prompt diverges"):
        verify_against_official(hub, official)


def _first_argument_changed(row: dict[str, Any]) -> dict[str, Any]:
    """The row with its first instruction asking for 2 highlights (key 2785: 3 → 2; key 1000:
    an argument its no_comma instruction never had)."""

    return {**row, "kwargs": [{**row["kwargs"][0], "num_highlights": 2}, *row["kwargs"][1:]]}


def _last_instruction_changed(row: dict[str, Any]) -> dict[str, Any]:
    """The row with its last instruction swapped for no_comma (neither key ends with it)."""

    ids: list[str] = row["instruction_id_list"]
    return {**row, "instruction_id_list": [*ids[:-1], "punctuation:no_comma"]}


@pytest.mark.parametrize(
    "change",
    [_first_argument_changed, _last_instruction_changed],
    ids=["kwargs", "instruction-ids"],
)
def test_changed_instructions_are_refused_never_patched(
    change: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    """The ids and arguments ARE the grading rule, so a Hub row whose instructions differ from
    the official file's is a different exam: refused, never patched. Also for key 2785, whose
    prompt IS patched: only its prompt text is a known, reviewed divergence."""

    official: list[dict[str, Any]] = official_rows()
    for key in (1000, 2785):
        hub: list[dict[str, Any]] = [
            change(dict(row)) if row["key"] == key else dict(row) for row in official
        ]
        with pytest.raises(ValueError, match=f"key {key}: instruction ids/kwargs diverge"):
            verify_against_official(hub, official)


def test_a_row_carries_its_instructions_privately_with_null_arguments_dropped() -> None:
    """The Hub pads every argument dict with None keys; passing one through would override a
    checker's default. The arguments ride as a list, so no key turns into "0" through JSON."""

    sample: Sample = record_to_sample(
        {
            "key": 1001,
            "prompt": "No commas, please.",
            "instruction_id_list": ["punctuation:no_comma"],
            "kwargs": [{"num_words": None, "relation": None}],
        },
        7,
    )

    assert (sample.id, sample.input, sample.target) == (7, "No commas, please.", "")
    assert sample.metadata == {"instruction_id_list": ["punctuation:no_comma"], "kwargs": [{}]}


# ── the rows ──────────────────────────────────────────────────────────────────────────────


def test_the_row_keeps_the_hand_built_id_offer_and_declaration() -> None:
    spec = next(row for row in BENCHMARKS if row.key == "ifeval")
    cases = TASK_REPLAY_CASES["ifeval"]
    benchmark = imported_benchmark("ifeval")
    assert benchmark.benchmark.id == "ifeval"  # the hand-built id, kept
    assert benchmark.benchmark.origin == "screamingface"
    assert provenance_gaps(benchmark.benchmark) == []
    assert benchmark.benchmark.declaration.difficulty == "medium"
    # No key, no judge: the checker grades the reply against the instructions in the prompt.
    assert spec.judge is None and spec.scorer_reads_answer_key is False
    assert (cases.case_count, cases.has_answer_key, cases.keep_sample_metadata) == (
        541,
        False,
        True,
    )
    assert cases.nltk_resources == ("punkt", "punkt_tab")
    # The owner's one Draft Feedback offer, with the scorer's own fraction and words.
    assert "ifeval" in OWNER_ALLOWED_DRAFT_FEEDBACK
    assert spec.with_check_surface is True and spec.scorer_draft_feedback is True
    assert benchmark.benchmark.check_surface is not None
    assert spec.candidate_input_envelope is False  # the hand-built input was plain text
    assert spec.named_scores == _NAMED_SCORES
    assert spec.whole_run_metric is not None and spec.whole_run_metric.endswith(":ifeval_accuracy")
    assert spec.whole_run_headline == "prompt_level_strict_accuracy"
