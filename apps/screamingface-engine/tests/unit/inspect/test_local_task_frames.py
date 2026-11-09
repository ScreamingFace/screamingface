# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""FRAMES with the gold articles given, as a LOCAL inspect Task (OME-1481).

What these tests pin, and why:

- the Candidate's prompt: the question's gold articles in link order, then the question, in
  one user message; the gold answer is not in it;
- the Judge's prompt: the paper's Figure 6 auto-rater, word for word as its LaTeX source writes
  it, with the question (never the articles), the reply and the gold answer filled in;
- the decision reader: TRUE scores 1.0, FALSE 0.0, the last decision wins, and a reply with no
  decision is redrawn and then fails the Case by name, never scored;
- the run: a Candidate whose prompt is longer than its context window fails that one Case and
  the run completes (decision 4);
- the loader: a questions file and snapshot that disagree are refused, never joined;
- the rows: `frames_oracle`, origin `screamingface`, the house judge pinned, 822 Cases.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
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
from screamingface_engine.world.connector import _raise_for_status  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.local_tasks.frames.frames import (  # noqa: E402
    JUDGE_SYSTEM,
    judge_user_text,
    parse_decision,
    record_to_sample,
    samples_from,
)
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PreparedCase,
    _write_cases,
    prepared_case,
)
from screamingface_engine_inspect.single_shot import benchmark_aggregate_async  # noqa: E402
from url4.core.errors import ResolutionError  # noqa: E402
from url4.wire.subrequest import decode_subrequest_http, extract_expression_params  # noqa: E402

#: FRAMES row 0, as published: its question and gold answer. The two articles are shortened
#: stand-ins for the snapshot's Harriet Lane and James A. Garfield texts.
_QUESTION: str = (
    "If my future wife has the same first name as the 15th first lady of the United States' "
    "mother and her surname is the same as the second assassinated president's mother's maiden "
    "name, what is my future wife's name? "
)
_GOLD: str = "Jane Ballou"
_ARTICLES: list[tuple[str, str]] = [
    ("Harriet Lane", "Harriet Rebecca Lane Johnston was the acting first lady.\n\n## Early life"),
    ("James A. Garfield", "Garfield's mother was Eliza (Ballou) Garfield."),
]

#: The house judge, as every judged Benchmark here pins it, and its params in wire order.
_JUDGE_ROUTE: str = "/openrouter/openai/gpt-5.4"
_JUDGE_PARAMS: list[tuple[str, str]] = [("web_search", "false"), ("max_tokens", "4096")]

_TRUE: str = 'Explanation: The reply names Jane Ballou.\nDecision: "TRUE"'
_FALSE: str = "Explanation: The reply names Jane Lane.\nDecision: FALSE"


# ── the Candidate's prompt ──────────────────────────────────────────────────────────────────


def test_a_row_renders_its_articles_in_link_order_then_the_question() -> None:
    """INVARIANT: these bytes are Benchmark identity (they sit inside the Case Digest). The
    paper publishes no oracle prompt, so the wording is ours; the gold answer rides the private
    answer key and the question rides the Grading Material for the judge."""

    sample: Sample = record_to_sample(
        0, _QUESTION, _GOLD, _ARTICLES, "Multiple constraints", missing=[]
    )

    assert sample.input == (
        "Answer the question using the Wikipedia articles below.\n"
        "\n"
        "=== Article 1: Harriet Lane ===\n"
        "Harriet Rebecca Lane Johnston was the acting first lady.\n"
        "\n"
        "## Early life\n"
        "\n"
        "=== Article 2: James A. Garfield ===\n"
        "Garfield's mother was Eliza (Ballou) Garfield.\n"
        "\n"
        "Question: " + _QUESTION
    )
    assert _GOLD not in str(sample.input)
    assert (sample.id, sample.target) == (0, _GOLD)
    assert sample.metadata == {
        "question": _QUESTION,
        "reasoning_types": "Multiple constraints",
        "missing_articles": [],
    }


# ── the Judge's prompt and its decision ─────────────────────────────────────────────────────


