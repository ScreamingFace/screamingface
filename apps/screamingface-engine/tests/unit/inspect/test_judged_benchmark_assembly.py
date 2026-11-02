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
        "failure_policy": "coverage_declare",
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


# ── some Cases' empty key is their answer: only for the eval's own judge-free scorer (R5) ──

#: The eval's own scorer of a Benchmark whose empty keys are answers: contracteval's (no
#: clause spans → the right reply declines). Assembly reads its source to confirm it reaches
#: no judge (a reference it cannot find is refused, OME-1602) and never imports it.
_EMPTY_KEY_SCORER: str = (
    "screamingface_engine_inspect.local_tasks.contracteval.contracteval:contracteval_containment"
)


def _empty_key_snapshot(monkeypatch: pytest.MonkeyPatch, **cases: Any) -> None:
    """Make the gsm8k Cases row say some Cases' empty key is their answer."""

    from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES

    monkeypatch.setitem(
        TASK_REPLAY_CASES,
        "gsm8k",
        replace(TASK_REPLAY_CASES["gsm8k"], empty_answer_key_allowed=True, **cases),
    )


def _own_scorer_spec(**overrides: Any) -> BenchmarkSpec:
    """A judge-free row graded by the eval's own scorer, which reads the key (empty or not)."""

    values: dict[str, Any] = {"scorer": _EMPTY_KEY_SCORER, "scorer_kwargs": {}, "judge": None}
    values.update(overrides)
    return _judged_spec(**values)


def test_empty_keys_as_answers_assemble_beside_the_evals_own_scorer_without_a_new_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one place the opt-in stands. It is no identity pin: the Case Digest already seals
    the empty keys, so the revision is the one the same row has without it."""

    without: str = _revision(_own_scorer_spec(), monkeypatch)
    _empty_key_snapshot(monkeypatch)

    assert _revision(_own_scorer_spec(), monkeypatch) == without


def test_empty_keys_as_answers_are_refused_on_a_judged_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A judge reads the key or not by its prompt; has_answer_key=False already says that."""

    _empty_key_snapshot(monkeypatch)
    spec = _judged_spec(
        scorer_kwargs={"model": "screamingface/judge-4", "template": "{question} {answer}"}
    )

    with pytest.raises(ValueError, match="judged"):
        _assembled(spec, monkeypatch)


def test_empty_keys_as_answers_are_refused_on_an_inspect_built_in_scorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """inspect's own scorers compare every reply against the key; an empty one fails them all."""

    _empty_key_snapshot(monkeypatch)

    with pytest.raises(ValueError, match="built-in"):
        _assembled(_own_scorer_spec(scorer="inspect_ai.scorer:match"), monkeypatch)


def test_empty_keys_as_answers_contradict_a_row_with_no_key_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One flag says some Cases have a key, the other that none has; a reader could not tell
    which to trust, so the row keeps one."""

    _empty_key_snapshot(monkeypatch, has_answer_key=False)

    with pytest.raises(ValueError, match="has_answer_key=False"):
        _assembled(_own_scorer_spec(), monkeypatch)


def test_empty_keys_as_answers_contradict_a_scorer_that_never_reads_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-in exists because the scorer reads the emptiness; a reply-only claim denies it."""

    _empty_key_snapshot(monkeypatch)

    with pytest.raises(ValueError, match="scorer_reads_answer_key=False"):
        _assembled(_own_scorer_spec(scorer_reads_answer_key=False), monkeypatch)


