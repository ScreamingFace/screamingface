"""OME-1980: MedXpertQA's commit turn continues the chat, answered by whoever wrote turn 1.

FEATURE: MedXpertQA two-turn protocol. Turn 1 reasons; turn 2 (the commit) asks the model to
finish "Therefore, among A through J, the answer is", and the grader reads the first standalone
letter of the reply.

STORY: as a researcher submitting a single model or a Fusion, my commit turn is the official
harness's four-message chat, so my model finishes its own sentence ("D.") instead of starting a
new essay whose first capital letter is graded; and my Fusion's commit is written by its
synthesizer alone, so its members are not billed twice and cannot overturn its answer.

These tests cover the two builders (who answers, and what chat they continue) with hand-written
recipe text, and the whole Case on the production executor with a recording gateway stand-in.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate
from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.medxpert.commit import commit_chat, commit_recipe
from screamingface_engine.benchmarks.medxpert.definition import COMMIT_CHAT_ROUTE, MEDXPERT
from screamingface_engine.benchmarks.medxpert.prepare import emit
from screamingface_engine.benchmarks.medxpert.prompts import COMMIT_INSTRUCTION
from screamingface_engine.benchmarks.medxpert.runtime import _commit_chat
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from url4.core.errors import ResolutionError
from url4.core.nodes import Expression, RelExpr, Source, Text
from url4.core.parser import build
from url4.peer.server import Request
from url4.streaming.interfaces import Completed

_PROMPT = "Q: Case one: pick B\nA: Let's think step by step."
_TRIGGER = "Therefore, among A through B, the answer is"
#: Turn 2's last message since OME-2018: the reply rule, a blank line, the harness's trigger.
_COMMIT_MESSAGE = f"{COMMIT_INSTRUCTION}\n\n{_TRIGGER}"
_SYNTHESIS_PROMPT = "Synthesize the strongest answer."
#: The SDK's compiled shapes, written out (see the SDK's `compile_candidate`): a solo model, a
#: two-member Fusion with a synthesizer on its own model, and a Vote, whose final step is ALSO
#: named `synthesis_1` but is the Engine's combine step.
_SOLO = "(model_1:0.0:/prov/solo($input)!'Answer the question.')!'$model_1'"
_FUSION = (
    "(model_1:0.0:/prov/a($input)!'Answer the question.', "
    "model_2:0.0:/prov/b($input)!'Answer the question.', "
    "synthesis_1:0.0:/prov/s?temperature=0.3&q=({input: '$input', outputs: "
    f"{{member_1: '$model_1', member_2: '$model_2'}}}})!'{_SYNTHESIS_PROMPT}')!'$synthesis_1'"
)
_VOTE = (
    "(model_1:0.0:/prov/a($input)!'Answer.', model_2:0.0:/prov/b($input)!'Answer.', "
    f"synthesis_1:0.0:{COMBINE_ROUTE}?binding=synthesis_1&q=({{input: '$input', outputs: "
    "{member_1: '$model_1', member_2: '$model_2'}})!'vote')!'$synthesis_1'"
)


def _model_routes(path: str) -> bool:
    """Stand-in for the world's model routes: every `/prov/...` path, never the combine step."""
    return path.startswith("/prov/")


def _root(recipe: str) -> Expression:
    """Parse recipe text into its root expression."""
    root = build(recipe)
    assert isinstance(root, Expression)
    return root


def _call(recipe: str, name: str) -> RelExpr:
    """The call a named root step makes."""
    (step,) = [s for s in _root(recipe).sources if isinstance(s, Source) and s.name == name]
    assert isinstance(step.value, RelExpr)
    return step.value


# --- who answers turn 2 -----------------------------------------------------------------------


def test_a_fusion_commits_with_its_synthesizer_alone_and_without_the_synthesis_prompt() -> None:
    """INVARIANT: the one model that wrote the turn-1 answer is the one that commits.

    The members are not called again (5 calls per Case for a three-member Fusion, not 8), and
    the synthesis prompt goes, because on turn 2 there is no panel to synthesize: the
    synthesizer reads the same chat a single model reads. Its own route settings stay.
    """
    shortcut: str = commit_recipe(_FUSION, _model_routes)

    root = _root(shortcut)
    assert [s.name for s in root.sources if isinstance(s, Source)] == ["synthesis_1"]
    call = _call(shortcut, "synthesis_1")
    assert (call.path, call.params, call.context, call.intent) == (
        "/prov/s",
        (("temperature", "0.3"),),
        "$input",
        Text(""),
    )
    assert _SYNTHESIS_PROMPT not in shortcut


