"""`/route-answer` over a dynamic-choice named profile, through the real executor (Unit 5.2).

FEATURE: Router Recipe extension (contracts C2, C6, C7). A dynamic profile checks the classifier's
`choice` capability and C7 limits before inference, sends the C7 choice input with its options in
branch order, takes the unique highest label and asks that one branch the exact question.

STORY: as an operator I describe each expert in the world file; a caller asks one question and the
expert the classifier picks from those descriptions answers it.

INVARIANT: one selected generation and zero unselected calls; a metadata refusal, a tie, a missing
or extra label and a classifier failure make no branch call; the `routed-answer-v1` wire is the
fixed profile's.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from routing_support import (
    CHAT_PATH,
    CLASSIFICATIONS_PATH,
    CLASSIFIER,
    DETAILS_PATH,
    GATEWAY_TOML,
    LABELS,
    MAX_TOKENS,
    MODELS,
    PROFILE,
    TEXT,
    Gateway,
    classifier_document,
    context,
    preflight_calls,
    query,
    run_direct,
    world_config,
)

from screamingface_engine.request_scope import RequestScope
from screamingface_engine.world.config import WorldConfig

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]

_INSTRUCTIONS = "Pick the expert for the question."
_DESCRIPTIONS = {
    "general": "Everything else.",
    "code": "Programming questions.",
    "math": "Arithmetic and proofs.",
}
_ORDER = ("math", "general", "code")  # table order, deliberately not the fixed profile's

_DYNAMIC_TOML = (
    GATEWAY_TOML
    + f"""
[routing.profiles.{PROFILE}]
classifier = "{CLASSIFIER}"
classifier_contract = "classification-scores-v1"
policy = "unique-argmax-v1"
revision_scheme = "router-definition-v1"
instructions = "{_INSTRUCTIONS}"
"""
    + "".join(
        f"""
