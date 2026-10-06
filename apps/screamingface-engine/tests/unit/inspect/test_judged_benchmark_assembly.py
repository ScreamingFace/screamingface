# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Judged-benchmark assembly — the judge is benchmark identity, and its only exit is the node.

A judged benchmark is not just its dataset: swap the judge model, its prompt, or
its pinned params and a candidate sits a DIFFERENT benchmark. This suite pins that the
judge declaration (``JudgeSpec``) rides the revision hash, that every misdeclaration
refuses at assembly (CI), never at grade time, and that the aggregate binds the
judge transport so the scorer's judge call leaves through the node's model route.

INVARIANT: the 10 published string-match benchmarks' revisions must NOT move — judge
pins exist only when a judge is declared, and scorer kwargs stay outside the hash
for undeclared benchmarks exactly as they were before OME-1240.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine.benchmarks.contract import (  # noqa: E402
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload  # noqa: E402
from screamingface_engine_inspect import benchmarks, single_shot  # noqa: E402
from screamingface_engine_inspect.benchmarks import BenchmarkSpec  # noqa: E402
from screamingface_engine_inspect.envelopes import (  # noqa: E402
    CHECK_SCHEMA,
    build_case_grade,
)
from screamingface_engine_inspect.single_shot import JudgeSpec  # noqa: E402
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Request, Url4Node  # noqa: E402


def _judged_spec(**overrides: Any) -> BenchmarkSpec:
    """One minimal judged row — a model_graded_qa benchmark pinned to gateway judge-4."""

    values: dict[str, Any] = {
        "key": "gsm8k",  # reuses the real cases row; the benchmark caches are patched
        "title": "Judged Test Benchmark",
        "description": "test",
        "focus": "test",
        "dataset_url": "https://example.test/ds",
        "difficulty": "easy",
        "scorer": "inspect_ai.scorer:model_graded_qa",
        "scorer_kwargs": {"model": "screamingface/judge-4"},
        "judge": JudgeSpec(model="judge-4", params=(("temperature", "0"),)),
        "with_check_surface": False,
    }
    values.update(overrides)
    return BenchmarkSpec(**values)


def _assembled(spec: BenchmarkSpec, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Assemble one row through the REAL catalogue path, on fresh benchmark caches."""

    monkeypatch.setattr(benchmarks, "BENCHMARKS", (spec,))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    return benchmarks.imported_benchmark(spec.key)


def _revision(spec: BenchmarkSpec, monkeypatch: pytest.MonkeyPatch) -> str:
    return str(_assembled(spec, monkeypatch).benchmark.revision)


# ── the judge is benchmark identity ───────────────────────────────────────────────


def test_a_judged_benchmarks_revision_moves_with_the_judge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: swapping the judge is a different benchmark — the revision must move."""

    base = _revision(_judged_spec(), monkeypatch)
    other = _revision(
        _judged_spec(
            judge=JudgeSpec(model="judge-5", params=(("temperature", "0"),)),
            scorer_kwargs={"model": "screamingface/judge-5"},
        ),
        monkeypatch,
    )
    assert base != other


def test_a_judged_benchmarks_revision_moves_with_the_judge_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The judge's grading prompt (template/instructions kwargs) is benchmark identity."""

    base = _revision(_judged_spec(), monkeypatch)
    other = _revision(
        _judged_spec(
            scorer_kwargs={
                "model": "screamingface/judge-4",
                "template": "Grade strictly: {question} {answer} {criterion} {instructions}",
            }
        ),
        monkeypatch,
    )
    assert base != other


def test_a_judged_benchmarks_revision_moves_with_the_judge_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _revision(_judged_spec(), monkeypatch)
    other = _revision(
        _judged_spec(judge=JudgeSpec(model="judge-4", params=(("temperature", "1"),))),
        monkeypatch,
    )
    assert base != other


def test_the_same_judged_spec_assembles_to_the_same_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _revision(_judged_spec(), monkeypatch) == _revision(_judged_spec(), monkeypatch)


def test_a_string_match_benchmarks_kwargs_stay_outside_the_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT (frozen published revisions): for an UNDECLARED benchmark, scorer kwargs
    were never benchmark identity before OME-1240 and must not become it now — the 10
    published benchmarks keep their revisions byte-identical."""

    plain = _judged_spec(
        scorer="inspect_ai.scorer:match",
        scorer_kwargs={"numeric": True},
        judge=None,
    )
    reworded = _judged_spec(
        scorer="inspect_ai.scorer:match",
        scorer_kwargs={},
        judge=None,
    )
    assert _revision(plain, monkeypatch) == _revision(reworded, monkeypatch)


# ── misdeclarations refuse at assembly, never at grade time ──────────────────


def test_an_undeclared_gateway_judge_kwarg_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row whose scorer calls the gateway without a JudgeSpec would grade with an
    unpinned judge — silently outside benchmark identity. Refuse at assembly (CI)."""

    spec = _judged_spec(judge=None)
    with pytest.raises(ValueError, match="judge"):
        _assembled(spec, monkeypatch)


def test_a_model_graded_scorer_without_a_judge_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model_graded_* with no explicit model rides inspect's grader ROLE — a path
    this plugin does not support yet; it must refuse by name, not fail every Case."""

    spec = _judged_spec(judge=None, scorer_kwargs={})
    with pytest.raises(ValueError, match="judge"):
        _assembled(spec, monkeypatch)


def test_a_judge_model_missing_from_the_scorer_kwargs_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The declaration and the scorer must call the SAME judge — a typo between the
    two would pin one model and call another."""

    spec = _judged_spec(scorer_kwargs={"model": "screamingface/judge-5"})
    with pytest.raises(ValueError, match="judge-4"):
        _assembled(spec, monkeypatch)


def test_an_unresolved_todo_judge_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The importer emits judge model TODO — an unreviewed row must fail CI by name."""

    spec = _judged_spec(
        judge=JudgeSpec(model="TODO"),
        scorer_kwargs={"model": "screamingface/TODO"},
    )
    with pytest.raises(ValueError, match="TODO"):
        _assembled(spec, monkeypatch)


def test_a_judged_benchmark_with_a_check_surface_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A judged mid-run check spends judge tokens per attempt; until the check-cost
    knob exists (OME-1116) a judged benchmark must not advertise a draft-feedback offer."""

    spec = _judged_spec(with_check_surface=True)
    with pytest.raises(ValueError, match="check"):
        _assembled(spec, monkeypatch)


# ── the aggregate binds the transport: the judge call exits via the node ─────


class _JudgeEndpoint:
    """A fake gateway model route: records requests, replies with a fixed grade."""

    def __init__(self, reply: str = "The answer matches.\n\nGRADE: C") -> None:
        self.requests: list[Request] = []
        self.reply = reply

    async def __call__(self, request: Request) -> str:
        self.requests.append(request)
        return self.reply


def _prepare_by_hand(root: Path, benchmark_id: str) -> None:
    benchmark_root = root / benchmark_id
    (benchmark_root / "targets").mkdir(parents=True)
    (benchmark_root / "cases.json").write_text(
        json.dumps([{"id": 1, "input": "What is the capital of France?"}]),
        encoding="utf-8",
    )
    (benchmark_root / "targets" / "1.json").write_text(
        json.dumps({"target": "Paris"}), encoding="utf-8"
    )


def _row(case_id: int, answer: str) -> dict[str, object]:
    record = {
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


async def _call(node: Url4Node, route: str, payload: str, intent: str) -> str:
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
async def test_the_aggregate_binds_the_judge_transport_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole seam under one roof: a judged benchmark's aggregate grades a Case by
    calling the node's own judge route — pinned params on the wire, score in the
    result, and the judge's words in the evidence."""

    benchmark = _assembled(_judged_spec(), monkeypatch)
    judge = _JudgeEndpoint()
    node = Url4Node("test")
    node.endpoint("/judge-4")(judge)
    _prepare_by_hand(tmp_path, benchmark.benchmark.id)
    benchmark.benchmark.install(node, tmp_path)

    rows = json.dumps([_row(1, "Paris is the capital of France.")])
    result = json.loads(await _call(node, benchmark.aggregate_route, rows, "aggregate:1"))

    assert result["score"] == 1.0
    assert result["cases"][0]["grade"]["score"] == 1.0
    # The judge's own words survive into the evidence (audit trail).
    assert "The answer matches." in json.dumps(result["cases"][0]["grade"]["checks"])
    # Exactly one judge call left the engine, through the declared route,
    # carrying the pinned params.
    assert len(judge.requests) == 1
    assert judge.requests[0].params.get("temperature") == "0"
    envelope = json.loads(judge.requests[0].context)
    assert envelope["schema"].startswith("screamingface.candidate-input.")


@pytest.mark.asyncio
async def test_a_judge_route_failure_fails_the_case_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A gateway refusal is ONE Case's named failure, never an aborted aggregate."""

    benchmark = _assembled(_judged_spec(), monkeypatch)

    async def refusing(request: Request) -> str:
        raise RuntimeError("the gateway refused: judge overloaded")

    node = Url4Node("test")
    node.endpoint("/judge-4")(refusing)
    _prepare_by_hand(tmp_path, benchmark.benchmark.id)
    benchmark.benchmark.install(node, tmp_path)

    rows = json.dumps([_row(1, "Paris.")])
    result = json.loads(await _call(node, benchmark.aggregate_route, rows, "aggregate:1"))

    case = result["cases"][0]
    assert case["grade"]["score"] is None
    assert case["failures"][0]["code"] == "scorer_error"


def test_the_judge_declaration_rides_the_assembled_benchmark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The binding seam: install-time wiring reads the judge off the ImportedBenchmark."""

    benchmark = _assembled(_judged_spec(), monkeypatch)
    assert benchmark.judge == JudgeSpec(model="judge-4", params=(("temperature", "0"),))
    unjudged = _assembled(
        replace(_judged_spec(), judge=None, scorer="inspect_ai.scorer:match", scorer_kwargs={}),
        monkeypatch,
    )
    assert unjudged.judge is None


def test_a_judge_model_kwarg_without_a_declaration_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detection must key on the KWARG, not the scorer's name: a custom eval-module
    scorer (frontierscience's shape) carries its judge under a model kwarg while
    matching no model_graded_* name — importing it undeclared shipped a judge
    outside benchmark identity (review finding, 2026-09-24)."""

    for kwargs in ({"model": None}, {"model": "openai/gpt-4o"}, {"grader_model": "openai/gpt-4o"}):
        spec = _judged_spec(
            scorer="inspect_evals.frontierscience.frontierscience:frontierscience_scorer",
            scorer_kwargs=kwargs,
            judge=None,
        )
        with pytest.raises(ValueError, match="judge"):
            _assembled(spec, monkeypatch)


def test_a_non_gateway_judge_model_value_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A judge-model kwarg naming another provider would call OpenAI directly —
    unmetered, outside the gateway, outside benchmark identity. Refused by name."""

    spec = _judged_spec(
        scorer_kwargs={"model": "screamingface/judge-4", "grader_model": "openai/gpt-4o"},
    )
    with pytest.raises(ValueError, match="openai/gpt-4o"):
        _assembled(spec, monkeypatch)


@pytest.mark.asyncio
async def test_the_judged_aggregate_runs_its_judge_fetch_on_the_runs_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """INVARIANT (OME-1240): no second loop for judged grading — the run's shared
    HTTP client's pooled connections are bound to the run's own loop, and httpx
    raises "bound to a different event loop" anywhere else (reproduced 2026-09-24)."""

    import asyncio

    seen_loops: list[Any] = []

    class _LoopRecordingJudge(_JudgeEndpoint):
        async def __call__(self, request: Request) -> str:
            seen_loops.append(asyncio.get_running_loop())
            return await super().__call__(request)

    benchmark = _assembled(_judged_spec(), monkeypatch)
    judge = _LoopRecordingJudge()
    node = Url4Node("test")
    node.endpoint("/judge-4")(judge)
    _prepare_by_hand(tmp_path, benchmark.benchmark.id)
    benchmark.benchmark.install(node, tmp_path)

    outer = asyncio.get_running_loop()
    rows = json.dumps([_row(1, "Paris.")])
    result = json.loads(await _call(node, benchmark.aggregate_route, rows, "aggregate:1"))
    assert result["cases"][0]["grade"]["score"] == 1.0
    assert seen_loops == [outer]


def test_the_run_sync_twins_stay_verbatim_identical() -> None:
    """The shared grading code's `_run_sync` and single_shot's copy must not diverge — the copy
    exists only because the shared grading code's is private, and a one-sided fix (the context
    copy, the loop discipline) would silently split behavior between the aggregate
    and the draft-feedback offer."""

    import ast
    import inspect as pyinspect

    from screamingface_engine.benchmarks.shared_grading import (
        benchmark_aggregation as shared_aggregation,
    )

    def body_dump(fn: Any) -> str:
        tree = ast.parse(pyinspect.getsource(fn).strip())
        function = tree.body[0]
        assert isinstance(function, ast.FunctionDef)
        # Drop the docstring — wording differs; the CODE must not.
        if isinstance(function.body[0], ast.Expr):
            function.body = function.body[1:]
        return ast.dump(function, include_attributes=False)

    assert body_dump(single_shot._run_sync) == body_dump(shared_aggregation._run_sync)


# ── no answer key: judged benchmarks only, and only when the judge never reads one ──


def _no_key_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES

    # OME-1460: gsm8k is a Task-replay declaration now; the flip it stands in for is the same.
    monkeypatch.setitem(
        TASK_REPLAY_CASES, "gsm8k", replace(TASK_REPLAY_CASES["gsm8k"], has_answer_key=False)
    )


def test_a_benchmark_without_an_answer_key_must_be_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no key, nothing but a judge can grade — a string-match benchmark would mark
    every reply wrong against an empty string, silently."""

    _no_key_snapshot(monkeypatch)
    spec = _judged_spec(
        scorer="inspect_ai.scorer:match", scorer_kwargs={}, judge=None, with_check_surface=False
    )

    with pytest.raises(ValueError, match="answer key"):
        _assembled(spec, monkeypatch)


def test_a_judge_that_reads_the_key_refuses_a_benchmark_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model_graded_qa's default prompt compares against {criterion} (the key); with
    no key the judge would grade against nothing, so the row must pass its own
    template, and that template must not read the key."""

    _no_key_snapshot(monkeypatch)

    with pytest.raises(ValueError, match="criterion"):
        _assembled(_judged_spec(), monkeypatch)
    with pytest.raises(ValueError, match="criterion"):
        _assembled(
            _judged_spec(
                scorer_kwargs={"model": "screamingface/judge-4", "template": "{criterion}"}
            ),
            monkeypatch,
        )


def test_a_judge_prompt_without_the_key_assembles(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_key_snapshot(monkeypatch)
    spec = _judged_spec(
        scorer_kwargs={
            "model": "screamingface/judge-4",
            "template": "[QUESTION]: {question}\n[RESPONSE]: {answer}\n{instructions}",
        }
    )

    assert _assembled(spec, monkeypatch).benchmark.revision


@pytest.mark.parametrize(
    "template",
    ["{criterion!s}", "{criterion:>10}", "{criterion.text}", "Key: {criterion[0]}", "{oops"],
)
def test_every_spelling_of_the_answer_key_field_is_caught(
    monkeypatch: pytest.MonkeyPatch, template: str
) -> None:
    """A substring test missed {criterion!s} and friends; the formatter's own parser
    sees them all, and an unparseable template is treated as reading the key
    (review on PR #1112)."""

    _no_key_snapshot(monkeypatch)
    spec = _judged_spec(scorer_kwargs={"model": "screamingface/judge-4", "template": template})

    with pytest.raises(ValueError, match="criterion"):
        _assembled(spec, monkeypatch)


# ── no answer key and no judge: only an eval's own scorer that never reads one (R19) ──

#: The eval's own scorer of a key-less, judge-less Benchmark: cyberseceval_4 mitre_frr's
#: refusal regex. Named here only as a reference; assembly never imports it.
_REPLY_ONLY_SCORER: str = "inspect_evals.cyberseceval_4.mitre_frr.scorers:refusal_scorer"


def _reply_only_spec(**overrides: Any) -> BenchmarkSpec:
    """A key-less row graded by the eval's own scorer, with no judge, declaring that the
    scorer never reads the answer key."""

    values: dict[str, Any] = {
        "scorer": _REPLY_ONLY_SCORER,
        "scorer_kwargs": {},
        "judge": None,
        "scorer_reads_answer_key": False,
    }
    values.update(overrides)
    return _judged_spec(**values)


def test_an_eval_scorer_that_never_reads_the_key_assembles_without_a_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec R19: a reply-only scorer (mitre_frr's refusal regex) grades the same with or
    without a key, so the row needs no judge once it says so."""

    _no_key_snapshot(monkeypatch)

    assert _assembled(_reply_only_spec(), monkeypatch).benchmark.revision


def test_a_judge_less_row_without_a_key_names_the_declaration_it_lacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal tells the importing agent the one way out besides a judge."""

    _no_key_snapshot(monkeypatch)

    with pytest.raises(ValueError, match="scorer_reads_answer_key=False"):
        _assembled(_reply_only_spec(scorer_reads_answer_key=True), monkeypatch)


def test_an_inspect_built_in_scorer_cannot_claim_it_ignores_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """inspect's own scorers (match, choice, includes, …) all compare the reply against the
    key; against an empty one they mark every reply wrong, silently. The claim is refused."""

    _no_key_snapshot(monkeypatch)

    with pytest.raises(ValueError, match="built-in"):
        _assembled(_reply_only_spec(scorer="inspect_ai.scorer:match"), monkeypatch)


def test_the_claim_is_refused_on_a_row_that_has_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """INVARIANT: the flag has one use. On a row with a key it would claim something no
    Case needs, and a reader could not tell which of the two to trust."""

    with pytest.raises(ValueError, match="has an answer key"):
        _assembled(_reply_only_spec(), monkeypatch)


def test_the_claim_is_refused_on_a_judged_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """A judged row's key question is the judge prompt's (checked above); the flag would be
    a second, unchecked answer to it."""

    _no_key_snapshot(monkeypatch)
    spec = _judged_spec(
        scorer_kwargs={"model": "screamingface/judge-4", "template": "{question} {answer}"},
        scorer_reads_answer_key=False,
    )

    with pytest.raises(ValueError, match="judge"):
        _assembled(spec, monkeypatch)


def test_a_reply_only_row_is_refused_the_check_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Owner decision 2026-10-05: a pass/fail check over a reply-only scorer (a refusal
    regex) lets a fusion re-word a draft until it slips past, so the offer is refused at
    assembly, not left to the importing agent to remember (review finding on #1222: the
    importer's generated row turns it on for any free-text key-less task)."""

    _no_key_snapshot(monkeypatch)

    with pytest.raises(ValueError, match="check surface"):
        _assembled(_reply_only_spec(with_check_surface=True), monkeypatch)