def test_the_judge_prompt_is_figure_6_word_for_word() -> None:
    """Transcribed from the paper's LaTeX source (`auto_rate_prompt.tex`, arXiv 2409.12941v1):
    its line breaks, its curly apostrophe and its en dash; the paper's ``<<question>>``,
    ``<<LLM_response>>`` and ``<<ground_truth_answer>>`` slots filled in. The judge sees the
    question alone, never the articles: the paper's rater compares answers, not evidence."""

    assert JUDGE_SYSTEM == "You are a helpful assistant."
    assert judge_user_text("Q?", "my reply", "gold") == (
        "===Task===\n"
        "\n"
        "I need your help in evaluating an answer provided by an LLM against a ground truth "
        "answer. Your task is to determine if the ground truth answer is present in the LLM’s "
        "response. Please analyze the provided data and make a decision.\n"
        "===Instructions===\n"
        '1. Carefully compare the "Predicted Answer" with the "Ground Truth Answer".\n'
        "2. Consider the substance of the answers – look for equivalent information or "
        "correct answers. Do not focus on exact wording unless the exact wording is crucial to "
        "the meaning.\n"
        "3. Your final decision should be based on whether the meaning and the vital facts of "
        'the "Ground Truth Answer" are present in the "Predicted Answer:"\n'
        "\n"
        "===Input Data===\n"
        "- Question: Q?\n"
        "- Predicted Answer: my reply\n"
        "- Ground Truth Answer: gold\n"
        "\n"
        "===Output Format===\n"
        "Provide your final evaluation in the following format:\n"
        '"Explanation:" (How you made the decision?)\n'
        '"Decision:" ("TRUE" or "FALSE" )\n'
        "\n"
        "Please proceed with the evaluation."
    )


def test_braces_in_a_reply_reach_the_judge_as_written() -> None:
    """WHY: a reply or a question can hold ``{`` and ``}`` (code, sets); the template is
    filled once, so the judge reads them as written instead of the fill failing."""

    assert "- Predicted Answer: {x} and {{y}}\n" in judge_user_text("Q?", "{x} and {{y}}", "g")


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('Explanation: It matches.\nDecision: "TRUE"', (True, "It matches.")),
        ("**Explanation:** Wrong year.\n**Decision:** FALSE", (False, "Wrong year.")),
        ('"Explanation:" Same person.\n"Decision:" ("TRUE")', (True, "Same person.")),
        ("Decision: true", (True, "")),
        # WHY the last decision wins: a judge that corrects itself means the correction.
        (
            "Explanation: First TRUE, then no.\nDecision: TRUE\nWait.\nDecision: FALSE",
            (False, "First TRUE, then no."),
        ),
    ],
)
def test_the_decision_is_read_from_the_judges_last_decision_line(
    reply: str, expected: tuple[bool, str]
) -> None:
    assert parse_decision(reply) == expected


@pytest.mark.parametrize("reply", ["", "I think it is right.", "Decision: maybe", "TRUE"])
def test_a_reply_with_no_decision_line_has_no_verdict(reply: str) -> None:
    """None, never False: the redraw helper asks again, and after its budget the Case fails as
    ``judge_reply_invalid``. A bare TRUE without the ``Decision:`` label is not read, so a word
    in the explanation can never become the verdict."""

    assert parse_decision(reply) is None


# ── grading through the real per-Case hook ──────────────────────────────────────────────────


class _ScriptedJudge:
    """A fake node fetch standing in for the gateway judge: answers each Case from its script
    by the Ground Truth Answer it is shown, and keeps every call's (path, params, messages).

    It simulates the judge's replies only; whether a real judge would answer so is not what
    these tests prove."""

    def __init__(self) -> None:
        self.scripts: dict[str, list[str]] = {}
        self.calls: list[tuple[str, list[tuple[str, str]], list[dict[str, str]]]] = []

    async def __call__(self, target: str) -> str:
        path, _, query = target.partition("?")
        params, q = extract_expression_params(query)
        assert q is not None
        context, _ = decode_subrequest_http(q)
        messages: list[dict[str, str]] = json.loads(context)["messages"]
        self.calls.append((path, list(params.items()), messages))
        gold: str = messages[1]["content"].split("- Ground Truth Answer: ")[1].split("\n")[0]
        return self.scripts[gold].pop(0)


@pytest.fixture
def judge() -> Iterator[_ScriptedJudge]:
    """The scripted judge, bound as frames_oracle's judge with its pinned params, inside a
    run's request scope (a redraw rebinds that scope to leave the cache)."""

    scripted: _ScriptedJudge = _ScriptedJudge()
    spec = imported_benchmark("frames_oracle").judge
    assert spec is not None
    transport = JudgeTransport(
        fetch=scripted,
        params=spec.params,
        benchmark_id="frames_oracle",
        seed_per_pass=spec.seed_per_pass,
    )
    with request_scope(RequestScope(origin="run")), bound_judge_transport(transport):
        yield scripted


