"""OME-1786: MedXpertQA's commit turn sends the reasoning TEXT, so a rerun sends the same bytes.

FEATURE: MedXpertQA two-turn protocol. Turn 1 reasons, turn 2 (the commit) is a new call that
carries the question, turn 1's answer and the trigger.

STORY: as a researcher who reruns the same Candidate on the same Cases, every call of the rerun
is served from the AI Gateway's request cache, so the rerun costs nothing and grades the same.

THE DEFECT these tests pin: turn 2 used to carry turn 1's whole result record, a JSON string
that holds the call's accounting (tokens, cost, latency, attempts, cache hit or miss). On a
rerun turn 1 is a cache hit, the Engine rewrites that accounting to zeros and "hit", turn 2's
request bytes change, and the cache (which hashes the messages verbatim) misses. An external
researcher saw 1,899 of 2,450 commit calls billed again on an identical rerun.

Every run here goes through the production executor, the same one a Job builds, because the
accounting only reaches a Candidate's record there.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from frozen_copy_support import COPY
from test_frozen_copy_failed_case import CopyGateway, _completion
from test_frozen_copy_failed_case import _assets as _copy_assets
from test_frozen_copy_failed_case import _cases as _case_outcomes
from test_frozen_copy_failed_case import _run as _copy_run

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate
from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE, encode_candidate_invocation
from screamingface_engine.benchmarks.medxpert.definition import (
    COMMIT_CHAT_ROUTE,
    FINGERPRINT,
    MEDXPERT,
    REVISION,
    compute_revision,
)
from screamingface_engine.benchmarks.medxpert.prepare import emit
from screamingface_engine.benchmarks.medxpert.prompts import COMMIT_INSTRUCTION
from screamingface_engine.benchmarks.medxpert.runtime import _commit_chat
from screamingface_engine.job_env import CAPTURE, REPLAY_FROZEN_COPY
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node
from url4.streaming.interfaces import Completed

_MODEL = "prov/solo"
# WHY a NAMED source: the Engine attaches a call's accounting to the Candidate's record only for
# a named model operation, which is the shape the SDK compiles every Candidate to.
_CANDIDATE = f"(model_1:0.0:/{_MODEL}($input)!'Answer the question.')!'$model_1'"
_CHAT = "/v1/chat/completions"
_TRIGGER_MARK = "the answer is"
_REASONING = 'The findings point to "b", so the answer is not A.'
# The id MedXpertQA published before OME-1786: its turn 2 carried the whole turn-1 record.
_RECORD_CARRYING_REVISION = "1e5a3b8a461a52f7"
# The id MedXpertQA published before OME-1980: its turn 2 was one JSON user message.
_JSON_MESSAGE_REVISION = "490235dc9a53b7d9"
_PROMPT = "Q: Case one: pick B\nA: Let's think step by step."
_TRIGGER = "Therefore, among A through B, the answer is"
# Every key of a Candidate's result record other than the answer text, and every key of the
# accounting inside it. None of them belongs in a prompt.
_RECORD_ONLY_KEYS: tuple[str, ...] = (
    "screamingface.candidate-invocation.v1",
    "finish_reason",
    "operations",
    "accounting",
    "usage",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "provider_latency_ms",
    "provider_attempts",
    "cache",
)


class CachingGateway:
    """An AI Gateway stand-in with a request cache keyed the way the real one keys it.

    The first time it sees a request body it answers as a live provider call and reports a
    cache miss; every later time it serves the stored answer and reports a cache hit. The key
    is a hash of the body with its messages verbatim, so two turn-2 requests share an answer
    only when their bytes are the same.
    """

    def __init__(self, reasoning: dict[str, Any] | None = None) -> None:
        """``reasoning`` replaces turn 1's assistant choice, e.g. with a provider refusal."""
        self._reasoning: dict[str, Any] = reasoning or {
            "message": {"role": "assistant", "content": _REASONING},
            "finish_reason": "stop",
        }
        self._stored: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one chat call: live on first sight of these bytes, from the cache after."""
        assert request.url.path == _CHAT, f"unexpected gateway request {request.url.path}"
        body: dict[str, Any] = json.loads(request.content)
        keyed: dict[str, Any] = {name: value for name, value in body.items() if name != "cache"}
        key: str = hashlib.sha256(
            json.dumps(keyed, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        status: str = "hit" if key in self._stored else "miss"
        self.calls.append((status, body))
        if status == "miss":
            commit: bool = _TRIGGER_MARK in _user_text(body)
            choice: dict[str, Any] = (
                {"message": {"role": "assistant", "content": "B"}, "finish_reason": "stop"}
                if commit
                else self._reasoning
            )
            self._stored[key] = {
                "choices": [choice],
                "usage": {"prompt_tokens": 40, "completion_tokens": 20},
            }
        return httpx.Response(200, json=self._stored[key], headers={"X-AIGW-Cache": status})

    def commits(self) -> list[tuple[str, dict[str, Any]]]:
        """The turn-2 calls seen so far, each with the cache status it was served under."""
        return [(status, body) for status, body in self.calls if _TRIGGER_MARK in _user_text(body)]


def _user_text(body: dict[str, Any]) -> str:
    """The text of a chat request's user messages."""
    return "\n".join(
        str(message.get("content") or "")
        for message in body.get("messages", [])
        if message.get("role") == "user"
    )


