"""Choice targets and classifier limits in the schema v1 remote-endpoint config (contract C7).

# FEATURE: Router Recipe extension Unit 5.1 — `systemone-choice-v1` is a classification target of
# its own kind, with required limits in the C7 ranges; an HF target may declare its text limits.
# INVARIANT: a refusal names the location and the rule, never the offending value; a document
# without the new keys parses exactly as before.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.plugins.remote_endpoint.definitions import (
    ChoiceTarget,
    ClassificationTarget,
    RemoteEndpointConfigError,
    parse_remote_endpoint_config,
)
from aigateway.plugins.remote_endpoint.limits import ClassifierLimits

from .choice_upstream import CHOICE_ALIAS, LIMITS, choice_target
from .fixtures import CLASSIFIER_PATH, classifier_target, document, endpoint

# A number no refusal may repeat.
MARKER = 7_777_777


def _parse(target: dict[str, Any]) -> Any:
    doc = document(endpoint(targets=[target], validation_target=target["alias"]))
    return parse_remote_endpoint_config(doc).endpoints[0].targets[0]


def _refusal(target: dict[str, Any]) -> str:
    with pytest.raises(RemoteEndpointConfigError) as caught:
        _parse(target)
    assert caught.value.__cause__ is None
    return str(caught.value)


def test_a_choice_target_is_parsed_with_its_limits() -> None:
    assert _parse(choice_target(upstream_model="jev/m")) == ChoiceTarget(
        alias=CHOICE_ALIAS,
        request_path=CLASSIFIER_PATH,
        limits=ClassifierLimits(**LIMITS),
        upstream_model="jev/m",
    )
    assert _parse(choice_target()).upstream_model is None


def test_an_hf_target_without_limits_parses_as_before_and_with_them_keeps_them() -> None:
    assert _parse(classifier_target()).limits is None
    text = {"max_labels": 2, "max_label_bytes": 8, "max_text_chars": 2_147_483_647}
    parsed = _parse(classifier_target(limits=text))
    assert isinstance(parsed, ClassificationTarget)
    limits = parsed.limits
    assert limits == ClassifierLimits(**text)
    assert limits is not None
    assert limits.row() == {"contract": "classifier-limits-v1", **text}


def _limits(**changes: Any) -> dict[str, Any]:
    limits: dict[str, Any] = {**LIMITS, **changes}
    return {key: value for key, value in limits.items() if value is not None}


CHOICE_REFUSALS: dict[str, tuple[dict[str, Any], str]] = {
    "no-limits": ({"limits": None}, "limits"),
    "missing-key": ({"limits": _limits(max_options=None)}, "limits.max_options"),
    "unknown-key": ({"limits": _limits(max_tokens=MARKER)}, "limits.max_tokens"),
    "zero": ({"limits": _limits(max_text_chars=0)}, "limits.max_text_chars"),
    "options-over-32": ({"limits": _limits(max_options=33, max_labels=33)}, "max_options"),
    "labels-over-32": ({"limits": _limits(max_labels=33)}, "limits.max_labels"),
    "labels-under-options": ({"limits": _limits(max_labels=5)}, "max_labels must be at least"),
    "label-bytes-over-64": ({"limits": _limits(max_label_bytes=65)}, "limits.max_label_bytes"),
    "description-over-1024": (
        {"limits": _limits(max_description_chars=1025)},
        "limits.max_description_chars",
    ),
    "instructions-over-4096": (
        {"limits": _limits(max_instructions_chars=MARKER)},
        "limits.max_instructions_chars",
    ),
    "text-over-int32": ({"limits": _limits(max_text_chars=2_147_483_648)}, "max_text_chars"),
    "boolean": ({"limits": _limits(max_options=True)}, "limits.max_options"),
    "float": ({"limits": _limits(max_options=4.0)}, "limits.max_options"),
    "string": ({"limits": _limits(max_options="4")}, "limits.max_options"),
    "spaced-upstream-model": ({"upstream_model": "a b"}, "upstream_model"),
    "envelope": ({"response_envelope": "flat"}, "response_envelope"),
    "score-semantics": ({"score_semantics": "bounded-score"}, "score_semantics"),
}


@pytest.mark.parametrize(("changes", "where"), CHOICE_REFUSALS.values(), ids=CHOICE_REFUSALS.keys())
def test_a_choice_target_outside_its_rules_fails_startup_without_the_value(
    changes: dict[str, Any], where: str
) -> None:
    target = choice_target(**changes)
    if target.get("limits") is None:
        target.pop("limits")
    message = _refusal(target)
    assert where in message
    assert str(MARKER) not in message


HF_REFUSALS: dict[str, dict[str, Any]] = {
    "zero": {"max_labels": 0, "max_label_bytes": 8, "max_text_chars": 10},
    "over-int32": {"max_labels": 2, "max_label_bytes": 8, "max_text_chars": 2_147_483_648},
    "choice-key": {"max_labels": 2, "max_label_bytes": 8, "max_text_chars": 10, "max_options": 2},
    "missing-key": {"max_labels": 2, "max_label_bytes": 8},
    "boolean": {"max_labels": True, "max_label_bytes": 8, "max_text_chars": 10},
}


@pytest.mark.parametrize("limits", HF_REFUSALS.values(), ids=HF_REFUSALS.keys())
def test_an_hf_limit_outside_its_rules_fails_startup(limits: dict[str, Any]) -> None:
    assert "limits" in _refusal(classifier_target(limits=limits))


def test_the_refusal_location_omits_the_parser_s_kind_tag() -> None:
    message = _refusal(choice_target(limits=_limits(max_options=0)))
    assert "targets.0.limits.max_options" in message
    assert "systemone-choice-v1" not in message