def test_a_solo_model_commits_with_itself_under_its_own_instruction() -> None:
    """A single model keeps the instruction it answered turn 1 under; nothing else changes."""
    call = _call(commit_recipe(_SOLO, _model_routes), "model_1")

    assert (call.path, call.context, call.intent) == (
        "/prov/solo",
        "$input",
        Text("Answer the question."),
    )


def test_a_vote_runs_whole_because_its_synthesis_step_is_the_engines_combine_step() -> None:
    """INVARIANT: a step NAMED like a model step but calling an Engine route is not a model.

    A compiled Vote's final step is `synthesis_1` on the combine route. Taking the shortcut would
    send the commit chat to a vote over nothing; instead every member answers the chat again.
    """
    assert commit_recipe(_VOTE, _model_routes) == _VOTE


@pytest.mark.parametrize(
    "recipe",
    [
        pytest.param("not url4 (", id="unparsable"),
        pytest.param(
            "(model_1:0.0:/prov/a($input)!'Answer.')!'Answer: $model_1'", id="prose-root-intent"
        ),
        pytest.param(
            "(loop_candidate:0.0:(model_1:0.0:/prov/a($input)!'A.')!'$model_1')!'$loop_candidate'",
            id="opaque-corrective-loop",
        ),
    ],
)
def test_any_other_recipe_runs_whole(recipe: str) -> None:
    """Anything the shortcut cannot prove is one model call runs whole, as on turn 1."""
    assert commit_recipe(recipe, _model_routes) == recipe


def test_the_shortcut_keeps_the_candidates_budget() -> None:
    """INVARIANT: the Candidate's caps still bind on turn 2 (`_sf_budget` stays in the recipe)."""
    budgeted: str = _FUSION.replace(
        "(model_1:0.0:", "(_sf_budget:0.0:'{\"usd\": 1.5}', model_1:0.0:", 1
    )

    names = [
        s.name
        for s in _root(commit_recipe(budgeted, _model_routes)).sources
        if isinstance(s, Source)
    ]

    assert names == ["_sf_budget", "synthesis_1"]


#: Real Client SDK output, so a compiler change that moves the shape fails here instead of
#: silently sending every Fusion down the whole-recipe path (the file says how it was made).
_SDK_RECIPES: dict[str, str] = {
    name: entry["url4"]
    for name, entry in json.loads(
        (Path(__file__).parents[1] / "fixtures" / "medxpert_sdk_compiled_recipes.json").read_text()
    )["recipes"].items()
}
_SDK_MEMBER_PROMPT = (
    "Answer the request accurately and completely. "
    "Follow every instruction and formatting constraint in the request."
)


@pytest.mark.parametrize(
    ("shape", "sources", "writer", "instruction"),
    [
        pytest.param("solo", ["model_1"], "/prov/a", _SDK_MEMBER_PROMPT, id="solo"),
        pytest.param("fusion", ["synthesis_1"], "/prov/s", "", id="fusion"),
        pytest.param(
            "budgeted_fusion", ["_sf_budget", "synthesis_1"], "/prov/s", "", id="budgeted-fusion"
        ),
        pytest.param("rank_then_writer", ["model_4"], "/prov/w", "", id="rank-then-writer"),
    ],
)
def test_sdk_compiled_recipes_commit_with_the_one_model_that_wrote_turn_one(
    shape: str, sources: list[str], writer: str, instruction: str
) -> None:
    """INVARIANT: on real SDK output, only the final writer commits, reading the chat.

    It keeps its instruction only when it read the Case on turn 1. A writer after Rank compiles
    to `model_4`, not `synthesis_N`, and its instruction ("Write the final answer to the input
    from the selected answers.") would be sent as the commit's system message with no selected
    answers, so it goes, as a synthesizer's does.
    """
    shortcut: str = commit_recipe(_SDK_RECIPES[shape], _model_routes)

    assert [s.name for s in _root(shortcut).sources if isinstance(s, Source)] == sources
    call = _call(shortcut, sources[-1])
    assert (call.path, call.context, call.intent) == (writer, "$input", Text(instruction))


# --- the chat turn 2 continues ----------------------------------------------------------------


def test_the_commit_chat_is_the_harness_four_message_layout_without_the_system_message() -> None:
    """The official harness: user CoT prompt, assistant reasoning, user trigger (after system).

    The system message is the Candidate's own instruction, added by the model connector.
    """
    chat: dict[str, Any] = json.loads(commit_chat(_PROMPT, "B is right.", _TRIGGER))

    assert chat == {
        "schema": CANDIDATE_INPUT_SCHEMA,
        "messages": [
            {"role": "user", "content": _PROMPT},
            {"role": "assistant", "content": "B is right."},
            {"role": "user", "content": _COMMIT_MESSAGE},
        ],
    }


