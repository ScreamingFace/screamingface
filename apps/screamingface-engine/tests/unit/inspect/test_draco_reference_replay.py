# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on.
"""Replaying the DRACO reference run reproduces its scores, Case by Case (spec V4).

FEATURE: a recorded judge reply is final (spec 2026-10-16-judge-redraw-live-only). DRACO is the
check that the evaluation algorithm is right, because we hold the raw data of its reference run:
the rubric of each Case, the recorded verdict of each criterion in each judge pass (a verdict the
reference lost is simply absent), and the reference ``normalized_score``. The fixture
``tests/fixtures/draco_reference_cases.json`` holds four real Cases from that run, verbatim.

The replay judge answers every (criterion, pass) the way the gateway cache answers a seeded
replay: the recorded verdict, or, where the reference has none, the seed's placeholder reply that
carries no verdict on purpose; every reply is marked as served from the cache. Should the Engine
ask again outside the cache, the replay judge answers like a fresh live judge would ("MET"),
which is exactly how a replay drifts from the recording, so the drift fails these tests.

STORY: as someone checking that the Engine grades DRACO exactly as the reference run did, a
replay of the recorded verdicts gives the reference score, with one judge call per criterion per
pass and no paid call.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.dataset import Sample  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine.request_scope import (  # noqa: E402
    RequestScope,
    current_scope,
    request_scope,
)
from screamingface_engine.world.reply_origin import record_reply_origin  # noqa: E402
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.local_tasks.draco.draco import (  # noqa: E402
    judge_criteria,
    record_to_sample,
)
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PreparedCase,
    prepared_case,
)
from url4.wire.subrequest import decode_subrequest_http, extract_expression_params  # noqa: E402

_FIXTURE: Path = Path(__file__).parents[2] / "fixtures" / "draco_reference_cases.json"
_CASES: list[dict[str, Any]] = json.loads(_FIXTURE.read_text(encoding="utf-8"))["cases"]
_PASSES: int = 3

#: The seed's placeholder for a verdict the reference lost (`draco-cache-seed:fill:*` rows):
#: a successful reply that deliberately carries no verdict.
_NO_VERDICT: str = (
    "[draco-cache-seed:fill:pass_gap] This row exists only so the request is served from "
    "cache; it deliberately carries NO verdict, so the score reproduces the published one."
)


def _reply(met: bool) -> str:
    status: str = "MET" if met else "UNMET"
    return json.dumps({"explanation": "Recorded verdict.", "criterion_status": status})


class _ReplayJudge:
    """The gateway judge during a seeded replay: every reply is the recording, from the cache.

    WHY keyed by requirement and seed: each call names its pass as ``seed=<pass>``, and the
    criterion is found by its requirement text inside the judge prompt (the longest one that
    the prompt contains, so a requirement that is part of another never matches by mistake).
    """

    def __init__(self, case: dict[str, Any]) -> None:
        rubric: dict[str, Any] = json.loads(case["rubric"])
        self.criteria: list[dict[str, str]] = judge_criteria(rubric)
        self.passes: list[dict[str, bool]] = case["passes"]
        self.calls: list[tuple[str, int, bool | None]] = []

    async def __call__(self, target: str) -> str:
        _, _, query = target.partition("?")
        params, q = extract_expression_params(query)
        assert q is not None
        context, _ = decode_subrequest_http(q)
        prompt: str = json.loads(context)["messages"][1]["content"]
        judge_pass: int = int(params["seed"])
        criterion_id: str = self._criterion(prompt)
        participate: bool | None = current_scope().cache.participate
        self.calls.append((criterion_id, judge_pass, participate))
        if participate is False:
            # A call that left the cache reaches a live judge, which gives a fresh verdict.
            record_reply_origin("live")
            return _reply(True)
        record_reply_origin("cache")
        recorded: dict[str, bool] = (
            self.passes[judge_pass - 1] if judge_pass <= len(self.passes) else {}
        )
        if criterion_id not in recorded:
            return _NO_VERDICT
        return _reply(recorded[criterion_id])

    def _criterion(self, prompt: str) -> str:
        matches: list[dict[str, str]] = [c for c in self.criteria if c["requirement"] in prompt]
        assert matches, "the judge prompt names no rubric criterion"
        longest: int = max(len(c["requirement"]) for c in matches)
        best: list[dict[str, str]] = [c for c in matches if len(c["requirement"]) == longest]
        assert len(best) == 1, "two criteria share one requirement text"
        return best[0]["id"]


@pytest.fixture(params=range(len(_CASES)), ids=[case["qa_id"][:8] for case in _CASES])
def case(request: pytest.FixtureRequest) -> dict[str, Any]:
    return _CASES[request.param]


@pytest.fixture
def judge(case: dict[str, Any]) -> Iterator[_ReplayJudge]:
    """The replay judge, bound as draco-3pass's judge, inside a run's request scope."""

    replay: _ReplayJudge = _ReplayJudge(case)
    spec = imported_benchmark("draco-3pass").judge
    assert spec is not None
    transport = JudgeTransport(
        fetch=replay,
        params=spec.params,
        benchmark_id="draco-3pass",
        seed_per_pass=spec.seed_per_pass,
    )
    with request_scope(RequestScope(origin="run")), bound_judge_transport(transport):
        yield replay


async def _grade(case: dict[str, Any], index: int) -> CaseGradeOutcome:
    """Grade one reference Case through draco-3pass's real per-Case grading hook."""

    row: dict[str, Any] = {
        "problem": case["question"],
        "answer": case["rubric"],
        "domain": case["domain"],
    }
    sample: Sample = record_to_sample(row, index)
    prepared: PreparedCase = prepared_case(
        sample, index, str(sample.input), TASK_REPLAY_CASES["draco-3pass"]
    )
    hook = imported_benchmark("draco-3pass").aggregation().grade_case
    return await hook(
        GradeRequest(
            case_id=index,
            input=TextPayload(text=case["question"]),
            answer=TextPayload(text=case["answer"]),
            row={"case": {"status": "answered"}},
            material=json.loads(json.dumps(prepared["grading_material"])),
        )
    )


