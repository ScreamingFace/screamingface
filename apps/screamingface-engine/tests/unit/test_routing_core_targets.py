"""The shared preflight's Router targets: a Model's call parameters and a text classifier input.

FEATURE: Router Recipe extension (C4 ADMIT, C7). Router ADMIT reads the same metadata through the
same shared preflight as a named profile, with two additions: each Model's whole parameter
contract, for the values exactly as its call sends them, and the C7 text capability and limits of
a fixed-label scoring classifier. A fixed profile passes neither, so its checks are unchanged.

INVARIANT: no inference, and a refusal only once every target was read.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from routing_support import (
    CALLER,
    CLASSIFIER,
    DETAILS_PATH,
    PARAMETERS_PATH,
    Gateway,
    classifier_document,
    max_tokens_rule,
    parameters_document,
)

from screamingface_engine.world.classifier_limits import (
    LIMITS_CONTRACT,
    ChoiceRequest,
    TextRequest,
    choice_input,
    read_capability,
    text_fits,
)
from screamingface_engine.world.routing_core import (
    ClassifierTarget,
    ModelTarget,
    PreflightRefusal,
    preflight,
)

_CODER = "openrouter/acme/coder"
_WRITER = "openrouter/acme/writer"
_SCORES = "classification-scores-v1"


def _rule(schema: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return max_tokens_rule(schema=schema, **changes)


def _parameters(model: str, rows: dict[str, Any], *, access: str = "configured") -> Any:
    document = parameters_document(model, access=access)
    document["parameters"] = rows
    return lambda _request: document


def _run(
    gateway: Gateway, models: list[ModelTarget], classifier: ClassifierTarget | None = None
) -> PreflightRefusal | None:
    async def scenario() -> None:
        async with gateway.client() as client:
            await preflight(client, dict(CALLER), classifier, models)

    try:
        asyncio.run(scenario())
    except PreflightRefusal as refusal:
        return refusal
    return None


def _kind(refusal: PreflightRefusal | None) -> str | None:
    return None if refusal is None else refusal.kind


# --- a Model's call parameters --------------------------------------------------------------------


_ROWS = {
    "max_tokens": max_tokens_rule(),
    "temperature": _rule({"type": "number", "minimum": 0, "maximum": 2}),
    "logprobs": _rule({"type": "boolean"}),
    "stop": _rule({"type": ["string", "array"], "items": {"type": "string"}}),
}


def test_call_parameters_that_fit_their_rows_pass() -> None:
    gateway = Gateway()
    gateway.script[(PARAMETERS_PATH, _CODER)] = _parameters(_CODER, _ROWS)
    params = (("logprobs", "true"), ("max_tokens", "256"), ("stop", "END"), ("temperature", "0.2"))

    assert _run(gateway, [ModelTarget(_CODER, params=params)]) is None
    assert gateway.calls() == [("GET", PARAMETERS_PATH, _CODER)]


@pytest.mark.parametrize(
    "params",
    [
        pytest.param((("max_tokens", "0.5"),), id="number-for-an-integer"),
        pytest.param((("temperature", "3"),), id="above-maximum"),
        pytest.param((("logprobs", "yes"),), id="text-for-a-boolean"),
        pytest.param((("temperature", "NaN"),), id="non-finite"),
        pytest.param((("top_k", "5"),), id="no-row"),
        pytest.param((("messages", "[]"),), id="runner-owned-field"),
    ],
)
def test_a_value_its_row_refuses_is_a_mismatch(params: tuple[tuple[str, str], ...]) -> None:
    gateway = Gateway()
    gateway.script[(PARAMETERS_PATH, _CODER)] = _parameters(_CODER, _ROWS)

    assert _kind(_run(gateway, [ModelTarget(_CODER, params=params)])) == "mismatch"


def test_a_provider_refusal_is_a_mismatch() -> None:
    gateway = Gateway()
    rows = {"seed": _rule({"type": "integer"}, provider={"support": "unsupported"})}
    gateway.script[(PARAMETERS_PATH, _CODER)] = _parameters(_CODER, rows)

    assert _kind(_run(gateway, [ModelTarget(_CODER, params=(("seed", "7"),))])) == "mismatch"


def test_engine_interpreted_parameters_need_no_row() -> None:
    # WHY: `web_search`, its exclusions and `binding` never reach the Gateway (model_params).
    gateway = Gateway()
    gateway.script[(PARAMETERS_PATH, _CODER)] = _parameters(_CODER, {})
    params = (("binding", "model_1"), ("web_search", "false"), ("web_search_exclude", "a.com"))

    assert _run(gateway, [ModelTarget(_CODER, params=params)]) is None


def test_a_model_without_parameters_reads_no_rule() -> None:
    gateway = Gateway()
    gateway.script[(PARAMETERS_PATH, _CODER)] = _parameters(_CODER, {})

    assert _run(gateway, [ModelTarget(_CODER)]) is None


def test_a_mismatch_is_decided_after_every_model_was_read() -> None:
    gateway = Gateway()
    gateway.script[(PARAMETERS_PATH, _CODER)] = _parameters(_CODER, {})
    gateway.script[(PARAMETERS_PATH, _WRITER)] = _parameters(_WRITER, {}, access="missing")
    targets = [ModelTarget(_CODER, params=(("top_k", "5"),)), ModelTarget(_WRITER)]

    refusal = _run(gateway, targets)

    # INVARIANT: a missing Connection is named before a misfit, once all are read.
    assert _kind(refusal) == "connection_missing"
    assert [path for _, path, _ in gateway.calls()] == [PARAMETERS_PATH, PARAMETERS_PATH]


def test_the_fixed_max_tokens_check_keeps_ignoring_provider_evidence() -> None:
    gateway = Gateway()
    rule = max_tokens_rule(provider={"support": "unsupported"})
    gateway.script[(PARAMETERS_PATH, _CODER)] = _parameters(_CODER, {"max_tokens": rule})

    assert _run(gateway, [ModelTarget(_CODER, 256)]) is None


# --- a fixed-label scoring classifier's text input ------------------------------------------------


def _text_limits(**changes: int) -> dict[str, Any]:
    limits: dict[str, Any] = {
        "contract": LIMITS_CONTRACT,
        "max_labels": 3,
        "max_label_bytes": 8,
        "max_text_chars": 10,
    }
    limits.update(changes)
    return limits


def _classifier(text: str = "short", labels: tuple[str, ...] = ("a", "b")) -> ClassifierTarget:
    return ClassifierTarget(CLASSIFIER, _SCORES, text=TextRequest(labels=labels, text=text))


def _details(**fields: Any) -> Any:
    document = classifier_document(**fields)
    return lambda _request: document


@pytest.mark.parametrize(
    ("fields", "target"),
    [
        pytest.param(
            {"input_contracts": ["text"], "limits": _text_limits()}, _classifier(), id="in-limits"
        ),
        pytest.param(
            {"input_contracts": ["text"], "limits": _text_limits()},
            _classifier("x" * 10, ("a", "b", "c")),
            id="at-every-limit",
        ),
    ],
)
def test_a_text_classifier_within_its_limits_passes(
    fields: dict[str, Any], target: ClassifierTarget
) -> None:
    gateway = Gateway()
    gateway.script[(DETAILS_PATH, CLASSIFIER)] = _details(**fields)

    assert _run(gateway, [], target) is None


@pytest.mark.parametrize(
    ("fields", "target"),
    [
        pytest.param(
            {"input_contracts": ["text"], "limits": _text_limits()},
            _classifier("x" * 11),
            id="text-over-max-text-chars",
        ),
        pytest.param(
            {"input_contracts": ["text"], "limits": _text_limits()},
            _classifier(labels=("a", "b", "c", "d")),
            id="more-labels-than-it-returns",
        ),
        pytest.param(
            {"input_contracts": ["text"], "limits": _text_limits()},
            _classifier(labels=("a", "é" * 5)),
            id="label-over-max-label-bytes",
        ),
        pytest.param(
            {"input_contracts": ["choice"], "limits": None}, _classifier(), id="choice-only"
        ),
        # INVARIANT (C7/C17): `limits: null` serves direct `/classify` only; a Router
        # that needs the classifier refuses it.
        pytest.param({"input_contracts": ["text"], "limits": None}, _classifier(), id="no-limits"),
        pytest.param({}, _classifier(), id="no-c7-row"),
    ],
)
def test_a_text_classifier_that_cannot_take_the_input_is_a_mismatch(
    fields: dict[str, Any], target: ClassifierTarget
) -> None:
    gateway = Gateway()
    gateway.script[(DETAILS_PATH, CLASSIFIER)] = _details(**fields)

    assert _kind(_run(gateway, [], target)) == "mismatch"


def test_the_fixed_profile_target_keeps_the_scalar_check() -> None:
    gateway = Gateway()

    assert _run(gateway, [], ClassifierTarget(CLASSIFIER, _SCORES)) is None


# --- the pure C7 helpers --------------------------------------------------------------------------


def test_text_fits_reads_only_the_text_contract() -> None:
    capability = read_capability(["text", "choice"], {**_text_limits(), **_choice_keys()})

    assert capability is not None
    assert text_fits(capability, TextRequest(("a",), "x" * 10)) is True
    assert text_fits(capability, TextRequest(("a",), "x" * 11)) is False


def _choice_keys() -> dict[str, int]:
    return {"max_options": 3, "max_description_chars": 20, "max_instructions_chars": 20}


def test_the_choice_input_keeps_option_order_and_exact_keys() -> None:
    request = ChoiceRequest(
        labels=("math", "code"),
        descriptions=("Sums.", "Programs."),
        instructions="Pick one.",
        text="What is 2+2?",
    )

    assert choice_input(request) == {
        "contract": "classification-choice-input-v1",
        "text": "What is 2+2?",
        "instructions": "Pick one.",
        "options": [
            {"label": "math", "description": "Sums."},
            {"label": "code", "description": "Programs."},
        ],
    }
    assert list(choice_input(request)) == ["contract", "text", "instructions", "options"]


# --- strict metadata documents --------------------------------------------------------------------


def _raw(text: str) -> httpx.Response:
    return httpx.Response(200, content=text.encode(), headers={"content-type": "application/json"})


_DETAILS_TEXT = json.dumps(classifier_document(input_contracts=["text"], limits=_text_limits()))


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(
            _DETAILS_TEXT[:-1] + ', "execution_access": "configured"}', id="repeated-access"
        ),
        pytest.param(
            _DETAILS_TEXT.replace('"max_labels": 3', '"max_labels": 3, "max_labels": 9'),
            id="repeated-limit",
        ),
        pytest.param(
            _DETAILS_TEXT.replace('"max_labels": 3', '"max_labels": 1e999'), id="non-finite"
        ),
    ],
)
def test_a_classifier_document_that_is_not_strict_json_is_unreadable(document: str) -> None:
    gateway = Gateway()
    gateway.script[(DETAILS_PATH, CLASSIFIER)] = _raw(document)

    # INVARIANT: a repeated key is never resolved by "last wins"; the read is refused.
    assert _kind(_run(gateway, [], _classifier())) == "failed"


def test_a_parameter_document_that_repeats_a_key_is_unreadable() -> None:
    gateway = Gateway()
    text = json.dumps(parameters_document(_CODER))
    gateway.script[(PARAMETERS_PATH, _CODER)] = _raw(text[:-1] + ', "parameters": {}}')

    assert _kind(_run(gateway, [ModelTarget(_CODER)])) == "failed"
