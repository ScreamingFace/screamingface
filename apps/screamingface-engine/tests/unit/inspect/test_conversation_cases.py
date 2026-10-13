# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Conversation-shaped Cases (OME-1527, R14): a Case whose prompt is a chat the dataset wrote.

INVARIANT the suite defends: a fixed conversation is still ONE Candidate call, and it travels
as the candidate-input envelope byte for byte as hand-built healthbench's preparer wrote it,
so a migrated Benchmark's recorded calls replay as cache hits (OME-1527 decision 5). The same
text is what the Case Digest seals and what the scorer opens back into turns. A one-prompt
Case is untouched: it keeps its plain text, so no published revision moves.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.model import (  # noqa: E402
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.scorer import Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from inspect_ai.tool import ToolCall  # noqa: E402

from screamingface_engine.benchmarks.healthbench.prepare import envelope  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.capture import CaptureError, captured_case_records  # noqa: E402
from screamingface_engine_inspect.conversation_input import (  # noqa: E402
    conversation_input,
    conversation_messages,
)
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec, case_digest  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402
from screamingface_engine_inspect.single_shot import _cases  # noqa: E402

#: A healthbench-shaped conversation: the patient speaks, the assistant asks back, the
#: patient answers, and the Candidate writes the next turn. Non-ASCII on purpose, so an
#: escaping difference (``¿`` for ``¿``) cannot hide.
TURNS: list[dict[str, str]] = [
    {"role": "user", "content": "Mi rodilla duele — ¿qué hago?"},
    {"role": "assistant", "content": "¿Desde cuándo?"},
    {"role": "user", "content": "Dos días."},
]

#: What hand-built healthbench's ``envelope(case_messages(row))`` writes for TURNS — printed
#: once from that preparer and pasted here, never computed by the code under test.
HAND_BUILT_BYTES: str = (
    '{"schema":"screamingface.candidate-input.v1","messages":['
    '{"role":"user","content":"Mi rodilla duele — ¿qué hago?"},'
    '{"role":"assistant","content":"¿Desde cuándo?"},'
    '{"role":"user","content":"Dos días."}]}'
)

_KINDS: dict[str, Any] = {
    "system": ChatMessageSystem,
    "user": ChatMessageUser,
    "assistant": ChatMessageAssistant,
}

_UNSEALED: str = "0" * 64


def _spec() -> TaskReplayCasesSpec:
    """A declaration whose seal nothing compares; capture reads only its writer options."""

    return TaskReplayCasesSpec(task="stand_in:task", case_count=1, case_digest=_UNSEALED)


def _captured(messages: list[Any]) -> str:
    """Capture one Sample whose input is ``messages``, served by inspect's default generate."""

    task: Task = Task(dataset=MemoryDataset([Sample(input=messages, target="rest")]))
    return captured_case_records(task, _spec())[0]["case"]["input"]


def _chat(turns: list[dict[str, str]]) -> list[Any]:
    """TURNS as the inspect messages a local Task's Sample would hold."""

    return [_KINDS[turn["role"]](content=turn["content"]) for turn in turns]


# ── what capture writes ───────────────────────────────────────────────────────


def test_a_fixed_conversation_is_written_as_the_hand_built_envelope() -> None:
    """The headline guarantee: the Case input is the hand-built preparer's bytes, so the
    Candidate and a Fusion synthesizer (which pastes the input raw) see what they saw."""

    written: str = _captured(_chat(TURNS))

    assert written == HAND_BUILT_BYTES
    assert written == envelope(TURNS), "the literal must still be the hand-built preparer's"


def test_a_one_prompt_case_keeps_its_plain_text() -> None:
    """A system turn then one user turn is still one prompt, joined as before: those Cases,
    and every published revision built on them, do not move."""

    written: str = _captured(
        [ChatMessageSystem(content="Be brief."), ChatMessageUser(content="What is 6 times 7?")]
    )

    assert written == "Be brief.\n\nWhat is 6 times 7?"


def test_a_system_turn_inside_a_conversation_keeps_its_role() -> None:
    """In a conversation, the system turn is a turn: the envelope carries it by role, as the
    hand-built envelope would, instead of folding it into the first prompt."""

    written: str = _captured([ChatMessageSystem(content="You are a nurse."), *_chat(TURNS)])

    assert conversation_messages(written) == [
        {"role": "system", "content": "You are a nurse."},
        *TURNS,
    ]


def test_an_assistant_turn_that_calls_tools_is_refused() -> None:
    """A tool call is not text the Candidate can be shown; the Case is refused by name."""

    calling: ChatMessageAssistant = ChatMessageAssistant(
        content="Let me look.",
        tool_calls=[ToolCall(id="1", function="search", arguments={"q": "knee"})],
    )

    with pytest.raises(CaptureError, match="case 1: an assistant turn calls tools"):
        _captured([ChatMessageUser(content="Hi"), calling, ChatMessageUser(content="And?")])


def test_a_tool_turn_is_refused() -> None:
    with pytest.raises(CaptureError, match="case 1: the solver sent a tool message"):
        _captured(
            [
                ChatMessageUser(content="Hi"),
                ChatMessageTool(content="42", tool_call_id="1"),
                ChatMessageUser(content="And?"),
            ]
        )


# ── what the Case Digest seals ─────────────────────────────────────────────────


def test_the_case_digest_seals_every_turn() -> None:
    """Changing one earlier turn changes the seal: a re-import that drifts mid-conversation
    is refused like any other changed Case."""

    edited: list[dict[str, str]] = [TURNS[0], {"role": "assistant", "content": "¿Dónde?"}, TURNS[2]]

    def sealed(turns: list[dict[str, str]]) -> str:
        """The digest of one prepared Case whose input is ``turns``."""

        case: dict[str, Any] = {"id": 1, "case_id": "1", "input": conversation_input(turns)}
        return case_digest([{"case": case, "grading_material": {"target": "rest"}}])

    assert sealed(TURNS) != sealed(edited)


# ── what the Candidate is served ───────────────────────────────────────────────


def test_the_envelope_flag_serves_a_conversation_as_written(tmp_path: Path) -> None:
    """With ``candidate_input_envelope`` on (healthbench's single-prompt Cases need it), a
    plain Case is wrapped and a conversation Case, already the envelope, is never wrapped
    twice."""

    rows: list[dict[str, Any]] = [
        {"id": 1, "case_id": "1", "input": "Dos días."},
        {"id": 2, "case_id": "2", "input": HAND_BUILT_BYTES},
    ]
    (tmp_path / "cases.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    served: list[dict[str, Any]] = json.loads(_cases(tmp_path, envelope=True)())

    assert served[0]["input"] == envelope([{"role": "user", "content": "Dos días."}])
    assert served[1]["input"] == HAND_BUILT_BYTES


# ── what the scorer reads ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_scorer_reads_the_conversation_the_candidate_was_shown() -> None:
    """The scorer gets the turns back as inspect messages, in order and role, and inspect's
    ``input_text`` is the last user turn, as it would be under ``eval()``."""

    seen: dict[str, Any] = {}

    async def scorer(state: TaskState, target: Target) -> Score:
        seen["turns"] = [(message.role, message.text) for message in state.messages]
        seen["input"] = [(message.role, message.text) for message in state.input]  # type: ignore[union-attr]
        seen["input_text"] = state.input_text
        return Score(value=1.0)

    request: GradeRequest = GradeRequest(
        case_id=1,
        input=TextPayload(text=HAND_BUILT_BYTES),
        answer=TextPayload(text="Rest and ice it."),
        row={"case": {"status": "answered"}},
        material={"target": "rest"},
    )

    outcome = await inspect_grade_case(scorer)(request)

    expected: list[tuple[str, str]] = [(turn["role"], turn["content"]) for turn in TURNS]
    assert outcome.score == 1.0
    assert seen["turns"] == expected
    assert seen["input"] == expected
    assert seen["input_text"] == "Dos días."


# ── reading an input back ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prompt",
    ["What is 6 times 7?", '{"answer": 42}', "{not json", '["schema"]'],
)
def test_a_plain_prompt_is_never_read_as_a_conversation(prompt: str) -> None:
    """Only a JSON object naming the candidate-input schema is a conversation, the
    connector's own rule; any other text, JSON included, is a prompt as written."""

    assert conversation_messages(prompt) is None


@pytest.mark.parametrize(
    "broken",
    [
        '{"schema":"screamingface.candidate-input.v1","messages":[]}',
        '{"schema":"screamingface.candidate-input.v1","messages":[{"role":"developer","content":"x"}]}',
        '{"schema":"screamingface.candidate-input.v1","messages":[{"role":"user"}]}',
        '{"schema":"screamingface.candidate-input.v1","messages":[],"extra":1}',
    ],
)
def test_a_broken_conversation_is_refused_not_graded_as_a_prompt(broken: str) -> None:
    """A text that names the schema but breaks its shape is a damaged Case; reading it as a
    plain prompt would grade the Candidate against JSON it never saw."""

    with pytest.raises(ValueError, match="conversation"):
        conversation_messages(broken)
