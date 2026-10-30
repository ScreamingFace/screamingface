"""OME-1775 — a fusion Case that fails with cancelled siblings replays exactly, so it is complete.

FEATURE: OME-1775 (spec `docs/spec/2026-10-29-OME-1775-cancelled-call-not-partial.md` §4 R1). A
whole capture run of a two-Case MedXpert Benchmark with a fusion Candidate goes through the real
executor. On Case 1 one member answers with `model_token_cap`, and url4 cancels the two members
still in flight: their calls leave no entry. A replay of the copy fails the same Case again and
scores the other the same, so the capture is `complete`. A cancelled-or-unanswered call in a Case
that SCORED stays `partial` (R4).
STORY: as a researcher who submits a fusion score with a failed Case, the score is replayable.

A separate module (append-only gate).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from frozen_copy_support import CHAT, COPY, OPEN, REPLAY_CHAT, SEAL

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate
from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT
from screamingface_engine.benchmarks.medxpert.prepare import emit
from screamingface_engine.capture_outcomes import CALL_OCCURRENCE_HEADER, CASE_KEY_HEADER
from screamingface_engine.job_env import CAPTURE, REPLAY_FROZEN_COPY
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from url4.streaming.interfaces import Completed

pytestmark = pytest.mark.asyncio

_DATA = Path(__file__).parent / "data"
_FUSION = (_DATA / "combine_contract" / "model_synthesizer_candidate.url4").read_text("utf-8")
_FUSION_MODELS = ("prov/member-a", "prov/member-b", "prov/member-c", "prov/synth")
_INTENT = (
    "'Answer the request accurately and completely. "
    "Follow every instruction and formatting constraint in the request.'"
)
_MEMBER_C = f"model_3:0.0:/prov/member-c($input)!{_INTENT}"
# WHY `;optional`: member C may fail and the Case still scores on the other two members.
_OPTIONAL_C = _FUSION.replace(_MEMBER_C, f"{_MEMBER_C};optional", 1)
assert _OPTIONAL_C != _FUSION, "the fusion fixture no longer binds member C as expected"
_FAILING_CASE = "Case one"
# WHY the job env: `build_executor` binds the run's request scope from it, as a Job does.
_CAPTURE = {CAPTURE: "1"}
_REPLAY = {REPLAY_FROZEN_COPY: COPY}

Answer = Callable[[str, bool], Awaitable[httpx.Response]]
"""A provider stand-in: (model, is the failing Case) → its response."""


def _completion(content: str | None, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


class CopyGateway:
    """An AI Gateway that keeps a frozen copy the way the real one does (spec §3 A1).

    A capture call is answered by ``answer``; its response is stored, before it is returned, at
    (case key, occurrence, digest of the body without ``cache``). A replay call is served the
    highest-``seq`` 200 at its key, else the highest-``seq`` entry, else ``frozen_copy_miss``. A
    call cancelled while it waits for its answer stores nothing (the gateway's 499).
    """

    def __init__(self, answer: Answer) -> None:
        self._answer = answer
        self.entries: dict[tuple[str, str, str], list[httpx.Response]] = {}
        self.cancelled: list[str] = []

    @staticmethod
    def _key(request: httpx.Request) -> tuple[str, str, str]:
        body = json.loads(request.content)
        body.pop("cache", None)
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return (
            request.headers.get(CASE_KEY_HEADER, ""),
            request.headers[CALL_OCCURRENCE_HEADER],
            hashlib.sha256(canonical.encode()).hexdigest(),
        )

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == CHAT:
            return await self._capture(request)
        if path == REPLAY_CHAT:
            return self._replay(request)
        return self._copy_lifecycle(request)

    @staticmethod
    def _copy_lifecycle(request: httpx.Request) -> httpx.Response:
        if request.url.path == OPEN:
            return httpx.Response(201, json={"id": COPY, "status": "open"})
        if request.url.path == SEAL:
            return httpx.Response(200, json={"id": COPY, "status": "sealed", "entries": 1})
        raise AssertionError(f"unexpected gateway request {request.method} {request.url.path}")

    async def _capture(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        failing = _FAILING_CASE in json.dumps(body["messages"])
        try:
            response = await self._answer(body["model"], failing)
        except asyncio.CancelledError:
            self.cancelled.append(body["model"])
            raise
        self.entries.setdefault(self._key(request), []).append(response)
        return httpx.Response(
            response.status_code, json=response.json(), headers={"X-AIGW-Capture": "stored"}
        )

    def _replay(self, request: httpx.Request) -> httpx.Response:
        stored = self.entries.get(self._key(request), [])
        hits = [entry for entry in stored if entry.status_code == 200]
        entry = (hits or stored or [None])[-1]
        if entry is None:
            return httpx.Response(
                404, json={"detail": {"code": "frozen_copy_miss", "message": "m"}}
            )
        word = "hit" if entry.status_code == 200 else "error"
        return httpx.Response(entry.status_code, json=entry.json(), headers={"X-AIGW-Replay": word})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handle), base_url="http://aigateway.test"
        )


def _assets(root: Path, *, cases: int = 2) -> None:
    rows = [
        {
            "id": "Text-0",
            "question": f"{_FAILING_CASE}: pick B",
            "options": {"A": "a", "B": "b"},
            "label": "B",
        },
        {
            "id": "Text-1",
            "question": "Case two: pick B",
            "options": {"A": "a", "B": "b"},
            "label": "B",
        },
    ]
    emit(rows[:cases], root / "medxpert")


async def _run(
    gateway: CopyGateway,
    env: dict[str, str],
    candidate: str,
    models: tuple[str, ...],
    assets: Path,
    *,
    cases: int = 2,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One whole Benchmark run on the production executor: its result, and its `capture.*` state."""
    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=models[0],
            models=tuple(ModelSpec(id=model) for model in models),
        )
    )
    async with gateway.client() as client:
        executor = build_executor(
            env,
            config,
            client=client,
            benchmarks=BenchmarkRegistry((MEDXPERT,)),
            benchmark_assets_root=assets,
        )
        expression = link_candidate(candidate.rstrip("\n"), MEDXPERT.build(cases))
        # WHY a bound: a regression that stops the cancel would park a member forever.
        frames = await asyncio.wait_for(_frames(executor, expression), timeout=30)
    completed = frames[-1]
    assert isinstance(completed, Completed)
    assert completed.result.body is not None
    summary = executor.last_summary()
    assert summary is not None and summary.cache_attributes is not None
    capture = {k: v for k, v in summary.cache_attributes.items() if k.startswith("capture.")}
    return json.loads(completed.result.body), capture