def _material(case_id: int, gold: str) -> dict[str, Any]:
    """One Case's Grading Material as the real row prepares it, after its JSON round trip."""

    sample: Sample = record_to_sample(case_id, _QUESTION, gold, _ARTICLES, "Numerical", missing=[])
    case: PreparedCase = prepared_case(
        sample, case_id, str(sample.input), TASK_REPLAY_CASES["frames_oracle"]
    )
    return json.loads(json.dumps(case["grading_material"]))


async def _grade(case_id: int, gold: str, reply: str) -> CaseGradeOutcome:
    """Grade one Case through frames_oracle's real per-Case grading hook."""

    hook = imported_benchmark("frames_oracle").aggregation().grade_case
    return await hook(
        GradeRequest(
            case_id=case_id,
            input=TextPayload(text="the articles, then the question"),
            answer=TextPayload(text=reply),
            row={"case": {"status": "answered"}},
            material=_material(case_id, gold),
        )
    )


@pytest.mark.asyncio
async def test_true_scores_one_and_false_scores_zero(judge: _ScriptedJudge) -> None:
    judge.scripts = {"Jane Ballou": [_TRUE], "Jane Lane": [_FALSE]}

    right: CaseGradeOutcome = await _grade(1, "Jane Ballou", "Your future wife is Jane Ballou.")
    wrong: CaseGradeOutcome = await _grade(2, "Jane Lane", "Your future wife is Jane Ballou.")

    assert (right.score, right.failure_code) == (1.0, None)
    assert (wrong.score, wrong.failure_code) == (0.0, None)


@pytest.mark.asyncio
async def test_a_judge_that_never_decides_fails_the_case_by_name(judge: _ScriptedJudge) -> None:
    """Three draws (the first ask and two redraws), none with a decision: the Case fails as
    ``judge_reply_invalid`` and keeps no score, so it leaves Coverage instead of reading as a
    wrong answer."""

    judge.scripts = {"Jane Ballou": ["Hmm.", "Let me think.", "Hard to say."]}

    outcome: CaseGradeOutcome = await _grade(1, "Jane Ballou", "Jane Ballou")

    assert (outcome.score, outcome.failure_code) == (None, "judge_reply_invalid")
    assert len(judge.calls) == 3


@pytest.mark.asyncio
async def test_each_judge_call_carries_figure_6_the_reply_and_the_pinned_params(
    judge: _ScriptedJudge,
) -> None:
    """The house judge's route and pinned params in order, no seed (one judgement per Case);
    the system message and Figure 6 as the paper writes them, with the Candidate's whole reply
    as the Predicted Answer."""

    judge.scripts = {"Jane Ballou": [_TRUE]}
    reply: str = "Harriet Lane's mother was Jane; Garfield's was Eliza Ballou. Jane Ballou."

    await _grade(1, "Jane Ballou", reply)

    [(path, params, messages)] = judge.calls
    assert path == _JUDGE_ROUTE
    assert params == _JUDGE_PARAMS
    assert messages == [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": judge_user_text(_QUESTION, reply, "Jane Ballou")},
    ]


def _collected_failure(error: ResolutionError) -> dict[str, object]:
    """The row a run collects for a Case whose Candidate call raised: the error's own code and
    retryability, as url4's collect writes it (the shape `test_ifeval_provider_failure_stage`
    pins through the real candidate boundary)."""

    return {
        "error": {
            "kind": "CandidateExecutionError",
            "message": str(error),
            "code": error.code,
            "retryable": not error.permanent,
        }
    }