def test_turn_two_states_its_reply_rule_and_still_ends_on_the_unfinished_sentence() -> None:
    """INVARIANT: the model is TOLD to reply with the option letter only, and the message still
    ends on the trigger, so the letter is the next thing it writes.

    With the bare trigger the model read turn 2 as a new question: the first paid run of
    revision 952ea002b0f5e3b0 got 277 and 496 tokens of new reasoning on 2 of 2 Cases, and one
    Case changed its turn-1 answer from the key to a wrong letter. The exact bytes are pinned
    because they are the exam: change this line and the protocol revision must move with it.
    """
    chat: dict[str, Any] = json.loads(commit_chat(_PROMPT, "B is right.", _TRIGGER))

    last: str = chat["messages"][-1]["content"]
    assert last == (
        "Finish the sentence below with the option letter only, and nothing else."
        "\n\nTherefore, among A through B, the answer is"
    )
    assert last.endswith(_TRIGGER)


@pytest.mark.parametrize("answer", ["", "  \n"], ids=["empty", "whitespace-only"])
def test_an_empty_turn_one_answer_leaves_out_the_assistant_message(answer: str) -> None:
    """Owner's call (OME-1980): some providers refuse an empty assistant message.

    A whitespace-only answer is empty too: the harness strips every reply before it becomes the
    assistant turn, and a provider refuses a blank message like an empty one.
    """
    chat: dict[str, Any] = json.loads(commit_chat(_PROMPT, answer, _TRIGGER))

    assert [m["role"] for m in chat["messages"]] == ["user", "user"]


def test_the_assistant_turn_is_stripped_like_the_harness_strips_it() -> None:
    """The harness sends `response.strip()` as the assistant turn (eval/main.py, 5f1db162)."""
    chat: dict[str, Any] = json.loads(commit_chat(_PROMPT, "\n B is right. \n", _TRIGGER))

    assert chat["messages"][1] == {"role": "assistant", "content": "B is right."}


def test_a_broken_case_row_is_the_benchmarks_fault_not_the_candidates() -> None:
    """INVARIANT: an empty prompt or trigger comes from this Benchmark's own rows.

    Blaming the Candidate (`candidate_contract_error`) would send a researcher to debug a
    recipe that did nothing wrong.
    """
    context: str = json.dumps(
        {"prompt": "", "reasoning": encode_candidate_invocation("B.", "stop", None), "trigger": "T"}
    )

    with pytest.raises(ResolutionError) as refused:
        _commit_chat(Request(path=COMMIT_CHAT_ROUTE, context=context, intent="1", params={}))

    assert refused.value.code == "benchmark_definition_error"


# --- the whole Case on the production executor ------------------------------------------------


class RecordingGateway:
    """An AI Gateway stand-in: members answer A, the synthesizer and solo models answer D.

    Every chat body is recorded with the model it named, so a test can read what turn 2 sent.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one chat call; turn 1 reasons, a reply to the trigger is the letter."""
        body: dict[str, Any] = json.loads(request.content)
        self.calls.append(body)
        last: str = str(body["messages"][-1]["content"])
        commit: bool = last.endswith("the answer is")  # OME-2018: the reply rule comes first
        member: bool = body["model"] in ("prov/a", "prov/b")
        text: str = ("A" if member else "B") if commit else "Reasoning... so the answer is B."
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    def commits(self) -> list[dict[str, Any]]:
        """The turn-2 calls: the ones whose last message is the trigger."""
        return [
            c for c in self.calls if str(c["messages"][-1]["content"]).endswith("the answer is")
        ]


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


async def _run(candidate: str, gateway: RecordingGateway, assets: Path) -> dict[str, Any]:
    """One whole one-Case MedXpertQA run on the production executor; returns its result."""
    models: tuple[str, ...] = ("prov/solo", "prov/a", "prov/b", "prov/s")
    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model="prov/solo",
            models=tuple(ModelSpec(id=model) for model in models),
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
        frames: list[Any] = [
            frame async for frame in executor.execute(link_candidate(candidate, MEDXPERT.build(1)))
        ]
    completed = frames[-1]
    assert isinstance(completed, Completed), completed
    assert completed.result.body is not None
    return json.loads(completed.result.body)


@pytest.mark.asyncio
async def test_a_solo_models_commit_turn_continues_its_own_chat(tmp_path: Path) -> None:
    """INVARIANT: the model sees its own reasoning as its own assistant turn, then the trigger.

    The request the provider gets is the harness's layout: system (the Candidate's own
    instruction), user (the turn-1 prompt), assistant (the turn-1 answer), user (the trigger).
    Before OME-1980 it was one user message holding a JSON object, and the model explained again.
    """
    _assets(tmp_path)
    gateway = RecordingGateway()

    result: dict[str, Any] = await _run(_SOLO, gateway, tmp_path)

    (commit,) = gateway.commits()
    assert commit["messages"] == [
        {"role": "system", "content": "Answer the question."},
        {"role": "user", "content": "Q: Case one: pick B\nA: Let's think step by step."},
        {"role": "assistant", "content": "Reasoning... so the answer is B."},
        {"role": "user", "content": _COMMIT_MESSAGE},
    ]
    assert result["score"] == 1.0


