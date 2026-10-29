"""Deployment review refuses a Gateway configured target the Engine would publish (OME-1770).

FEATURE: hosted BYOM, Unit 2. Every target in the Gateway's configured-endpoints file is private:
the Gateway grants it to named accounts. The Engine runs it through an explicit
`[[aigateway.models]]` declaration, and that declaration must say `public_schema = false` and
`web_search = false`. The first keeps the route out of the shared schema; the second keeps the
Tavily tool loop off a contract that refuses tools.

WHY a review step and not a startup check: neither process holds both files. The Gateway's file
carries endpoint URLs and grants and never reaches the Engine's pods, so the check runs where an
operator holds both, before a rollout.

INVARIANT: the review reads only `endpoints[].id` and `targets[].alias`, and never echoes the
Gateway file, which also holds private origins.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from screamingface_engine import cli, job_env
from screamingface_engine.world.config import WorldConfig, parse_config
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world.publication import (
    PublicationReviewError,
    gateway_target_ids,
    review_endpoint_routes,
)

_ENDPOINT = "byom_" + "0123456789abcdef" * 2
_TARGET = f"{_ENDPOINT}/model_v1"
_PUBLIC = "anthropic/claude-haiku-4-5"
_ORIGIN = "https://private-lab.example"
_GATEWAY = f"""
schema_version = 1

[[endpoints]]
id = "{_ENDPOINT}"
display_name = "Research Lab"
enabled = false
origin = "{_ORIGIN}"
allowed_account_ids = ["acct-1"]
validation_target = "model_v1"

[[endpoints.targets]]
alias = "model_v1"
task = "chat"
contract = "openai-chat-basic-v1"
request_path = "/v1/chat/completions"
upstream_model = "lab/model"

[[endpoints.targets]]
alias = "model_v2"
task = "chat"
contract = "openai-chat-basic-v1"
request_path = "/v1/chat/completions"
upstream_model = "lab/model-2"
"""


def _world(declaration: str) -> WorldConfig:
    text = f'[aigateway]\ndefault_route = "/{_PUBLIC}"\nmodels = ["{_PUBLIC}", {declaration}]\n'
    return parse_config(tomllib.loads(text), {}, registry=EMPTY_MODEL_WORLD)


def test_every_target_of_every_endpoint_is_a_private_id() -> None:
    """A disabled endpoint is still private: disabling it must not publish it."""
    assert gateway_target_ids(_GATEWAY) == {_TARGET, f"{_ENDPOINT}/model_v2"}


def test_a_private_declaration_passes() -> None:
    world = _world(f'{{ id = "{_TARGET}", web_search = false, public_schema = false }}')

    assert review_endpoint_routes(world, gateway_target_ids(_GATEWAY)) == ()


def test_a_target_declared_with_the_public_default_is_refused() -> None:
    problems = review_endpoint_routes(
        _world(f'{{ id = "{_TARGET}", web_search = false }}'), gateway_target_ids(_GATEWAY)
    )

    assert len(problems) == 1
    assert _TARGET in problems[0] and "public_schema = false" in problems[0]


def test_a_target_that_would_search_the_web_is_refused() -> None:
    problems = review_endpoint_routes(
        _world(f'{{ id = "{_TARGET}", public_schema = false }}'), gateway_target_ids(_GATEWAY)
    )

    assert len(problems) == 1
    assert _TARGET in problems[0] and "web_search = false" in problems[0]


def test_a_bare_declaration_names_both_problems() -> None:
    problems = review_endpoint_routes(_world(f'"{_TARGET}"'), gateway_target_ids(_GATEWAY))

    assert len(problems) == 2


def test_a_target_the_engine_does_not_declare_is_not_a_problem() -> None:
    """Undeclared means not runnable through this Engine, which publishes nothing."""
    world = _world('"openrouter/openai/gpt-5.5"')

    assert review_endpoint_routes(world, gateway_target_ids(_GATEWAY)) == ()


@pytest.mark.parametrize(
    "document",
    [
        f'schema_version = 1\norigin = "{_ORIGIN}\n',
        f'schema_version = 1\n[[endpoints]]\norigin = "{_ORIGIN}"\n',
        f'schema_version = 1\n[[endpoints]]\nid = "{_ENDPOINT}"\norigin = "{_ORIGIN}"\n',
        f'schema_version = 1\nendpoints = "{_ORIGIN}"\n',
    ],
)
def test_an_unreadable_gateway_file_is_refused_without_echoing_it(document: str) -> None:
    with pytest.raises(PublicationReviewError) as refused:
        gateway_target_ids(document)

    assert "private-lab" not in str(refused.value)


# --- the operator command -------------------------------------------------------------------


def _files(tmp_path: Path, declaration: str) -> tuple[Path, Path]:
    world = tmp_path / "url4.toml"
    world.write_text(
        f'[aigateway]\ndefault_route = "/{_PUBLIC}"\n\n[[aigateway.models]]\n{declaration}\n'
    )
    endpoints = tmp_path / "endpoints.toml"
    endpoints.write_text(_GATEWAY)
    return world, endpoints


def test_the_command_fails_and_names_each_published_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world, endpoints = _files(tmp_path, f'id = "{_TARGET}"')
    monkeypatch.setenv(job_env.RUNNER_CONFIG, str(world))

    with pytest.raises(SystemExit) as exited:
        cli.main(["admin", "check-publication", "--endpoints", str(endpoints)])

    out = capsys.readouterr()
    assert exited.value.code == 1
    assert _TARGET in out.out
    assert "private-lab" not in out.out + out.err


def test_the_command_passes_a_private_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world, endpoints = _files(
        tmp_path, f'id = "{_TARGET}"\nweb_search = false\npublic_schema = false'
    )
    monkeypatch.setenv(job_env.RUNNER_CONFIG, str(world))

    cli.main(["admin", "check-publication", "--endpoints", str(endpoints)])

    assert "1 of 2 configured target(s) declared" in capsys.readouterr().out


def test_the_command_reports_an_unreadable_file_without_its_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world, endpoints = _files(tmp_path, f'id = "{_TARGET}"')
    endpoints.write_text(f'origin = "{_ORIGIN}')
    monkeypatch.setenv(job_env.RUNNER_CONFIG, str(world))

    with pytest.raises(SystemExit) as exited:
        cli.main(["admin", "check-publication", "--endpoints", str(endpoints)])

    out = capsys.readouterr()
    assert exited.value.code == 2
    assert "private-lab" not in out.out + out.err
