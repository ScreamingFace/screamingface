"""Classifier targets in the schema v1 remote-endpoint config.

# FEATURE: hosted BYOM Unit 3 — `task` selects a target's kind; each kind has its own required
# fields and refuses the other kind's, in the same file and schema version as chat.
# INVARIANT: a refusal names the location and the rule, never the offending value, exactly as the
# chat target refusals do.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.plugins.remote_endpoint.definitions import (
    ChatTarget,
    ClassificationTarget,
    RemoteEndpointConfigError,
    parse_remote_endpoint_config,
)

from .fixtures import (
    ALIAS,
    CLASSIFIER_ALIAS,
    CLASSIFIER_PATH,
    ENDPOINT_A,
    chat_target,
    classifier_target,
    document,
    endpoint,
)

# A value no refusal may repeat.
MARKER = "zz-private-marker"


def _refusal(doc: Any) -> str:
    with pytest.raises(RemoteEndpointConfigError) as caught:
        parse_remote_endpoint_config(doc)
    error = caught.value
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__
    return str(error)


def _classifier_only(**overrides: Any) -> dict[str, Any]:
    return document(
        endpoint(targets=[classifier_target(**overrides)], validation_target=CLASSIFIER_ALIAS)
    )


# --- accepted -----------------------------------------------------------------------------------


def test_a_classifier_target_alone_is_accepted_with_its_fields() -> None:
    (definition,) = parse_remote_endpoint_config(_classifier_only()).endpoints

    (target,) = definition.targets
    assert target == ClassificationTarget(
        alias=CLASSIFIER_ALIAS,
        request_path=CLASSIFIER_PATH,
        response_envelope="single-batch",
        score_semantics="bounded-score",
    )
    assert (target.task, target.contract) == ("text-classification", "hf-text-classification-v1")
    assert definition.validation_target == CLASSIFIER_ALIAS
    assert definition.target(CLASSIFIER_ALIAS) is target
    assert definition.model_id(target) == f"{ENDPOINT_A}/{CLASSIFIER_ALIAS}"
    assert (definition.chat_targets, definition.classifier_targets) == ((), (target,))


@pytest.mark.parametrize("envelope", ["flat", "single-batch"])
def test_both_response_envelopes_parse(envelope: str) -> None:
    config = parse_remote_endpoint_config(_classifier_only(response_envelope=envelope))

    (target,) = config.endpoints[0].classifier_targets
    assert target.response_envelope == envelope


@pytest.mark.parametrize("validation_target", [ALIAS, CLASSIFIER_ALIAS])
def test_a_classifier_sits_next_to_a_chat_target(validation_target: str) -> None:
    doc = document(
        endpoint(targets=[chat_target(), classifier_target()], validation_target=validation_target)
    )

    (definition,) = parse_remote_endpoint_config(doc).endpoints

    chat, classifier = definition.targets
    assert isinstance(chat, ChatTarget)
    assert isinstance(classifier, ClassificationTarget)
    assert definition.chat_targets == (chat,)
    assert definition.classifier_targets == (classifier,)
    assert definition.validation_target == validation_target


# --- refused at the location, without the value -------------------------------------------------


def test_a_classifier_carrying_an_upstream_model_is_refused() -> None:
    message = _refusal(_classifier_only(upstream_model=MARKER))

    assert "endpoints.0.targets.0.upstream_model" in message
    assert MARKER not in message


@pytest.mark.parametrize(
    "field, value", [("response_envelope", "single-batch"), ("score_semantics", "bounded-score")]
)
def test_a_chat_target_carrying_a_classifier_field_is_refused(field: str, value: str) -> None:
    message = _refusal(document(endpoint(targets=[chat_target(**{field: value})])))

    assert f"endpoints.0.targets.0.{field}" in message


@pytest.mark.parametrize(
    "target",
    [
        classifier_target(contract="openai-chat-basic-v1"),
        chat_target(contract="hf-text-classification-v1"),
    ],
    ids=["classifier-with-chat-contract", "chat-with-classifier-contract"],
)
def test_each_incompatible_task_and_contract_pair_is_refused(target: dict[str, Any]) -> None:
    doc = document(endpoint(targets=[target], validation_target=target["alias"]))

    assert "endpoints.0.targets.0.contract" in _refusal(doc)


@pytest.mark.parametrize("task", [MARKER, "embeddings", "Text-Classification", 7, None])
def test_an_unknown_task_is_refused_at_the_task(task: Any) -> None:
    target = classifier_target(task=task)
    if task is None:
        del target["task"]

    message = _refusal(document(endpoint(targets=[target], validation_target=CLASSIFIER_ALIAS)))

    assert "endpoints.0.targets.0.task" in message
    assert MARKER not in message
    # INVARIANT: the location is the document's, not the parser's internal choice of kind.
    assert "targets.0.text-classification" not in message
    assert "targets.0.chat" not in message


@pytest.mark.parametrize("envelope", [MARKER, "batch", None])
def test_a_missing_or_unknown_response_envelope_is_refused(envelope: str | None) -> None:
    doc = _classifier_only(response_envelope=envelope)
    if envelope is None:
        del doc["endpoints"][0]["targets"][0]["response_envelope"]

    message = _refusal(doc)

    assert "endpoints.0.targets.0.response_envelope" in message
    assert MARKER not in message


@pytest.mark.parametrize("semantics", ["raw-score", MARKER, None])
def test_only_bounded_scores_are_accepted(semantics: str | None) -> None:
    doc = _classifier_only(score_semantics=semantics)
    if semantics is None:
        del doc["endpoints"][0]["targets"][0]["score_semantics"]

    message = _refusal(doc)

    assert "endpoints.0.targets.0.score_semantics" in message
    assert MARKER not in message


def test_aliases_are_unique_across_both_kinds() -> None:
    doc = document(endpoint(targets=[chat_target(), classifier_target(alias=ALIAS)]))

    assert "duplicate target alias" in _refusal(doc)


@pytest.mark.parametrize("path", ["relative", "/a/../b", "//other.test/x", "/a?b", "/{model}"])
def test_a_classifier_request_path_follows_the_path_rule(path: str) -> None:
    assert "endpoints.0.targets.0.request_path" in _refusal(_classifier_only(request_path=path))


def test_a_classifier_alias_follows_the_alias_rule() -> None:
    doc = document(endpoint(targets=[classifier_target(alias="Bad/Alias")], validation_target="x"))

    assert "endpoints.0.targets.0.alias" in _refusal(doc)


def test_a_target_that_is_not_a_table_is_refused_at_its_index() -> None:
    doc = document(endpoint())
    doc["endpoints"][0]["targets"] = [MARKER]
    message = _refusal(doc)

    assert "endpoints.0.targets.0" in message
    assert MARKER not in message


def test_the_second_target_is_located_by_its_own_index() -> None:
    doc = document(endpoint(targets=[chat_target(), classifier_target(response_envelope="x")]))

    assert "endpoints.0.targets.1.response_envelope" in _refusal(doc)