def test_empty_keys_as_answers_are_refused_the_check_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draft Feedback over an empty key would tell a fusion "no clause here" mid-run, which
    is the answer itself."""

    _empty_key_snapshot(monkeypatch)

    with pytest.raises(ValueError, match="check surface"):
        _assembled(_own_scorer_spec(with_check_surface=True), monkeypatch)


# ── Draft Feedback without an answer key: only on a Benchmark the owner allowed (R10) ──

#: The eval's own scorer of an IFEval Benchmark: it grades the reply against the
#: instructions in each Sample's metadata, never a key. Assembly reads its source to confirm
#: it reaches no judge (a reference it cannot find is refused, OME-1602) and never imports it.
_INSTRUCTION_SCORER: str = "inspect_evals.ifeval.ifeval:instruction_following"


def _ifeval_shaped_spec(**overrides: Any) -> BenchmarkSpec:
    """A key-less, judge-less local-Task row keyed "ifeval" (catalogue id "ifeval", the one
    the owner allowed), asking for Draft Feedback."""

    values: dict[str, Any] = {
        "key": "ifeval",
        "origin": "screamingface",
        "scorer": _INSTRUCTION_SCORER,
        "with_check_surface": True,
    }
    values.update(overrides)
    return _reply_only_spec(**values)


def _ifeval_cases(monkeypatch: pytest.MonkeyPatch, **cases: Any) -> None:
    """Give the "ifeval" key a Cases row (gsm8k's, standing in) with no answer key, unless
    the test overrides that."""

    from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES

    monkeypatch.setitem(
        TASK_REPLAY_CASES,
        "ifeval",
        replace(TASK_REPLAY_CASES["gsm8k"], **{"has_answer_key": False, **cases}),
    )


def test_the_owner_allowed_benchmark_offers_draft_feedback_without_an_answer_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1527 R10: IFEval has no key; its instructions sit in the prompt, so a mid-run
    check leaks nothing, and re-wording a draft until the checker passes IS the task the
    Corrective Loop's paper studied. The owner allowed it by name, so it assembles with
    the offer on (the 2026-10-05 refusal keeps every other reply-only row)."""

    _ifeval_cases(monkeypatch)

    assembled: Any = _assembled(_ifeval_shaped_spec(), monkeypatch)

    # The exact list is the owner test's pin (test_draft_feedback_offer_is_owner_opt_in.py).
    assert "ifeval" in benchmarks.OWNER_ALLOWED_DRAFT_FEEDBACK
    assert assembled.benchmark.id == "ifeval"
    assert assembled.benchmark.check_surface is not None


def test_a_reply_only_benchmark_the_owner_never_named_is_still_refused_draft_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exception is the owner's list, not the row's shape: the same IFEval-shaped row
    under another catalogue id is refused, so a refusal-regex Benchmark (mitre_frr) can
    never earn the offer by looking like IFEval."""

    from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES

    _ifeval_cases(monkeypatch)
    monkeypatch.setitem(TASK_REPLAY_CASES, "ifeval_twin", TASK_REPLAY_CASES["ifeval"])

    with pytest.raises(ValueError, match="ifeval_twin: .*OWNER_ALLOWED_DRAFT_FEEDBACK"):
        _assembled(_ifeval_shaped_spec(key="ifeval_twin"), monkeypatch)


def test_an_inspect_evals_row_keyed_ifeval_is_not_the_benchmark_the_owner_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY catalogue ids, not row keys: an inspect_evals row keyed "ifeval" is served as
    "inspect-ifeval", a different Benchmark with a different scorer, which the owner never
    read or allowed."""

    _ifeval_cases(monkeypatch)

    with pytest.raises(ValueError, match="inspect-ifeval: .*OWNER_ALLOWED_DRAFT_FEEDBACK"):
        _assembled(_ifeval_shaped_spec(origin="inspect_evals"), monkeypatch)


def test_the_owner_allowed_benchmark_is_still_refused_draft_feedback_over_an_empty_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exception lifts only the reply-only refusal. Draft Feedback over an empty key
    tells a fusion "no clause here" mid-run, which is the answer itself, so that refusal
    stands even for a Benchmark the owner allowed."""

    _ifeval_cases(monkeypatch, has_answer_key=True, empty_answer_key_allowed=True)
    spec: BenchmarkSpec = _ifeval_shaped_spec(
        scorer=_EMPTY_KEY_SCORER, scorer_reads_answer_key=True
    )

    with pytest.raises(ValueError, match="would leak the answer"):
        _assembled(spec, monkeypatch)


# ── OME-1602, F2: judges the row cannot see in its kwargs ────────────────────

import textwrap  # noqa: E402

#: A stand-in eval module whose scorers reach a judge without naming one in their kwargs. Its
#: first line raises, so a test using it also proves assembly reads the source and never
#: imports the eval (inspect stays off the Engine's run path).
_UNIMPORTABLE_JUDGED_SCORERS: str = textwrap.dedent(
    """
    raise RuntimeError("assembly imported the eval's scorer module")

    from inspect_ai.model import get_model

    def takes_a_judge(include_history=None, judge_model=None):
        async def score(state, target):
            return None
        return score

    async def _ask_the_grader(question):
        return await get_model(role="grader").generate(question)

    def asks_the_grader():
        async def score(state, target):
            await _ask_the_grader("Is it right?")
        return score

    def judge_free():
        async def score(state, target):
            return None
        return score

    def asks_two_roles():
        async def score(state, target):
            await get_model(role="grader").generate("Is it right?")
            await get_model(role="critic").generate("Is it fair?")
        return score
    """
)


@pytest.fixture
def judged_scorers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Put the stand-in scorer module on the import path; return its module name."""

    (tmp_path / "stand_in_judged_scorers.py").write_text(
        _UNIMPORTABLE_JUDGED_SCORERS, encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    return "stand_in_judged_scorers"


def test_a_panel_of_judges_in_the_kwargs_is_refused_even_with_a_declared_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The declared judge is called, and so is every other judge in the list, unmetered
    and outside benchmark identity: the old check only looked for the declared one."""

    spec = _judged_spec(
        scorer_kwargs={
            "model": "screamingface/judge-4",
            "grader_models": ["screamingface/judge-4", "openai/gpt-4o"],
        }
    )

    with pytest.raises(ValueError, match=r"grader_models names a panel of 2 judges"):
        _assembled(spec, monkeypatch)


def test_a_judge_free_row_whose_scorer_takes_a_judge_parameter_is_refused(
    judged_scorers: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """niah's shape: the scorer takes judge_model and nobody passes it, so it would grade
    with its default, a judge outside benchmark identity."""

    spec = _judged_spec(scorer=f"{judged_scorers}:takes_a_judge", scorer_kwargs={}, judge=None)

    with pytest.raises(
        ValueError, match=r"takes_a_judge reaches a judge \(parameter judge_model\)"
    ):
        _assembled(spec, monkeypatch)


def test_a_judge_free_row_whose_scorer_asks_for_the_grader_role_is_refused(
    judged_scorers: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """simpleqa's shape, one helper down: the role is asked in the body, never in a kwarg."""

    spec = _judged_spec(scorer=f"{judged_scorers}:asks_the_grader", scorer_kwargs={}, judge=None)

    with pytest.raises(ValueError, match=r"asks_the_grader reaches a judge \(get_model\(role="):
        _assembled(spec, monkeypatch)


def test_a_judge_free_row_whose_scorer_reaches_no_judge_still_assembles(
    judged_scorers: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _judged_spec(scorer=f"{judged_scorers}:judge_free", scorer_kwargs={}, judge=None)

    assert _assembled(spec, monkeypatch).judge is None


def test_a_scorer_from_a_package_not_installed_is_refused_naming_the_missing_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Engine without the inspect extra cannot read inspect_evals' scorers; the refusal
    must name the missing install, not blame a judge the reader never saw."""

    # A package name chosen so no environment installs it, standing in for inspect_evals.
    spec = _judged_spec(
        scorer="stand_in_never_installed_evals.scorers:judge_free", scorer_kwargs={}, judge=None
    )

    with pytest.raises(
        ValueError,
        match=r"comes from stand_in_never_installed_evals, which is not installed",
    ):
        _assembled(spec, monkeypatch)


def test_a_missing_module_inside_an_installed_package_is_still_refused_as_unread(
    judged_scorers: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The install check only speaks for a package that is absent; a wrong path inside an
    installed one stays unread, and unread is never judge-free."""

    spec = _judged_spec(scorer=f"{judged_scorers}.nowhere:judge_free", scorer_kwargs={}, judge=None)

    with pytest.raises(ValueError, match=r"judge_free reaches a judge \(unread: "):
        _assembled(spec, monkeypatch)


def test_an_extra_scorer_that_reaches_a_judge_is_refused(
    judged_scorers: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Extra scorers are built bare at grading time, so a judge they reach is never the
    row's pinned one: the check reads every extra scorer, not only the headline."""

    spec = _judged_spec(
        scorer="inspect_ai.scorer:match",
        scorer_kwargs={},
        judge=None,
        extra_scorers=(f"{judged_scorers}:takes_a_judge",),
        named_scores=("match", "takes_a_judge"),
    )

    with pytest.raises(ValueError, match=r"extra scorer takes_a_judge reaches a judge"):
        _assembled(spec, monkeypatch)


def test_a_role_judged_row_whose_scorer_asks_only_that_role_assembles(
    judged_scorers: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _judged_spec(
        scorer=f"{judged_scorers}:asks_the_grader",
        scorer_kwargs={},
        judge=JudgeSpec(model="judge-4", model_role="grader"),
    )

    assert _assembled(spec, monkeypatch).judge is not None


def test_a_role_judged_row_whose_scorer_asks_a_second_role_is_refused(
    judged_scorers: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row binds one role to its pinned judge; inspect hands the unbound second role
    the Candidate's own model, so the Candidate would mark its own answers. Once a human
    pins the judge, assembly is the only check that still reads the scorer."""

    spec = _judged_spec(
        scorer=f"{judged_scorers}:asks_two_roles",
        scorer_kwargs={},
        judge=JudgeSpec(model="judge-4", model_role="grader"),
    )

    with pytest.raises(
        ValueError,
        match=r"the judge fills the 'grader' role, but the scorer also reaches the "
        r"role\(s\) 'critic'",
    ):
        _assembled(spec, monkeypatch)


def test_the_older_judge_kwarg_lists_stay_inside_the_judge_parameters() -> None:
    """Three lists name the judge kwargs; a name added to one of the older two but not to
    the judge-shape reader's would let that judge through the reader unseen."""

    from screamingface_engine_inspect.importer import _JUDGE_MODEL_KWARG_NAMES
    from screamingface_engine_inspect.judge_shape import JUDGE_PARAMETERS

    assert benchmarks._JUDGE_MODEL_KWARGS <= JUDGE_PARAMETERS
    assert _JUDGE_MODEL_KWARG_NAMES <= JUDGE_PARAMETERS