@pytest.mark.asyncio
async def test_a_fusion_commits_with_its_synthesizer_alone_and_keeps_every_members_row(
    tmp_path: Path,
) -> None:
    """INVARIANT: a Fusion's commit is one call to its synthesizer; the record keeps its members.

    Members here would answer A on turn 2. The synthesizer answers B. Before OME-1980 the whole
    Fusion ran again (6 calls for this two-member Fusion); now turn 2 is one call, the members
    cannot overturn the answer, and the graded record still shows each member's turn-1 row with
    what its one call cost, so the SDK's per-member cost view stays known.
    """
    _assets(tmp_path)
    gateway = RecordingGateway()

    result: dict[str, Any] = await _run(_FUSION, gateway, tmp_path)

    assert [c["model"] for c in gateway.calls] == ["prov/a", "prov/b", "prov/s", "prov/s"]
    (commit,) = gateway.commits()
    assert [m["role"] for m in commit["messages"]] == ["user", "assistant", "user"]
    assert _SYNTHESIS_PROMPT not in json.dumps(commit)
    (case,) = result["cases"]
    assert result["score"] == 1.0
    rows = {row["operation_id"]: row for row in case["operations"]}
    assert list(rows) == ["op_model_1", "op_model_2", "op_synthesis_1"]
    assert rows["op_model_1"]["output"] == "Reasoning... so the answer is B."
    assert rows["op_model_1"]["accounting"] is not None
    assert rows["op_synthesis_1"]["output"] == "B"


#: The digest of the turn-1 request (model + messages, the AI Gateway cache's own inputs) that
#: MedXpertQA sent for `_SOLO` on a one-Case bundle whose question is "Case one: pick B — é",
#: computed on 2026-11-24 at the commit that published `1e5a3b8a461a52f7`, where today's five
#: leaderboard entries ran. Same bytes, same cache entry.
_TURN_ONE_DIGEST_AT_1E5A3B8A = "1b0168ac5364f89d6a3ab5ec260161bb2967bf7204027802418080ff9d999f61"


@pytest.mark.asyncio
async def test_turn_one_sends_the_bytes_the_leaderboard_entries_were_cached_under(
    tmp_path: Path,
) -> None:
    """INVARIANT: OME-1980 leaves turn 1 byte-identical, so a rerun answers it from the cache.

    The shared request cache keys on the request body. If turn 1 changed, rerunning the five
    entries on the new revision would pay for all of turn 1 again (the owner kept the SDK's
    system message for exactly this reason). Non-ASCII in the question guards the encoding.
    """
    emit(
        [
            {
                "id": "Text-0",
                "question": "Case one: pick B — é",
                "options": {"A": "a", "B": "b"},
                "label": "B",
            }
        ],
        tmp_path / "medxpert",
    )
    gateway = RecordingGateway()

    await _run(_SOLO, gateway, tmp_path)

    turn_one: dict[str, Any] = {k: v for k, v in gateway.calls[0].items() if k != "cache"}
    digest: str = hashlib.sha256(
        json.dumps(turn_one, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert digest == _TURN_ONE_DIGEST_AT_1E5A3B8A


#: A recipe the shortcut cannot lift: its result comes from a nested group, not a root model
#: step, the shape of a corrective loop or any step the Engine cannot see inside.
_NESTED = (
    "(wrap_1:0.0:(model_1:0.0:/prov/solo($input)!'Answer the question.')!'$model_1')!'$wrap_1'"
)


@pytest.mark.asyncio
async def test_a_recipe_the_shortcut_cannot_lift_commits_whole_on_the_same_chat(
    tmp_path: Path,
) -> None:
    """INVARIANT: the whole-recipe path still reaches the Candidate route and continues the chat.

    Every recipe that is not one model call (Vote, Gate, a corrective loop) takes this path; it
    was the only path before OME-1980, so a break in how the returned text reaches the Candidate
    route must fail here, not pass silently.
    """
    _assets(tmp_path)
    gateway = RecordingGateway()

    result: dict[str, Any] = await _run(_NESTED, gateway, tmp_path)

    assert len(gateway.calls) == 2
    (commit,) = gateway.commits()
    assert [m["role"] for m in commit["messages"]] == ["system", "user", "assistant", "user"]
    assert result["score"] == 1.0