@pytest.mark.asyncio
async def test_a_replayed_reference_case_scores_what_the_reference_scored(
    case: dict[str, Any], judge: _ReplayJudge
) -> None:
    """INVARIANT: the replay reproduces the recording — the reference score to 4 places, or,
    for the reference's error row, no score at all (the mean leaves the Case out)."""

    outcome: CaseGradeOutcome = await _grade(case, _CASES.index(case) + 1)

    if case["normalized_score"] is None:
        assert outcome.failure_code == "judge_reply_invalid", outcome.checks
        assert outcome.score is None
    else:
        assert outcome.failure_code is None, outcome.checks
        assert outcome.score == case["normalized_score"]
        # AIDEV-NOTE: not asserted here — the Case's `judge_redraws` metadata. draco.py books
        # MAX_JUDGE_REDRAWS for every item that gives up, also when a recorded reply ended it
        # with no redraw. Changing draco.py moves the published draco/draco-3pass revisions (the
        # Task source is hashed), an owner decision; the call count in the next test is the proof
        # that no redraw happened.


@pytest.mark.asyncio
async def test_a_replay_asks_once_per_criterion_per_pass_and_never_leaves_the_cache(
    case: dict[str, Any], judge: _ReplayJudge
) -> None:
    """The reference asked the judge once per criterion per pass, so the replay does too; a
    recorded reply with no verdict is final, so no call ever opts out of the gateway cache."""

    await _grade(case, _CASES.index(case) + 1)

    assert len(judge.calls) == len(judge.criteria) * _PASSES
    assert sorted((criterion, judge_pass) for criterion, judge_pass, _ in judge.calls) == sorted(
        (criterion["id"], judge_pass)
        for criterion in judge.criteria
        for judge_pass in range(1, _PASSES + 1)
    )
    assert all(participate is None for _, _, participate in judge.calls)
