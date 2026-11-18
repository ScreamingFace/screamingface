"""POST /v1/chat/completions through the `openai` SDK, on the local in-process App (U4).

FEATURE: OpenAI-compatible Engine API, unit U4 (prd/chat-completion.md CC-22, CC-23, CC-29, CC-30,
CC-31). Plan decision D1: these are Engine integration tests. The App runs the real executor in
process, a fake gateway (an `httpx.MockTransport`) answers each model call, and the `openai` SDK
is the client. No replay lane, no network: each URL that could leave the machine uses `.invalid`.

STORY: as a developer with an OpenAI client, I point its base URL at the Engine and send a model id
or a URL4 recipe as `model`; I get a normal chat completion back.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import openai
import pytest
from _chat_sdk_stack import ChatStack, chat_stack
from fastapi.testclient import TestClient

from url4 import RelExpr, expr, render, src, text

SECRET = "chat-completions-sdk-secret-000000000"
EMAIL = "dev@example.com"
MEMBER, SYNTH, COLON = "prov/a", "prov/b", "prov/c:free"
# WHY: GET /v1/models lists a gateway id in its route form, `:` written as `~` (C3, CC-S32).
LISTED = (MEMBER, SYNTH, "prov/c~free")
REPLIES = {MEMBER: "member answer", SYNTH: "Paris", COLON: "free answer"}
# A model step on a remote node: url4 refuses it before any I/O (peer/server.py remote guard).
REMOTE_RECIPE = "(model_1:0.0:url4://remote.invalid/v1($input)!'')!'$model_1'"


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[ChatStack]:
    """The local App over the real executor, a filesystem blob store and the fake gateway."""
    with chat_stack(
        tmp_path,
        secret=SECRET,
        replies=REPLIES,
        listed=LISTED,
        known={*LISTED, COLON},
        default_model=MEMBER,
    ) as built:
        yield built


def _sdk(http: TestClient, *, identity: bool = True) -> openai.OpenAI:
    headers = {"X-User-Email": EMAIL} if identity else {}
    return openai.OpenAI(
        base_url="http://testserver/v1",
        api_key="unused",
        http_client=http,
        max_retries=0,
        default_headers=headers,
    )


def _fusion_recipe() -> str:
    """Two members on one route, then synthesis_1 on another route over both."""

    def member(name: str, answer: str) -> Any:
        return src(
            RelExpr(path="/" + MEMBER, context="$input", intent=text(answer)), name=name, weight=0.0
        )

    synthesis = src(
        RelExpr(path="/" + SYNTH, context="$model_1 $model_2", intent=text("Merge")),
        name="synthesis_1",
        weight=0.0,
    )
    return render(
        expr(
            member("model_1", "Answer A"),
            member("model_2", "Answer B"),
            synthesis,
            intent=text("$synthesis_1"),
        )
    )


def _extra(completion: Any) -> dict[str, Any]:
    extra = completion.model_extra or {}
    value = extra.get("screamingface")
    assert isinstance(value, dict), "the response has no screamingface field"
    return value


def test_local_stack_fusion_answers_openai_sdk_request(stack: ChatStack) -> None:
    """CC-22 (CC-S5): a local caller with no identity runs a Fusion URL4 through the SDK."""
    stack.app.state.runs_require_identity = False
    recipe = _fusion_recipe()

    completion = _sdk(stack.http, identity=False).chat.completions.create(
        model=recipe, messages=[{"role": "user", "content": "Capital of France?"}]
    )

    assert completion.id.startswith("chatcmpl-")
    assert completion.object == "chat.completion"
    assert completion.model == recipe
    assert completion.choices[0].message.content == REPLIES[SYNTH]
    assert completion.choices[0].finish_reason == "stop"
    # INVARIANT: usage and cost are the sum over ALL 3 model calls of the ensemble (contracts C9),
    # not the final call alone: each fake reply is 10 + 4 tokens and 0.001 credits.
    assert len(stack.gateway.seen) == 3
    usage = completion.usage
    assert usage is not None
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (30, 12, 42)
    extra = _extra(completion)
    assert extra["status"] == "answered"
    assert extra["cost_usd"] == "0.003"


def test_get_v1_models_is_unchanged(stack: ChatStack) -> None:
    """CC-23 (CC-S32): the SDK lists the catalog as GET /v1/models does; each id is a `model`."""
    sdk = _sdk(stack.http)

    listed = [model.id for model in sdk.models.list()]
    direct = stack.http.get("/v1/models", headers={"X-User-Email": EMAIL})

    assert direct.status_code == 200
    assert listed == [row["id"] for row in direct.json()["data"]]
    assert listed == list(LISTED)

    # C3: a listed id in its route form (`~`) is a valid `model` value, not a 404.
    completion = sdk.chat.completions.create(
        model="prov/c~free", messages=[{"role": "user", "content": "Hi"}]
    )
    assert completion.choices[0].message.content == REPLIES[COLON]
    assert [sent["model"] for sent in stack.gateway.seen] == [COLON]


def test_multi_turn_text_and_developer_role_pass_as_native_messages(stack: ChatStack) -> None:
    """CC-29 (CC-S30, D4): the model call gets the client messages as sent, no added system."""
    messages: list[Any] = [
        {"role": "system", "content": "Be brief."},
        {"role": "developer", "content": "Answer in French."},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Bonjour"},
        {"role": "user", "content": "Capital of France?"},
    ]

    completion = _sdk(stack.http).chat.completions.create(model=MEMBER, messages=messages)

    assert completion.choices[0].message.content == REPLIES[MEMBER]
    assert stack.gateway.messages_for(MEMBER) == [messages]


def test_picture_parts_reach_model_steps_as_v2_parts(stack: ChatStack) -> None:
    """CC-30 (CC-S31): a `data:` picture part reaches the model call unchanged."""
    picture = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
    content: list[Any] = [{"type": "text", "text": "what is this?"}, picture]

    _sdk(stack.http).chat.completions.create(
        model=MEMBER, messages=[{"role": "user", "content": content}]
    )

    sent = stack.gateway.messages_for(MEMBER)
    assert len(sent) == 1
    users = [m for m in sent[0] if m["role"] == "user"]
    assert any(isinstance(m["content"], list) and picture in m["content"] for m in users)


def test_remote_node_in_model_is_refused_as_on_get_q(stack: ChatStack) -> None:
    """CC-31 (CC-S33): a remote node in `model` fails as on GET /?q=, before any model call."""
    with pytest.raises(openai.APIStatusError) as caught:
        _sdk(stack.http).chat.completions.create(
            model=REMOTE_RECIPE, messages=[{"role": "user", "content": "Hi"}]
        )

    # WHY 502 internal_error: `x.remote_node_unsupported` is not a code the Engine vouches for,
    # so the terminal table gives its generic failed row (prd/chat-completion.md §3.2).
    assert caught.value.status_code == 502
    assert caught.value.response.json()["error"]["code"] == "internal_error"
    assert stack.gateway.seen == []

    token = stack.http.post("/token").json()["token"]
    on_get = stack.http.get(
        "/",
        params={"q": REMOTE_RECIPE},
        headers={"URL4-Capability": token, "X-User-Email": EMAIL},
    )

    assert on_get.status_code == 502
    assert on_get.json()["code"] == "internal_error"
    assert stack.gateway.seen == []
