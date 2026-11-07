"""Deployment review refuses a Gateway classifier declared as an Engine model (OME-1795).

FEATURE: hosted BYOM, Unit 3. A classifier runs through `/classify` with its ID in the request, so
it needs no `[[aigateway.models]]` entry. Declared as one, it would be a chat route the Gateway
refuses on every call with `invalid_model`; the review catches that before a rollout instead.

INVARIANT: the review reads only `endpoints[].id` and `targets[].alias` and `targets[].task`, and
never echoes the Gateway file, which also holds private origins.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from screamingface_engine import cli, job_env
from screamingface_engine.world.config import WorldConfig, parse_config
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world.publication import (
    gateway_classifier_ids,
    gateway_target_ids,
    review_endpoint_routes,
)

_ENDPOINT = "byom_" + "0123456789abcdef" * 2
_CHAT = f"{_ENDPOINT}/model_v1"
_CLASSIFIER = f"{_ENDPOINT}/classifier_v1"
_PUBLIC = "anthropic/claude-haiku-4-5"
_PRIVATE = "web_search = false, public_schema = false"
_GATEWAY = f"""
schema_version = 1

[[endpoints]]
id = "{_ENDPOINT}"
display_name = "Research Lab"
enabled = true
origin = "https://private-lab.example"
allowed_account_ids = ["acct-1"]
validation_target = "model_v1"

[[endpoints.targets]]
alias = "model_v1"
task = "chat"
contract = "openai-chat-basic-v1"
request_path = "/v1/chat/completions"
upstream_model = "lab/model"

[[endpoints.targets]]
alias = "classifier_v1"
task = "text-classification"
contract = "hf-text-classification-v1"
request_path = "/"
response_envelope = "single-batch"
score_semantics = "bounded-score"
"""


def _world(*declarations: str) -> WorldConfig:
    models = ", ".join([f'"{_PUBLIC}"', *declarations])
    text = f'[aigateway]\ndefault_route = "/{_PUBLIC}"\nmodels = [{models}]\n'
    return parse_config(tomllib.loads(text), {}, registry=EMPTY_MODEL_WORLD)


def _review(world: WorldConfig) -> tuple[str, ...]:
    return review_endpoint_routes(
        world, gateway_target_ids(_GATEWAY), classifiers=gateway_classifier_ids(_GATEWAY)
    )


def test_only_a_text_classification_target_is_a_classifier() -> None:
    assert gateway_classifier_ids(_GATEWAY) == {_CLASSIFIER}
    assert gateway_target_ids(_GATEWAY) == {_CHAT, _CLASSIFIER}


@pytest.mark.parametrize(
    "declaration",
    [f'{{ id = "{_CLASSIFIER}", {_PRIVATE} }}', f'"{_CLASSIFIER}"'],
    ids=["private", "bare"],
)
def test_a_classifier_declared_as_an_engine_model_is_one_problem(declaration: str) -> None:
    """One problem whatever the flags: the fix is to remove the entry, not to set them."""
    (problem,) = _review(_world(declaration))

    assert _CLASSIFIER in problem
    assert "classifier" in problem and "/classify" in problem
    assert "private-lab" not in problem


def test_a_private_chat_target_beside_an_undeclared_classifier_passes() -> None:
    assert _review(_world(f'{{ id = "{_CHAT}", {_PRIVATE} }}')) == ()


def test_the_review_without_classifiers_keeps_its_unit_2_answer() -> None:
    """A caller that passes no classifiers gets the chat review alone, as before Unit 3."""
    world = _world(f'{{ id = "{_CLASSIFIER}", {_PRIVATE} }}')

    assert review_endpoint_routes(world, gateway_target_ids(_GATEWAY)) == ()


def test_check_publication_fails_on_a_declared_classifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = tmp_path / "url4.toml"
    world.write_text(
        f'[aigateway]\ndefault_route = "/{_PUBLIC}"\n'
        f'models = ["{_PUBLIC}", {{ id = "{_CLASSIFIER}", {_PRIVATE} }}]\n'
    )
    endpoints = tmp_path / "endpoints.toml"
    endpoints.write_text(_GATEWAY)
    monkeypatch.setenv(job_env.RUNNER_CONFIG, str(world))

    with pytest.raises(SystemExit) as exited:
        cli.main(["admin", "check-publication", "--endpoints", str(endpoints)])

    out = capsys.readouterr()
    assert exited.value.code == 1
    assert _CLASSIFIER in out.out and "1 problem(s)" in out.out
    assert "private-lab" not in out.out + out.err