def _assets(root: Path) -> None:
    """Prepare a one-Case MedXpertQA bundle whose key is B."""
    emit(
        [
            {
                "id": "Text-0",
                "question": "Case one: pick B",
                "options": {"A": "a", "B": "b"},
                "label": "B",
            }
        ],
        root / "medxpert",
    )


async def _run(gateway: CachingGateway, assets: Path) -> dict[str, Any]:
    """One whole one-Case MedXpertQA run on the production executor; returns its result."""
    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_MODEL,
            models=(ModelSpec(id=_MODEL),),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    ) as client:
        executor = build_executor(
            {},
            config,
            client=client,
            benchmarks=BenchmarkRegistry((MEDXPERT,)),
            benchmark_assets_root=assets,
        )
        expression: str = link_candidate(_CANDIDATE, MEDXPERT.build(1))
        frames: list[Any] = [frame async for frame in executor.execute(expression)]
    completed = frames[-1]
    assert isinstance(completed, Completed), completed
    assert completed.result.body is not None
    return json.loads(completed.result.body)


@pytest.mark.asyncio
async def test_a_rerun_sends_byte_identical_commit_turn_whatever_turn_one_accounting_says(
    tmp_path: Path,
) -> None:
    """INVARIANT: turn 2's bytes depend only on the question, the reasoning text and the trigger.

    Run 1 makes turn 1 as a live call (tokens, cost, a cache miss). Run 2 gets turn 1 as a cache
    hit, which the Engine accounts as zero tokens, zero cost and "hit". Both runs must send the
    same turn-2 request, or the rerun pays for every commit again and can draw another letter.
    """
    _assets(tmp_path)
    gateway = CachingGateway()

    first: dict[str, Any] = await _run(gateway, tmp_path)
    rerun: dict[str, Any] = await _run(gateway, tmp_path)

    # The stand-in did its job: run 1 was all live calls, and run 2's turn 1 was a cache hit.
    assert [status for status, _ in gateway.calls[:3]] == ["miss", "miss", "hit"]
    (_, live_commit), (rerun_status, rerun_commit) = gateway.commits()
    assert json.dumps(rerun_commit, sort_keys=True) == json.dumps(live_commit, sort_keys=True)
    # What the researcher sees: the rerun's commit is served from the cache, and grades the same.
    assert rerun_status == "hit"
    assert rerun["score"] == first["score"] == 1.0


@pytest.mark.asyncio
async def test_the_commit_turn_carries_the_reasoning_text_and_none_of_the_record(
    tmp_path: Path,
) -> None:
    """INVARIANT: the model reads its own turn-1 answer, never the bookkeeping around it.

    The record's status, finish reason and accounting are the Engine's notes about the call. In
    the prompt they are noise in the exam, and they are what made a rerun's bytes differ.
    """
    _assets(tmp_path)
    gateway = CachingGateway()

    await _run(gateway, tmp_path)

    ((_, commit),) = gateway.commits()
    # OME-1980: the reasoning text is the model's own assistant turn in the chat turn 2 continues.
    assert commit["messages"] == [
        {"role": "system", "content": "Answer the question."},
        {"role": "user", "content": _PROMPT},
        {"role": "assistant", "content": _REASONING},
        # OME-2018: the last message opens with the reply rule, then the trigger.
        {"role": "user", "content": f"{COMMIT_INSTRUCTION}\n\n{_TRIGGER}"},
    ]
    for key in _RECORD_ONLY_KEYS:
        assert key not in json.dumps(commit["messages"]), f"the commit turn leaked {key!r}"


