# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""GDPval-text as a LOCAL inspect Task (OME-1527) — the hand-built folder, moved.

What these tests pin, and why:

- conservation: five canned Cases, each rubric line answered by a scripted judge, grade
  exactly as the hand-built grader graded them — the same Case scores, the same met / not-met
  per line, the same failed Case, the same headline. The literals were produced by driving the
  hand-built routes (judge requests → verdict, redrawn as its `;retry=2` would → rubric and
  case evaluation → its rubric grade hook → the shared mean scorer) on these replies at
  2b3d477fe, before the folder was deleted, so "same exam, same score" is a test;
- the judge's wire: each call sends the hand-built grader prompt as one user message, to the
  same route with the same pinned params (one prompt pinned as a literal);
- the Candidate's prompt bytes: a synthetic row renders to a pinned literal, the hand-built
  `case_input` byte for byte (all 102 real Cases were compared at import: 0 differ, and 0 of
  the 102 filtered rubrics);
- the row: id `gdpval-text`, origin `screamingface`, the judge pinned, no Draft Feedback.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.dataset import Sample  # noqa: E402
from test_whole_run_metric import _row  # noqa: E402

from screamingface_engine.benchmarks.provenance import provenance_gaps  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine.request_scope import RequestScope, request_scope  # noqa: E402
from screamingface_engine_inspect import benchmarks, single_shot  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    BenchmarkSpec,
    _task_replay_pins,
    imported_benchmark,
)
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.local_tasks.gdpval.gdpval import record_to_sample  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PreparedCase,
    _write_cases,
    prepared_case,
)
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    ImportedBenchmark,
    _cases,
    benchmark_aggregate_async,
)
from url4.wire.subrequest import decode_subrequest_http, extract_expression_params  # noqa: E402

#: Five Cases: (request, submission, [(points, criterion, the judge's replies in draw order)]).
#: Each criterion carries a `crit-<case>-<line>` token so the scripted judge can tell which
#: line it was asked about. They cover fenced, prose-prefixed and bare JSON; a prose reply and
#: a string "true", each redrawn once; a penalty that bites (Case 1) and one that drives the
#: score below zero (Case 3); and a line that never parses — a blank, prose, then `{}` — which
#: fails its Case (Case 5).
_CASES: list[tuple[str, str, list[tuple[int, str, list[str]]]]] = [
    (
        "Write a competitor brief for case-1.",
        "Brief one.",
        [
            (
                5,
                "crit-1-1 names three competitors",
                ['```json\n{"explanation": "Names three.", "criteria_met": true}\n```'],
            ),
            (
                3,
                "crit-1-2 recommends a timeline",
                ['Verdict below.\n{"explanation": "No timeline.", "criteria_met": false}'],
            ),
            (
                -3,
                "crit-1-3 fabricates a statistic",
                ['{"explanation": "Invents a number.", "criteria_met": true}'],
            ),
        ],
    ),
    (
        "Draft a memo for case-2.",
        "Memo two.",
        [
            (
                2,
                "crit-2-1 states the decision",
                [
                    "I believe it is met.",
                    '{"criteria_met": true}',
                ],
            ),
            (
                2,
                "crit-2-2 cites the policy",
                [
                    '{"explanation": "Says true.", "criteria_met": "true"}',
                    '{"explanation": "Missing.", "criteria_met": false}',
                ],
            ),
            (-1, "crit-2-3 uses jargon", ['{"explanation": "Clean.", "criteria_met": false}']),
        ],
    ),
    (
        "Answer the client for case-3.",
        "Reply three.",
        [
            (2, "crit-3-1 answers the question", ['{"criteria_met": false}']),
            (-5, "crit-3-2 gives unsafe advice", ['{"criteria_met": true}']),
        ],
    ),
    (
        "Summarise the file for case-4.",
        "Summary four.",
        [
            (1, "crit-4-1 is concise", ['{"criteria_met": true}']),
            (1, "crit-4-2 is accurate", ['{"criteria_met": true}']),
        ],
    ),
    (
        "Plan the launch for case-5.",
        "Plan five.",
        [
            (3, "crit-5-1 lists milestones", ["", "no idea", "```json\n{}\n```"]),
            (1, "crit-5-2 names an owner", ['{"criteria_met": true}']),
        ],
    ),
]

#: What the hand-built grader recorded for each Case above: its score and each line's MET
#: (True) or UNMET (False); None for Case 5, which it failed (`judge_reply_invalid` on line 1
#: after its two retries). Captured from `benchmarks/gdpval` at 2b3d477fe before its deletion.
_HAND_BUILT: list[tuple[float, list[bool]] | None] = [
    (0.25, [True, False, True]),
    (0.5, [True, False, False]),
    (-2.5, [False, True]),
    (1.0, [True, True]),
    None,
]