@pytest.mark.asyncio
async def test_an_over_window_prompt_fails_its_case_counts_zero_and_the_run_completes(
    tmp_path: Path, judge: _ScriptedJudge
) -> None:
    """Decision 4: a prompt longer than the Candidate's window comes back from the provider as
    a 400, which the gateway connector raises as ``aigateway_http_400``. That one Case fails
    and shows in Coverage (2 of 3 graded). frames_oracle declares ``withhold`` (OME-1642), so
    the failed Case counts 0 in the score: (1 + 0 + 0) / 3, not the graded pair's 0.5."""

    # Keyed by gold answer, not call order: the aggregate grades Cases concurrently.
    judge.scripts = {"Jane Ballou": [_TRUE], "Eliza Ballou": [_FALSE]}
    golds: dict[int, str] = {1: "Jane Ballou", 2: "Harriet Lane", 3: "Eliza Ballou"}
    prepared: list[PreparedCase] = [
        {
            "case": {"id": case_id, "case_id": str(case_id), "input": "articles and question"},
            "grading_material": _material(case_id, gold),
        }
        for case_id, gold in golds.items()
    ]
    _write_cases(prepared, tmp_path)
    with pytest.raises(ResolutionError) as over_window:
        _raise_for_status(httpx.Response(400))
    rows: str = json.dumps(
        [_row(1, "Jane Ballou"), _collected_failure(over_window.value), _row(3, "Jane Lane")]
    )

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("frames_oracle"), rows, tmp_path, case_ids=(1, 2, 3)
    )

    assert [case["status"] for case in result["cases"]] == ["scored", "failed", "scored"]
    assert [failure["code"] for failure in result["cases"][1]["failures"]] == ["aigateway_http_400"]
    assert result["coverage"] == round(2 / 3, 4)
    assert result["score"] == round(1 / 3, 4)


# ── the loader's join ───────────────────────────────────────────────────────────────────────


def _files(
    *, prompt_sha256: str | None = None, keys: list[str] | None = None
) -> tuple[bytes, bytes, bytes]:
    """A one-row questions file, its snapshot question row and two articles, consistent unless
    a test overrides the snapshot's prompt sha256 or article keys."""

    header: str = "\tPrompt\tAnswer\treasoning_types\n"
    questions: bytes = (header + f"0\t{_QUESTION}\t{_GOLD}\tMultiple constraints\n").encode()
    snapshot_row: dict[str, Any] = {
        "index": 0,
        "prompt_sha256": prompt_sha256 or hashlib.sha256(_QUESTION.encode()).hexdigest(),
        "articles": keys or ["en.wikipedia.org/1", "en.wikipedia.org/2"],
        "missing_articles": [],
    }
    articles: bytes = "".join(
        json.dumps({"key": f"en.wikipedia.org/{n}", "title": title, "text": text}) + "\n"
        for n, (title, text) in enumerate(_ARTICLES, start=1)
    ).encode()
    return questions, (json.dumps(snapshot_row) + "\n").encode(), articles


def test_the_loader_joins_each_question_to_its_articles_by_key() -> None:
    [sample] = samples_from(*_files())
    assert (
        sample.input
        == record_to_sample(
            0, _QUESTION, _GOLD, _ARTICLES, "Multiple constraints", missing=[]
        ).input
    )


def test_a_snapshot_written_for_another_question_is_refused() -> None:
    """WHY: the snapshot is joined by row index; a questions file the authors edited would pair
    one question with another's articles, so the prompt's sha256 must match, row by row."""

    with pytest.raises(ValueError, match="row 0: the snapshot was built for another prompt"):
        samples_from(*_files(prompt_sha256="0" * 64))


def test_an_article_missing_from_the_snapshot_is_refused() -> None:
    with pytest.raises(ValueError, match="row 0: article en.wikipedia.org/9 is not in"):
        samples_from(*_files(keys=["en.wikipedia.org/1", "en.wikipedia.org/9"]))


# ── the rows ────────────────────────────────────────────────────────────────────────────────


def test_the_row_pins_the_house_judge_and_drops_the_two_unanswerable_questions() -> None:
    """Decisions 9 and 10: questions 141 (its only source was deleted) and 77 (its answer is
    in a table a deleted template drew) are left out by name; 822 Cases remain."""

    spec = next(row for row in BENCHMARKS if row.key == "frames_oracle")
    cases = TASK_REPLAY_CASES["frames_oracle"]
    benchmark = imported_benchmark("frames_oracle")
    assert benchmark.benchmark.origin == "screamingface"
    assert provenance_gaps(benchmark.benchmark) == []
    assert spec.judge is not None and spec.judge.model == _JUDGE_ROUTE.removeprefix("/")
    assert list(spec.judge.params) == _JUDGE_PARAMS
    assert spec.judge.seed_per_pass is False
    assert spec.scorer_kwargs == {"judge_model": "screamingface" + _JUDGE_ROUTE}
    assert spec.with_check_surface is False and spec.retrieval_policy is None
    assert (cases.case_count, cases.has_answer_key, cases.keep_sample_metadata) == (822, True, True)
    assert cases.excluded_sample_ids == ("77", "141")