@pytest.mark.asyncio
async def test_a_refused_turn_one_still_reaches_the_commit_turn_with_empty_reasoning(
    tmp_path: Path,
) -> None:
    """INVARIANT: a refusal in turn 1 does not end the Case; the commit letter is still graded.

    That was the outcome before this change (turn 2 then carried the refusal inside the record).
    A refused record has no answer text, so turn 2 carries an empty reasoning: the same bytes on
    every run, and nothing from the record.
    """
    _assets(tmp_path)
    gateway = CachingGateway(
        reasoning={
            "message": {"role": "assistant", "content": None, "refusal": "I cannot help."},
            "finish_reason": "stop",
        }
    )

    result: dict[str, Any] = await _run(gateway, tmp_path)

    ((_, commit),) = gateway.commits()
    # OME-1980 (owner's call): no answer text, no assistant message; the trigger still follows.
    assert [message["role"] for message in commit["messages"]] == ["system", "user", "user"]
    assert "I cannot help." not in json.dumps(commit["messages"])
    assert result["score"] == 1.0


@pytest.mark.asyncio
async def test_a_failed_turn_one_fails_the_case_before_any_commit_turn(tmp_path: Path) -> None:
    """INVARIANT: a turn 1 that errors ends the Case; no commit call is paid for after it.

    Unchanged by OME-1786, and pinned here because the reasoning-text route now sits between
    the turns: it must never turn a failed turn 1 into an empty reasoning and a graded guess.
    """
    _assets(tmp_path)
    # WHY "length" with no content: the model ran out of tokens, which the Engine reports as a
    # failed call (`model_token_cap`), not as an answer.
    gateway = CachingGateway(
        reasoning={"message": {"role": "assistant", "content": None}, "finish_reason": "length"}
    )

    result: dict[str, Any] = await _run(gateway, tmp_path)

    assert gateway.commits() == []
    (case,) = result["cases"]
    assert case["status"] == "failed"
    assert [failure["code"] for failure in case["failures"]] == ["model_token_cap"]


async def _always_b(model: str, failing: bool) -> httpx.Response:
    """A provider stand-in for the frozen-copy gateway: every call, either turn, answers B."""
    return _completion("B")


@pytest.mark.asyncio
async def test_a_scored_case_replays_from_its_frozen_copy(tmp_path: Path) -> None:
    """INVARIANT: a Case that scored in a capture run scores the same when its copy is replayed.

    This is where the defect was first seen (OME-1775's tests): a frozen copy stores each reply
    under a digest of its request, the replayed turn 1 is accounted as a hit, and turn 2 then
    asked for a request the copy never stored, so the Case failed with ``frozen_copy_miss``.
    The gateway stand-in is that test module's, which keeps a copy the way the real one does.
    """
    _copy_assets(tmp_path, cases=1)
    gateway = CopyGateway(_always_b)

    captured, _ = await _copy_run(gateway, {CAPTURE: "1"}, _CANDIDATE, (_MODEL,), tmp_path, cases=1)
    replayed, capture = await _copy_run(
        gateway, {REPLAY_FROZEN_COPY: COPY}, _CANDIDATE, (_MODEL,), tmp_path, cases=1
    )

    assert _case_outcomes(replayed) == _case_outcomes(captured) == [(1, "scored", 1.0, [])]
    assert capture == {"capture.replay": COPY}


def _reasoning_text_reply(record: str) -> str:
    """The assistant text the commit-chat route writes for one turn-1 record ("" for none)."""
    context: str = json.dumps({"prompt": _PROMPT, "reasoning": record, "trigger": _TRIGGER})
    chat: dict[str, Any] = json.loads(
        _commit_chat(Request(path=COMMIT_CHAT_ROUTE, context=context, intent="1", params={}))
    )
    return "".join(m["content"] for m in chat["messages"] if m["role"] == "assistant")


def test_the_commit_chat_route_carries_the_answer_text_alone() -> None:
    """The route is the one place a turn-1 record becomes turn-2 prompt text."""
    record: str = encode_candidate_invocation("I think B.", "stop", None)

    assert _reasoning_text_reply(record) == "I think B."


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(encode_candidate_invocation("", "stop", "I cannot help."), id="refused"),
        pytest.param(encode_candidate_invocation("", "stop", None), id="empty-answer"),
        pytest.param(
            encode_candidate_invocation("", None, None, abstained=True), id="fusion-abstained"
        ),
    ],
)
def test_a_turn_one_without_answer_text_gives_the_commit_turn_empty_reasoning(
    record: str,
) -> None:
    """INVARIANT: no answer text means no assistant message, never the record itself.

    A refused, empty or abstained (Fusion) turn 1 has an empty output. Falling back to the
    record would put the accounting back into the prompt for exactly these Cases.
    """
    assert _reasoning_text_reply(record) == ""