#: The hand-built mean scorer's headline over the four graded Cases:
#: (0.25 + 0.5 − 2.5 + 1.0) / 4 = −0.1875 — unclamped, the failed Case left out.
_HAND_BUILT_HEADLINE: float = -0.1875

#: The hand-built judge route and its JUDGE_PARAMS, in wire order.
_JUDGE_ROUTE: str = "/openrouter/google/gemini-3.1-pro-preview"
_JUDGE_PARAMS: dict[str, str] = {
    "web_search": "false",
    "temperature": "0.2",
    "reasoning_effort": "low",
    "max_tokens": "8192",
}

_LINE_TOKEN: re.Pattern[str] = re.compile(r"crit-\d+-\d+")


class _ScriptedJudge:
    """A fake node fetch standing in for the gateway judge: answers each rubric line from its
    script, in draw order, and keeps every call's decoded (path, params, context, intent).

    WHY keyed by line, not by call order: the aggregate grades several Cases at once, so calls
    from different Cases interleave. It simulates the judge's replies only; whether a real
    judge would answer so is not what these tests prove."""

    def __init__(self) -> None:
        self.scripts: dict[str, list[str]] = {
            _LINE_TOKEN.findall(criterion)[0]: list(replies)
            for _, _, rubric in _CASES
            for _, criterion, replies in rubric
        }
        self.calls: list[tuple[str, dict[str, str], str, str]] = []

    async def __call__(self, target: str) -> str:
        path, _, query = target.partition("?")
        params, q = extract_expression_params(query)
        assert q is not None
        context, intent = decode_subrequest_http(q)
        self.calls.append((path, dict(params), context, intent))
        prompt: str = json.loads(context)["messages"][0]["content"]
        token: str = _LINE_TOKEN.findall(prompt.split("<criterion>")[1])[0]
        return self.scripts[token].pop(0)


@pytest.fixture
def judge() -> Iterator[_ScriptedJudge]:
    """The scripted judge, bound as the run's judge with the row's pinned params, inside a
    run's request scope (a redraw rebinds that scope to leave the gateway cache)."""

    scripted: _ScriptedJudge = _ScriptedJudge()
    spec = imported_benchmark("gdpval-text").judge
    assert spec is not None
    transport = JudgeTransport(fetch=scripted, params=spec.params, benchmark_id="gdpval-text")
    with request_scope(RequestScope(origin="run")), bound_judge_transport(transport):
        yield scripted


def _material(index: int) -> dict[str, Any]:
    """Case ``index``'s Grading Material as the real row prepares it, after its JSON round trip."""

    request, _, rubric = _CASES[index - 1]
    row: dict[str, Any] = {
        "task_id": f"task-{index}",
        "prompt": request,
        "reference_files": [],
        "rubric_json": json.dumps(
            [{"criterion": criterion, "score": points} for points, criterion, _ in rubric]
        ),
    }
    sample: Sample = record_to_sample(row, reader=_no_references)
    case: PreparedCase = prepared_case(
        sample, index, str(sample.input), TASK_REPLAY_CASES["gdpval-text"]
    )
    return json.loads(json.dumps(case["grading_material"]))


def _no_references(task_id: str, file_name: str) -> str:
    """A reference reader for rows that list no reference files; it is never called."""

    raise AssertionError(f"{task_id} has no reference {file_name}")


# ── conservation: the hand-built grader's numbers, pinned as literals ─────────────────────


@pytest.mark.asyncio
async def test_each_case_is_graded_as_the_hand_built_grader_graded_it(
    judge: _ScriptedJudge,
) -> None:
    """Score, per-line verdict and failure, Case by Case. Each line's verdict, points and the
    judge's words ride the one Check's evidence (the thinner Report, owner decision 1)."""

    hook = imported_benchmark("gdpval-text").aggregation().grade_case
    for index, ((request, submission, rubric), expected) in enumerate(
        zip(_CASES, _HAND_BUILT, strict=True), start=1
    ):
        outcome: CaseGradeOutcome = await hook(
            GradeRequest(
                case_id=index,
                input=TextPayload(text=request),
                answer=TextPayload(text=submission),
                row={"case": {"status": "answered"}},
                material=_material(index),
            )
        )
        if expected is None:
            # The hand-built grader failed it too; the plugin names the judge as the cause.
            assert outcome.failure_code == "judge_reply_invalid", outcome.checks
            assert outcome.score is None
            continue
        score, met = expected
        evidence: dict[str, Any] = outcome.checks[0]["evidence"][0]["metadata"]
        assert outcome.failure_code is None, outcome.checks
        assert outcome.score == score, index
        assert [item["met"] for item in evidence["items"]] == met
        assert [item["points"] for item in evidence["items"]] == [p for p, _, _ in rubric]
        assert [item["rubric_id"] for item in evidence["items"]] == list(range(1, len(met) + 1))


