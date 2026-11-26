"""The Router ADMIT metadata preflight, per model-bearing role (contracts C2, C4, C7; Unit 5.2).

FEATURE: Router Recipe extension. Before any provider I/O of an occurrence, ADMIT reads the
classifier's details and every Model's parameters; a role that cannot run is refused as data
(`{"refused": ...}`) with its routing code, and a Gateway that cannot answer is a transient refusal.

INVARIANT: a preflight refusal makes no provider call (no POST).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from router_support import (
    CHOICE_LIMITS,
    QUESTION,
    ROUTES,
    SELECTOR_MODEL,
    admit_step,
    choice_definition,
    classifier_details,
    fixed_definition,
    llm_definition,
    model,
    posts,
    refusal,
    regex_definition,
    router_gateway,
    spec_text,
)
from routing_support import (
    CLASSIFIER,
    DETAILS_PATH,
    LABELS,
    MODELS,
    PARAMETERS_PATH,
    PUBLIC,
    parameters_document,
)

# --- the metadata preflight, per role -------------------------------------------------------------


def _missing(name: str) -> Any:
    document = parameters_document(name, access="missing")
    return lambda _request: document


def _without_rows(name: str) -> Any:
    document = parameters_document(name)
    document["parameters"] = {}
    return lambda _request: document


@pytest.mark.parametrize(
    ("definition", "script", "code"),
    [
        pytest.param(
            fixed_definition(),
            {(DETAILS_PATH, CLASSIFIER): httpx.Response(404)},
            "routing_profile_not_found",
            id="invisible-classifier",
        ),
        pytest.param(
            fixed_definition(),
            {(DETAILS_PATH, CLASSIFIER): classifier_details("choice", limits=CHOICE_LIMITS)},
            "routing_profile_mismatch",
            id="classifier-without-text-input",
        ),
        pytest.param(
            choice_definition(),
            {(DETAILS_PATH, CLASSIFIER): classifier_details("text")},
            "routing_profile_mismatch",
            id="choice-classifier-with-null-limits",
        ),
        # INVARIANT (C7, C17): `limits: null` serves direct scalar classification only;
        # a Router that needs the classifier is refused before any classifier or chat call.
        pytest.param(
            fixed_definition(),
            {(DETAILS_PATH, CLASSIFIER): classifier_details("text", limits=None)},
            "routing_profile_mismatch",
            id="text-classifier-with-null-limits",
        ),
        pytest.param(
            llm_definition(),
            {(PARAMETERS_PATH, SELECTOR_MODEL): httpx.Response(404)},
            "routing_profile_not_found",
            id="llm-classifier-unknown",
        ),
        pytest.param(
            llm_definition(),
            {(PARAMETERS_PATH, SELECTOR_MODEL): _missing(SELECTOR_MODEL)},
            "routing_connection_missing",
            id="llm-classifier-connection",
        ),
        pytest.param(
            fixed_definition(),
            {(PARAMETERS_PATH, MODELS["math"]): _without_rows(MODELS["math"])},
            "routing_profile_mismatch",
            id="candidate-parameter-refused",
        ),
        pytest.param(
            fixed_definition(),
            {(PARAMETERS_PATH, MODELS["code"]): _missing(MODELS["code"])},
            "routing_connection_missing",
            id="candidate-connection",
        ),
        pytest.param(
            fixed_definition(default=model(PUBLIC, max_tokens="32")),
            {(PARAMETERS_PATH, PUBLIC): _without_rows(PUBLIC)},
            "routing_profile_mismatch",
            id="default-parameter-refused",
        ),
        pytest.param(
            fixed_definition(default=model(PUBLIC)),
            {(PARAMETERS_PATH, PUBLIC): httpx.Response(404)},
            "routing_profile_not_found",
            id="default-unknown",
        ),
        pytest.param(
            regex_definition(),
            {(PARAMETERS_PATH, MODELS["general"]): httpx.Response(403)},
            "routing_preflight_failed",
            id="unreadable-parameters",
        ),
    ],
)
def test_a_preflight_refusal_is_a_refusal_document_with_no_provider_call(
    definition: dict[str, Any], script: dict[tuple[str, str], Any], code: str
) -> None:
    gateway = router_gateway()
    gateway.script.update(script)

    assert json.loads(admit_step(gateway, spec_text(definition))) == refusal(code)
    assert posts(gateway) == []


def test_an_unavailable_preflight_is_a_transient_refusal() -> None:
    gateway = router_gateway()
    gateway.script[(PARAMETERS_PATH, MODELS["general"])] = httpx.ConnectError("down")

    assert json.loads(admit_step(gateway, spec_text(regex_definition()))) == refusal(
        "routing_preflight_unavailable", permanent=False
    )
    assert posts(gateway) == []


def test_the_question_is_checked_against_the_text_limits() -> None:
    gateway = router_gateway()
    text_limits = {
        "contract": CHOICE_LIMITS["contract"],
        "max_labels": len(LABELS),
        "max_label_bytes": 64,
        "max_text_chars": len(QUESTION) - 1,
    }
    gateway.script[(DETAILS_PATH, CLASSIFIER)] = classifier_details("text", limits=text_limits)

    assert json.loads(admit_step(gateway, spec_text(fixed_definition()))) == refusal(
        "routing_profile_mismatch"
    )


# --- canonical Model IDs (C2, C5) -----------------------------------------------------------------

_COLON_MODEL = "openrouter/qwen/qwen3:free"
_COLON_ROUTE = "/openrouter/qwen/qwen3~free"
"""How the world declares that Model: its url4 route escapes ``:`` as ``~`` (OME-873)."""


def test_a_colon_bearing_canonical_model_id_is_admitted_and_read_canonically() -> None:
    gateway = router_gateway()
    definition = regex_definition(default=model(_COLON_MODEL))

    document = json.loads(
        admit_step(gateway, spec_text(definition), routes=ROUTES | {_COLON_ROUTE})
    )

    assert set(document) == {"input", "spec"}
    assert document["spec"]["definition"]["default"]["model"] == _COLON_MODEL
    assert ("GET", PARAMETERS_PATH, _COLON_MODEL) in gateway.calls()


def test_a_tilde_encoded_model_id_is_not_a_canonical_id_and_is_refused() -> None:
    gateway = router_gateway()
    definition = regex_definition(default=model(_COLON_ROUTE.removeprefix("/")))

    document = json.loads(
        admit_step(gateway, spec_text(definition), routes=ROUTES | {_COLON_ROUTE})
    )

    # INVARIANT: no record ever names a route form; the refusal comes before any read.
    assert document == refusal("routing_profile_not_found")
    assert gateway.calls() == []