[routing.profiles.{PROFILE}.branches.{label}]
model = "{MODELS[label]}"
max_tokens = {MAX_TOKENS[label]}
description = "{_DESCRIPTIONS[label]}"
"""
        for label in _ORDER
    )
)

_ABSENT = object()

_LIMITS = {
    "contract": "classifier-limits-v1",
    "max_labels": 32,
    "max_label_bytes": 64,
    "max_text_chars": 20000,
    "max_options": 32,
    "max_description_chars": 1024,
    "max_instructions_chars": 4096,
}


def _config() -> WorldConfig:
    return world_config(_DYNAMIC_TOML)


def _choice_gateway(top: str = "code", **details: Any) -> Gateway:
    gateway = Gateway(top=top)
    document = classifier_document(input_contracts=["choice"], limits=_LIMITS)
    document.update(details)
    for key in [key for key, value in document.items() if value is _ABSENT]:
        del document[key]
    gateway.script[(DETAILS_PATH, CLASSIFIER)] = lambda _: document
    return gateway


def _scores(*pairs: tuple[str, float]) -> Any:
    return lambda _: {
        "object": "classification",
        "model": CLASSIFIER,
        "contract": "classification-scores-v1",
        "scores": [{"label": label, "score": score} for label, score in pairs],
    }


def _branch_calls(gateway: Gateway) -> list[tuple[str, str, str]]:
    return [call for call in gateway.calls() if call[1] == CHAT_PATH]


def _dynamic_preflight() -> list[tuple[str, str, str]]:
    (details, *_) = preflight_calls()
    by_model = {call[2]: call for call in preflight_calls()[1:]}
    return [details, *(by_model[MODELS[label]] for label in _ORDER)]


# --- selection ------------------------------------------------------------------------------------


@pytest.mark.parametrize("label", LABELS)
async def test_each_label_selects_its_branch_and_calls_no_other(label: str) -> None:
    gateway = _choice_gateway(top=label)

    document = (await run_direct(gateway, config=_config())).document()

    assert gateway.calls() == [
        *_dynamic_preflight(),
        ("POST", CLASSIFICATIONS_PATH, CLASSIFIER),
        ("POST", CHAT_PATH, MODELS[label]),
    ]
    assert document["selected"] == {"label": label, "model": MODELS[label]}
    assert document["answer"] == f"answer from {MODELS[label]}"


async def test_the_classifier_reads_the_choice_input_with_options_in_branch_order() -> None:
    gateway = _choice_gateway()

    await run_direct(gateway, config=_config())

    assert gateway.posts(CLASSIFICATIONS_PATH) == [
        {
            "model": CLASSIFIER,
            "input": {
                "contract": "classification-choice-input-v1",
                "text": TEXT,
                "instructions": _INSTRUCTIONS,
                "options": [
                    {"label": label, "description": _DESCRIPTIONS[label]} for label in _ORDER
                ],
            },
        }
    ]


async def test_the_selected_branch_reads_the_exact_question_with_its_bound_max_tokens() -> None:
    gateway = _choice_gateway(top="math")

    await run_direct(gateway, config=_config())

    assert gateway.posts(CHAT_PATH) == [
        {
            "model": MODELS["math"],
            "messages": [{"role": "user", "content": TEXT}],
            "max_tokens": MAX_TOKENS["math"],
        }
    ]


async def test_the_wire_is_routed_answer_v1_with_the_c3_revision() -> None:
    gateway = _choice_gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = _scores(
        ("code", 0.7), ("math", 0.2), ("general", 0.1)
    )

    document = (await run_direct(gateway, config=_config())).document()

    assert document == {
        "object": "routed_answer",
        "contract": "routed-answer-v1",
        "profile": PROFILE,
        "revision": _config().routing[PROFILE].revision,
        "policy": "unique-argmax-v1",
        "classification": {
            "model": CLASSIFIER,
            "contract": "classification-scores-v1",
            "scores": [
                {"label": "code", "score": 0.7},
                {"label": "math", "score": 0.2},
                {"label": "general", "score": 0.1},
            ],
        },
        "selected": {"label": "code", "model": MODELS["code"]},
        "answer": f"answer from {MODELS['code']}",
    }
    assert document["revision"] != world_config().routing[PROFILE].revision


# --- no branch call -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pairs", "code"),
    [
        pytest.param(
            (("code", 0.4), ("math", 0.4), ("general", 0.2)), "routing_ambiguous", id="tie"
        ),
        pytest.param((("code", 0.9), ("math", 0.1)), "routing_invalid_scores", id="missing"),
        pytest.param(
            (("code", 0.6), ("math", 0.1), ("general", 0.1), ("poetry", 0.2)),
            "routing_invalid_scores",
            id="extra",
        ),
    ],
)
async def test_a_tie_or_a_label_mismatch_asks_no_branch(
    pairs: tuple[tuple[str, float], ...], code: str
) -> None:
    gateway = _choice_gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = _scores(*pairs)

    outcome = await run_direct(gateway, config=_config())

    assert (outcome.code(), outcome.permanent()) == (code, True)
    assert _branch_calls(gateway) == []


async def test_a_classifier_failure_asks_no_branch() -> None:
    gateway = _choice_gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = httpx.Response(
        503, json={"detail": "unavailable"}
    )

    outcome = await run_direct(gateway, config=_config())

    assert outcome.error is not None
    assert _branch_calls(gateway) == []


@pytest.mark.parametrize(
    "details",
    [
        pytest.param({"input_contracts": ["text"], "limits": None}, id="text-only"),
        pytest.param({"input_contracts": ["choice"], "limits": None}, id="null-limits"),
        pytest.param({"limits": _ABSENT}, id="no-limits-key"),
        pytest.param({"input_contracts": _ABSENT}, id="no-contracts-key"),
        pytest.param({"limits": {**_LIMITS, "max_options": 2}}, id="max-options"),
        pytest.param({"limits": {**_LIMITS, "max_labels": 2}}, id="max-labels"),
        pytest.param({"limits": {**_LIMITS, "max_label_bytes": 4}}, id="label-bytes"),
        pytest.param({"limits": {**_LIMITS, "max_description_chars": 15}}, id="descriptions"),
        pytest.param({"limits": {**_LIMITS, "max_instructions_chars": 32}}, id="instructions"),
        pytest.param({"limits": {**_LIMITS, "max_text_chars": len(TEXT) - 1}}, id="text"),
        pytest.param({"limits": {**_LIMITS, "max_options": True}}, id="invalid-limits"),
        pytest.param({"result_contract": "classification-scores-v2"}, id="result-contract"),
    ],
)
async def test_a_classifier_the_profile_does_not_fit_is_refused_before_inference(
    details: dict[str, Any],
) -> None:
    gateway = _choice_gateway(**details)

    outcome = await run_direct(gateway, config=_config())

    assert (outcome.code(), outcome.permanent()) == ("routing_profile_mismatch", True)
    assert all(request.method == "GET" for request in gateway.requests)


async def test_an_input_at_the_text_limit_is_sent() -> None:
    gateway = _choice_gateway(limits={**_LIMITS, "max_text_chars": len(TEXT)})

    assert (await run_direct(gateway, config=_config())).error is None


async def test_the_fixed_profile_still_sends_the_scalar_input_to_a_text_classifier() -> None:
    gateway = Gateway()
    gateway.script[(DETAILS_PATH, CLASSIFIER)] = lambda _: classifier_document(
        input_contracts=["text"], limits=None
    )

    await run_direct(gateway)

    assert gateway.posts(CLASSIFICATIONS_PATH) == [{"model": CLASSIFIER, "input": TEXT}]


async def test_the_mode_refusal_still_comes_first() -> None:
    gateway = _choice_gateway()
    scope = RequestScope(
        origin="sync", identity_headers={"X-User-Email": "a@x.test"}, answer_seed=0
    )

    outcome = await run_direct(gateway, query(context()), scope=scope, config=_config())

    assert outcome.code() == "routing_unsupported"
    assert gateway.requests == []