@pytest.mark.asyncio
async def test_the_run_headline_is_the_hand_built_mean(
    tmp_path: Path, judge: _ScriptedJudge
) -> None:
    """The headline guarantee: the same replies score −0.1875 here and in the hand-built
    Benchmark — a plain, unclamped mean over the four graded Cases; the Case whose judge never
    gave a verdict is left out of the mean and counted against coverage, never scored 0."""

    prepared: list[PreparedCase] = [
        {
            "case": {"id": index, "case_id": str(index), "input": request},
            "grading_material": _material(index),
        }
        for index, (request, _, _) in enumerate(_CASES, start=1)
    ]
    _write_cases(prepared, tmp_path)
    rows: str = json.dumps(
        [_row(index, submission) for index, (_, submission, _) in enumerate(_CASES, start=1)]
    )

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("gdpval-text"), rows, tmp_path, case_ids=(1, 2, 3, 4, 5)
    )

    assert result["score"] == _HAND_BUILT_HEADLINE
    assert result["metrics"]["scored_cases"] == 4
    statuses: list[str] = [case["status"] for case in result["cases"]]
    assert statuses.count("failed") == 1
    codes: list[str] = [failure["code"] for case in result["cases"] for failure in case["failures"]]
    assert codes == ["judge_reply_invalid"]
    redraws: list[int] = [
        case["grade"]["checks"][0]["evidence"][0]["metadata"]["judge_redraws"]
        for case in result["cases"]
        if case["status"] != "failed"
    ]
    assert redraws == [0, 2, 0, 0]


# ── the judge's wire ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_judge_call_is_the_hand_built_one(judge: _ScriptedJudge) -> None:
    """Same route, same pinned params in the same order, one user message, empty intent — and
    the grader prompt's bytes, pinned below for Case 3's penalty line (the hand-built route
    rendered exactly this text for it)."""

    hook = imported_benchmark("gdpval-text").aggregation().grade_case
    request, submission, _ = _CASES[2]
    await hook(
        GradeRequest(
            case_id=3,
            input=TextPayload(text=request),
            answer=TextPayload(text=submission),
            row={"case": {"status": "answered"}},
            material=_material(3),
        )
    )

    assert len(judge.calls) == 2
    for path, params, _, intent in judge.calls:
        assert (path, params, intent) == (_JUDGE_ROUTE, _JUDGE_PARAMS, "")
    assert list(judge.calls[0][1]) == list(_JUDGE_PARAMS)
    messages: list[dict[str, str]] = json.loads(judge.calls[1][2])["messages"]
    assert messages == [
        {
            "role": "user",
            "content": (
                "You are grading one submitted piece of professional work against ONE\n"
                "criterion from an expert-written rubric.\n"
                "\n"
                "The work was requested as follows:\n"
                "\n"
                "<request>\n"
                "Answer the client for case-3.\n"
                "</request>\n"
                "\n"
                "The submission:\n"
                "\n"
                "<submission>\n"
                "Reply three.\n"
                "</submission>\n"
                "\n"
                "The single criterion to judge:\n"
                "\n"
                "<criterion>\n"
                "[-5] crit-3-2 gives unsafe advice\n"
                "</criterion>\n"
                "\n"
                "Judge ONLY this criterion. Ignore every other quality of the submission, "
                "including whether it\n"
                "would satisfy criteria you have not been shown.\n"
                "\n"
                "The submission is plain text. Judge its CONTENT: if the criterion asks for "
                "something that would\n"
                "normally live in a formatted document — a section, a table, a named field — "
                "treat the content\n"
                "being present and clearly identifiable as satisfying it.\n"
                "\n"
                'A conditional criterion ("If X is addressed/discussed, then Y...") is met '
                "only if the\n"
                "submission engages X and satisfies Y, or the request genuinely makes X "
                "irrelevant. Silence\n"
                "about a condition the request's facts raise does NOT satisfy the criterion.\n"
                "\n"
                "Reply with JSON only, no prose outside it:\n"
                "\n"
                '{"explanation": "<one or two sentences>", "criteria_met": true or false}\n'
            ),
        }
    ]


# ── the Candidate's prompt bytes ──────────────────────────────────────────────────────────


