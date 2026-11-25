"""`/route-answer` through the real executor: classify, select one branch, answer (OME-1822).

FEATURE: BYOM routing pilot (spec 3.2 to 3.5). One direct run reads the classifier's and each
branch's published metadata, classifies the caller's question once, takes the unique highest
label and asks that label's route once, with the unchanged question.

STORY: as a granted caller I name a routing profile and ask one question; the model bound to the
question's kind answers it, and I see which label and model were chosen and why.

INVARIANT: no unselected branch is ever called, and nothing reaches a branch unless the scores
name exactly the profile's labels with one highest. The preflight outcomes have their own module
(`test_routing_preflight.py`).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from frozen_copy_support import capture_scope, replay_scope
from routing_support import (
    CALLER,
    CHAT_PATH,
    CLASSIFICATIONS_PATH,
    CLASSIFIER,
    LABELS,
    MAX_TOKENS,
    MODELS,
    PROFILE,
    TEXT,
    Gateway,
    context,
    preflight_calls,
    query,
    revision,
    run_direct,
)

from screamingface_engine.request_scope import RequestScope
from screamingface_engine.world.gateway_endpoints import ROUTED_CALL_FAILED_MESSAGE

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]

_NOT_FOUND = "routing_profile_not_found"


# --- selection ------------------------------------------------------------------------------------


@pytest.mark.parametrize("label", LABELS)
async def test_each_label_selects_its_branch_and_calls_no_other(label: str) -> None:
    gateway = Gateway(top=label)

    document = (await run_direct(gateway)).document()

    assert gateway.calls() == [
        *preflight_calls(),
        ("POST", CLASSIFICATIONS_PATH, CLASSIFIER),
        ("POST", CHAT_PATH, MODELS[label]),
    ]
    assert document["selected"] == {"label": label, "model": MODELS[label]}
    assert document["answer"] == f"answer from {MODELS[label]}"


async def test_the_result_is_the_routed_answer_contract() -> None:
    order = [
        {"label": "math", "score": 0.02},
        {"label": "code", "score": 0.91},
        {"label": "general", "score": 0.07},
    ]
    gateway = Gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = lambda _: {
        "object": "classification",
        "model": CLASSIFIER,
        "contract": "classification-scores-v1",
        "scores": order,
    }

    document = (await run_direct(gateway)).document()

    assert document == {
        "object": "routed_answer",
        "contract": "routed-answer-v1",
        "profile": PROFILE,
        "revision": revision(),
        "policy": "unique-argmax-v1",
        "classification": {
            "model": CLASSIFIER,
            "contract": "classification-scores-v1",
            "scores": order,
        },
        "selected": {"label": "code", "model": MODELS["code"]},
        "answer": f"answer from {MODELS['code']}",
    }


async def test_a_tie_below_the_highest_score_still_selects() -> None:
    gateway = Gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = lambda _: {
        "object": "classification",
        "model": CLASSIFIER,
        "contract": "classification-scores-v1",
        "scores": [
            {"label": "general", "score": 0.5},
            {"label": "code", "score": 0.25},
            {"label": "math", "score": 0.25},
        ],
    }

    assert (await run_direct(gateway)).document()["selected"]["label"] == "general"


# --- exact bytes and identity ---------------------------------------------------------------------


async def test_the_input_reaches_the_classifier_and_the_branch_byte_for_byte() -> None:
    gateway = Gateway(top="code")

    await run_direct(gateway)

    assert gateway.posts(CLASSIFICATIONS_PATH) == [{"model": CLASSIFIER, "input": TEXT}]
    (chat,) = gateway.posts(CHAT_PATH)
    assert chat == {
        "model": MODELS["code"],
        "messages": [{"role": "user", "content": TEXT}],
        "max_tokens": MAX_TOKENS["code"],
    }


async def test_every_gateway_call_carries_the_callers_identity_and_no_key() -> None:
    gateway = Gateway()

    await run_direct(gateway)

    assert len(gateway.requests) == 6
    for request in gateway.requests:
        assert request.headers["X-User-Email"] == CALLER["X-User-Email"]
        assert "Authorization" not in request.headers


# --- scores ---------------------------------------------------------------------------------------


def _scored(*pairs: tuple[str, float]) -> Gateway:
    gateway = Gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = lambda _: {
        "object": "classification",
        "model": CLASSIFIER,
        "contract": "classification-scores-v1",
        "scores": [{"label": label, "score": score} for label, score in pairs],
    }
    return gateway


async def test_a_tied_highest_score_is_ambiguous_and_calls_no_branch() -> None:
    gateway = _scored(("general", 0.45), ("code", 0.45), ("math", 0.1))

    outcome = await run_direct(gateway)

    assert (outcome.code(), outcome.permanent()) == ("routing_ambiguous", True)
    assert gateway.posts(CHAT_PATH) == []


async def test_an_integer_and_a_float_of_one_value_tie() -> None:
    gateway = _scored(("general", 1), ("code", 1.0), ("math", 0))

    assert (await run_direct(gateway)).code() == "routing_ambiguous"
    assert gateway.posts(CHAT_PATH) == []


@pytest.mark.parametrize(
    "pairs",
    [
        pytest.param((("general", 0.1), ("code", 0.7), ("math", 0.1), ("legal", 0.1)), id="extra"),
        pytest.param((("general", 0.2), ("code", 0.8)), id="missing"),
        pytest.param((("general", 0.1), ("code", 0.8), ("maths", 0.1)), id="renamed"),
    ],
)
async def test_scores_must_name_exactly_the_profile_labels(
    pairs: tuple[tuple[str, float], ...],
) -> None:
    gateway = _scored(*pairs)

    outcome = await run_direct(gateway)

    assert outcome.code() == "routing_invalid_scores"
    assert gateway.posts(CHAT_PATH) == []


@pytest.mark.parametrize(
    "field",
    [
        pytest.param({"model": f"{CLASSIFIER}_other"}, id="model"),
        pytest.param({"contract": "classification-scores-v2"}, id="contract"),
    ],
)
async def test_a_result_for_another_model_or_contract_never_reaches_a_branch(
    field: dict[str, str],
) -> None:
    # WHY `aigateway_bad_response`: Unit 3 refuses a result outside its contract before the
    # routing handler sees it; the relay keeps that Engine code (spec 3.5, 6.1 C9).
    gateway = Gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = lambda _: {
        "object": "classification",
        "model": CLASSIFIER,
        "contract": "classification-scores-v1",
        "scores": [{"label": label, "score": 0.3} for label in LABELS],
        **field,
    }

    assert (await run_direct(gateway)).code() == "aigateway_bad_response"
    assert gateway.posts(CHAT_PATH) == []


# --- classifier and branch failures ---------------------------------------------------------------


async def test_a_classifier_the_caller_may_not_use_is_an_unknown_profile() -> None:
    gateway = Gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = httpx.Response(
        400, json={"detail": f"unknown provider: {CLASSIFIER.split('/')[0]}"}
    )

    outcome = await run_direct(gateway)

    assert outcome.code() == _NOT_FOUND
    assert CLASSIFIER not in str(outcome.error)
    assert gateway.posts(CHAT_PATH) == []


async def test_a_classifier_failure_is_relayed_and_calls_no_branch() -> None:
    gateway = Gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = httpx.Response(200, text="<html>")

    assert (await run_direct(gateway)).code() == "aigateway_bad_response"
    assert gateway.posts(CHAT_PATH) == []


async def test_a_branch_the_caller_may_not_use_is_an_unknown_profile() -> None:
    gateway = Gateway(top="math")
    gateway.script[(CHAT_PATH, MODELS["math"])] = httpx.Response(
        400, json={"detail": f"unknown provider: {MODELS['math'].split('/')[0]}"}
    )

    outcome = await run_direct(gateway)

    assert outcome.code() == _NOT_FOUND
    assert MODELS["math"] not in str(outcome.error)
    assert "/route-answer" not in str(outcome.error)


async def test_a_branch_failure_is_relayed_by_the_spec_policy() -> None:
    """Spec 3.5 and 6.1 C9: the fixed message, and a Gateway refusal's own status code."""
    gateway = Gateway(top="general")
    gateway.script[(CHAT_PATH, MODELS["general"])] = httpx.Response(
        400, json={"detail": {"code": "model_token_cap", "message": "too many tokens"}}
    )

    outcome = await run_direct(gateway)

    assert outcome.code() == "aigateway_http_400"
    assert str(outcome.error) == ROUTED_CALL_FAILED_MESSAGE
    assert len(gateway.posts(CHAT_PATH)) == 1