async def _frames(executor: Any, expression: str) -> list[Any]:
    return [frame async for frame in executor.execute(expression)]


def _cases(result: dict[str, Any]) -> list[tuple[Any, str, Any, list[str]]]:
    """What a replay must reproduce: per Case its id, status, score and failure codes."""
    return [
        (
            case["case_id"],
            case["status"],
            (case.get("grade") or {}).get("score"),
            sorted(failure["code"] for failure in case["failures"]),
        )
        for case in result["cases"]
    ]


async def _token_cap_then_cancel(model: str, failing: bool) -> httpx.Response:
    """Case 1: member A ends on the token cap; members B and C are still in flight when url4
    cancels them. Case 2: every model answers B."""
    if failing and model == "prov/member-a":
        return _completion(None, finish_reason="length")
    if failing and model in ("prov/member-b", "prov/member-c"):
        await asyncio.sleep(30)
    return _completion("B")


async def test_a_fusion_case_whose_siblings_were_cancelled_is_complete(tmp_path: Path) -> None:
    _assets(tmp_path)
    gateway = CopyGateway(_token_cap_then_cancel)

    result, capture = await _run(gateway, _CAPTURE, _FUSION, _FUSION_MODELS, tmp_path)

    assert sorted(gateway.cancelled) == ["prov/member-b", "prov/member-c"]
    assert [(case_id, status) for case_id, status, _, _ in _cases(result)] == [
        (1, "failed"),
        (2, "scored"),
    ]
    assert "model_token_cap" in _cases(result)[0][3]
    # INVARIANT (R1): the two cancelled calls gave no answer, in a Case that failed, and no later
    # call answered them, so nothing makes the run partial.
    assert capture == {"capture.frozen_copy_id": COPY, "capture.status": "complete"}


async def test_the_replay_of_that_copy_reproduces_the_failed_case(tmp_path: Path) -> None:
    # AIDEV-NOTE: one Case only. A SCORED MedXpert Case cannot replay here: turn 2 embeds turn 1's
    # envelope with its accounting (cost, usage, cache hits), which differs on replay, so every
    # turn-2 call misses. That is a separate defect (reported with OME-1775), not this rule.
    _assets(tmp_path, cases=1)
    gateway = CopyGateway(_token_cap_then_cancel)
    captured, _ = await _run(gateway, _CAPTURE, _FUSION, _FUSION_MODELS, tmp_path, cases=1)

    replayed, capture = await _run(gateway, _REPLAY, _FUSION, _FUSION_MODELS, tmp_path, cases=1)

    # WHY this is the claim R1 rests on: the replay may miss a cancelled call or never send it,
    # but the Case fails again with the same codes either way.
    assert replayed["score"] == captured["score"]
    assert _cases(replayed) == _cases(captured) == [(1, "failed", None, _cases(captured)[0][3])]
    assert capture == {"capture.replay": COPY}


async def _optional_member_unreachable(model: str, failing: bool) -> httpx.Response:
    """Case 1: the `;optional` member C's call never reaches the gateway (connect failure), so
    it gives no answer; members A and B still answer. Case 2: every model answers B."""
    if failing and model == "prov/member-c":
        raise httpx.ConnectError("down")
    return _completion("B")


async def test_an_unanswered_call_in_a_case_that_scored_stays_partial(tmp_path: Path) -> None:
    _assets(tmp_path)
    gateway = CopyGateway(_optional_member_unreachable)

    result, capture = await _run(gateway, _CAPTURE, _OPTIONAL_C, _FUSION_MODELS, tmp_path)

    assert [status for _, status, _, _ in _cases(result)] == ["scored", "scored"]
    # INVARIANT (R4, D1d): a no-answer outcome in a SCORED Case is never forgiven.
    assert capture["capture.status"] == "partial"
    # WHY 2: MedXpert has two turns, and member C fails in both turns of Case 1.
    assert capture["capture.partial.error"] == 2