def test_a_row_renders_to_the_pinned_prompt_bytes_and_its_filtered_rubric() -> None:
    """INVARIANT: these bytes are Benchmark identity (they sit inside the Case Digest) and
    equal the hand-built `case_input`: the stripped request, then per reference a header line
    and its text, joined by blank lines. The rubric drops its container criterion and numbers
    the rest from 1."""

    texts: dict[str, str] = {"a.pdf": "Population table.", "b.docx": "Prior report."}
    sample: Sample = record_to_sample(
        {
            "task_id": "t-1",
            "prompt": "  Draft the memo.\n",
            "reference_files": ["a.pdf", "b.docx"],
            "rubric_json": json.dumps(
                [
                    {"criterion": "The memo is provided as a Word document.", "score": 1},
                    {"criterion": "States the deadline.", "score": 2},
                    {"criterion": "Invents a figure.", "score": -4},
                ]
            ),
        },
        reader=lambda _task, name: texts[name],
    )

    assert sample.input == (
        "Draft the memo.\n"
        "\n"
        "--- Reference file: a.pdf ---\n"
        "\n"
        "Population table.\n"
        "\n"
        "--- Reference file: b.docx ---\n"
        "\n"
        "Prior report."
    )
    assert sample.target == ""
    assert sample.metadata == {
        "task_id": "t-1",
        "rubric": [
            {"rubric_id": 1, "criterion": "States the deadline.", "points": 2},
            {"rubric_id": 2, "criterion": "Invents a figure.", "points": -4},
        ],
    }


# ── the row ───────────────────────────────────────────────────────────────────────────────


def test_the_row_keeps_the_hand_built_id_judge_and_declaration() -> None:
    spec = next(row for row in BENCHMARKS if row.key == "gdpval-text")
    cases = TASK_REPLAY_CASES["gdpval-text"]
    benchmark = imported_benchmark("gdpval-text")
    assert benchmark.benchmark.id == "gdpval-text"  # the hand-built id, kept
    assert benchmark.benchmark.origin == "screamingface"
    assert provenance_gaps(benchmark.benchmark) == []
    assert spec.judge is not None and spec.judge.model == _JUDGE_ROUTE.removeprefix("/")
    assert dict(spec.judge.params) == _JUDGE_PARAMS
    assert spec.with_check_surface is False and spec.whole_run_metric is None
    assert (cases.case_count, cases.has_answer_key, cases.keep_sample_metadata) == (
        102,
        False,
        True,
    )
    source = [pin for pin in _task_replay_pins(cases) if pin.startswith("task_source=")]
    assert len(source) == 1


# --- the Candidate gets the hand-built input envelope (owner decision 3, OME-1527) ---------


def test_the_candidate_is_served_the_hand_built_envelope_while_cases_json_stays_plain(
    tmp_path: Path,
) -> None:
    """A Fusion synthesizer is pasted ``$input`` raw, so the hand-built envelope must reach
    the Candidate byte for byte or the recorded e2e golden misses every synthesizer call;
    the scorer reads cases.json, which must stay plain or the judge's prompt moves."""

    plain: str = "Rédige la note.\n\nREFERENCE FILE: brief.pdf"
    written: str = json.dumps([{"id": 1, "case_id": 1, "input": plain}])
    (tmp_path / "cases.json").write_text(written, encoding="utf-8")

    served: list[dict[str, Any]] = json.loads(_cases(tmp_path, envelope=True)())

    # The literal is hand-built gdpval's `case_input` form: compact, non-ASCII kept as is.
    assert served[0]["input"] == (
        '{"schema":"screamingface.candidate-input.v1","messages":[{"role":"user",'
        '"content":"Rédige la note.\\n\\nREFERENCE FILE: brief.pdf"}]}'
    )
    assert (tmp_path / "cases.json").read_text(encoding="utf-8") == written
    assert _cases(tmp_path)() == written, "a row without the flag is served cases.json as is"
    assert imported_benchmark("gdpval-text").candidate_input_envelope is True


def test_the_envelope_is_benchmark_identity_and_refuses_a_check_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The envelope changes what a synthesizer reads, so it moves the revision; and the
    check surface finds its Case by the exact text the Candidate was given, which the
    envelope no longer matches, so the two can't be declared together."""

    # Stand-in: gsm8k's real row, simulating any row that sets the flag; it proves the
    # factory's rules, not gdpval-text's own Task.
    gsm8k: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == "gsm8k")

    def assembled(spec: BenchmarkSpec) -> ImportedBenchmark:
        """Assemble one row through the real table path, with the caches emptied."""

        monkeypatch.setattr(benchmarks, "BENCHMARKS", (spec,))
        monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
        monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
        return imported_benchmark(spec.key)

    plain: str = assembled(replace(gsm8k, with_check_surface=False)).benchmark.revision
    enveloped: str = assembled(
        replace(gsm8k, with_check_surface=False, candidate_input_envelope=True)
    ).benchmark.revision
    assert enveloped != plain
    with pytest.raises(ValueError, match="cannot declare a check surface"):
        assembled(replace(gsm8k, with_check_surface=True, candidate_input_envelope=True))