async def test_a_branch_answer_without_content_is_never_an_empty_answer() -> None:
    gateway = Gateway(top="general")
    gateway.script[(CHAT_PATH, MODELS["general"])] = lambda _: {
        "choices": [{"message": {"role": "assistant", "content": None}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 0},
    }

    outcome = await run_direct(gateway)

    assert outcome.error is not None
    assert outcome.code() in {"aigateway_bad_response", "model_empty_content"}


async def test_a_cancelled_classification_never_reaches_a_branch() -> None:
    gateway = Gateway(hold=CLASSIFICATIONS_PATH)
    task = asyncio.create_task(run_direct(gateway))

    await asyncio.wait_for(gateway.held.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert gateway.cancelled.is_set()
    assert gateway.posts(CHAT_PATH) == []


# --- refusals before any Gateway call -------------------------------------------------------------


@pytest.mark.parametrize(
    "scope",
    [
        pytest.param(
            RequestScope(origin="sync", identity_headers=CALLER, answer_seed=0), id="seed"
        ),
        pytest.param(capture_scope(identity_headers=CALLER), id="capture"),
        pytest.param(replay_scope(identity_headers=CALLER), id="replay"),
    ],
)
async def test_seed_capture_and_replay_are_refused_before_any_call(scope: RequestScope) -> None:
    gateway = Gateway()

    outcome = await run_direct(gateway, scope=scope)

    assert (outcome.code(), outcome.permanent()) == ("routing_unsupported", True)
    # WHY the frozen-copy open is set aside: a capture run's executor opens its copy before any
    # handler runs; the mount refuses both frozen-copy headers before a run exists.
    assert [r for r in gateway.requests if r.url.path != "/v1/frozen-copies"] == []


async def test_an_unknown_profile_is_refused_before_any_call() -> None:
    gateway = Gateway()

    outcome = await run_direct(gateway, query(context(profile="missing_v1")))

    assert outcome.code() == _NOT_FOUND
    assert "missing_v1" not in str(outcome.error)
    assert gateway.requests == []


async def test_an_unknown_and_an_ungranted_profile_answer_the_same_message() -> None:
    unknown = await run_direct(Gateway(), query(context(profile="missing_v1")))
    hidden = Gateway()
    hidden.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = httpx.Response(
        400, json={"detail": f"unknown provider: {CLASSIFIER.split('/')[0]}"}
    )
    ungranted = await run_direct(hidden)

    assert str(unknown.error) == str(ungranted.error)


_CASE_V1 = json.dumps(
    {"schema": "screamingface.candidate-input.v1", "messages": [{"role": "user", "content": "hi"}]}
)
_CASE_V9 = json.dumps({"schema": "screamingface.candidate-input.v9", "messages": []})
_PICTURE_CASE = json.dumps(
    {
        "schema": "screamingface.candidate-input.v2",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is shown?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                    },
                ],
            }
        ],
    }
)
_FUSION_PICTURE = json.dumps({"input": _PICTURE_CASE, "outputs": {"member_1": "a chart"}})