#: Turn-1 values that are not exactly a Candidate's result record.
_MALFORMED_RECORDS: dict[str, str] = {
    "plain-text": "I think B.",
    "not-an-object": '["I think B."]',
    "another-schema": '{"schema":"someone.else.v1","output":"I think B."}',
    # A record cut short: the right schema, the answer and the outcome fields missing.
    "missing-fields": '{"schema":"screamingface.candidate-invocation.v1","status":"completed"}',
    "unknown-field": encode_candidate_invocation("I think B.", "stop", None)[:-1] + ',"extra":1}',
}


@pytest.mark.parametrize("record", _MALFORMED_RECORDS.values(), ids=_MALFORMED_RECORDS.keys())
def test_a_malformed_turn_one_record_is_refused_not_read_as_reasoning(record: str) -> None:
    """INVARIANT: only an exact Candidate result record becomes turn-2 prompt text.

    A lenient read has two bad endings: it hands the raw value on (accounting and all, the
    defect of OME-1786), or it reads "no answer" and lets the model commit on a reasoning it
    never wrote. The route refuses loudly instead, with the Candidate-contract failure code.
    """
    with pytest.raises(ResolutionError) as refused:
        _reasoning_text_reply(record)

    assert refused.value.code == "candidate_contract_error"
    assert refused.value.permanent


@pytest.mark.asyncio
async def test_a_malformed_turn_one_record_fails_the_case_before_any_commit_turn(
    tmp_path: Path,
) -> None:
    """INVARIANT: a turn 1 the Engine cannot read ends the Case; nothing is committed or graded.

    The stand-in replaces the Engine's own Candidate route, the only way to hand the protocol
    a record the real route would never write: its first call (turn 1) returns a record cut
    short, and any later call would be the commit turn.
    """
    _assets(tmp_path)
    node = Url4Node("malformed-turn-one")
    MEDXPERT.install(node, tmp_path)
    calls: list[str] = []

    @node.endpoint(CANDIDATE_ROUTE)
    def candidate(request: Request) -> str:
        calls.append(request.context)
        return _MALFORMED_RECORDS["missing-fields"]

    try:
        result: dict[str, Any] = json.loads(
            (await node.evaluate(link_candidate(_CANDIDATE, MEDXPERT.build(1)))).text
        )
    finally:
        await node.aclose()

    assert len(calls) == 1, "the commit turn ran on a turn-1 record nobody could read"
    (case,) = result["cases"]
    assert case["status"] == "failed"
    assert [failure["code"] for failure in case["failures"]] == ["candidate_contract_error"]
    assert case["grade"]["score"] is None


def test_the_commit_turn_change_moved_the_published_revision() -> None:
    """INVARIANT: changed prompt bytes are a changed exam, so old and new scores never mix.

    The turn-2 input shape is hashed through the protocol constant: restoring an old constant
    must compute the id that exam published.
    """
    assert REVISION == FINGERPRINT not in (_RECORD_CARRYING_REVISION, _JSON_MESSAGE_REVISION)
    # OME-2018: those exams sent no reply rule, so they are computed with none.
    assert (
        compute_revision(protocol_revision="two-turn-cot-v1", commit_instruction="")
        == _RECORD_CARRYING_REVISION
    )
    assert (
        compute_revision(protocol_revision="two-turn-cot-v2", commit_instruction="")
        == _JSON_MESSAGE_REVISION
    )


# The id MedXpertQA published before OME-2018: its turn 2 sent the bare trigger.
_BARE_TRIGGER_REVISION = "952ea002b0f5e3b0"


def test_stating_the_reply_rule_moved_the_published_revision() -> None:
    """INVARIANT: an instruction added to turn 2 is a changed exam, so it gets its own id.

    Restoring the bare-trigger exam (its protocol constant, and no reply rule) must compute the
    id it published.
    """
    assert REVISION == FINGERPRINT != _BARE_TRIGGER_REVISION
    assert (
        compute_revision(protocol_revision="two-turn-cot-v3", commit_instruction="")
        == _BARE_TRIGGER_REVISION
    )


def test_rewording_the_reply_rule_moves_the_revision_by_itself() -> None:
    """INVARIANT: the reply rule is prompt text, so a changed word is a changed exam.

    Nobody has to remember to bump the protocol constant: the text is a hashed input, like the
    two prompt templates. Without this, a reworded rule with an updated test literal would keep
    the old id on a different exam (review of PR 2042).
    """
    reworded: str = compute_revision(commit_instruction="Reply with the option letter only.")

    assert reworded != REVISION
    assert compute_revision() == REVISION