@pytest.mark.parametrize(
    "raw_query",
    [
        pytest.param(query("not json"), id="not-json"),
        pytest.param(query("[]"), id="not-an-object"),
        pytest.param(query(context(extra="x")), id="extra-key"),
        pytest.param(query(json.dumps({"profile": PROFILE})), id="missing-input"),
        pytest.param(query('{"profile":"a","profile":"b","input":"c"}'), id="repeated-key"),
        pytest.param(query(json.dumps({"profile": 1, "input": "x"})), id="profile-not-a-string"),
        pytest.param(query(json.dumps({"profile": PROFILE, "input": 1})), id="input-not-a-string"),
        pytest.param(query(context(text="")), id="empty-input"),
        pytest.param(query(json.dumps({"profile": PROFILE, "input": "a\ud800b"})), id="surrogate"),
        pytest.param(query(context(), intent="classify"), id="wrong-intent"),
        pytest.param(query(context(), params=(("max_tokens", "5"),)), id="a-parameter"),
        pytest.param(query(context(text=_CASE_V1)), id="candidate-envelope"),
        pytest.param(query(context(text=_CASE_V9)), id="broken-envelope"),
        pytest.param(query(context(text=_FUSION_PICTURE)), id="fusion-picture-context"),
        pytest.param(query("[" * 3000 + "]" * 3000), id="deeply-nested"),
    ],
)
async def test_a_malformed_request_is_refused_before_any_call(raw_query: str) -> None:
    gateway = Gateway()

    outcome = await run_direct(gateway, raw_query)

    assert outcome.code() == "malformed_source"
    assert gateway.requests == []


async def test_a_text_fusion_context_is_a_plain_prompt() -> None:
    # WHY accepted: the chat route sends a text-only Fusion context as written, so the branch
    # still receives exactly the caller's characters.
    text = json.dumps({"input": "plain question", "outputs": {"member_1": "x"}})
    gateway = Gateway()

    await run_direct(gateway, query(context(text=text)))

    (chat,) = gateway.posts(CHAT_PATH)
    assert chat["messages"] == [{"role": "user", "content": text}]
