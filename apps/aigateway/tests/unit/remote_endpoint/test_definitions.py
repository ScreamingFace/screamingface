"""Schema v1 validation of configured remote endpoints into immutable definitions.

# FEATURE: hosted BYOM Unit 0 — one validation boundary, independent of any file format, turns an
# operator document into endpoint definitions plus a SEPARATE grant view.
# INVARIANT: unknown fields, superseded forms, collisions and unsafe URL parts are refused, and a
# refusal names where and why without echoing the offending value.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from aigateway.plugins.remote_endpoint.definitions import (
    EndpointGrant,
    RemoteEndpointConfigError,
    parse_remote_endpoint_config,
)

from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    ALIAS,
    CHAT_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    ORIGIN_A,
    ORIGIN_B,
    UPSTREAM_MODEL,
    chat_target,
    document,
    endpoint,
    two_endpoint_document,
)


def _refusal(doc: Any) -> str:
    with pytest.raises(RemoteEndpointConfigError) as caught:
        parse_remote_endpoint_config(doc)
    # WHY: a chained pydantic error would carry the raw input into any traceback.
    error = caught.value
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__
    return str(error)


# --- accepted -----------------------------------------------------------------------------------


def test_two_endpoints_become_ordered_definitions_with_canonical_targets() -> None:
    config = parse_remote_endpoint_config(two_endpoint_document())

    assert [d.id for d in config.endpoints] == [ENDPOINT_A, ENDPOINT_B]
    first, second = config.endpoints
    assert (first.origin, second.origin) == (ORIGIN_A, ORIGIN_B)
    assert first.validation_target == ALIAS
    (target,) = first.targets
    assert (target.alias, target.task, target.contract) == (ALIAS, "chat", "openai-chat-basic-v1")
    assert (target.request_path, target.upstream_model) == (CHAT_PATH, UPSTREAM_MODEL)
    assert first.model_id(target) == f"{ENDPOINT_A}/{ALIAS}"
    assert first.target(ALIAS) is target
    assert first.target("absent") is None
    # INVARIANT: the same upstream model name on both endpoints is legal and stays distinct by ID.
    assert second.targets[0].upstream_model == UPSTREAM_MODEL


def test_grants_are_a_separate_view_and_definitions_carry_none() -> None:
    config = parse_remote_endpoint_config(two_endpoint_document(b_enabled=False))

    assert dict(config.grants) == {
        ENDPOINT_A: EndpointGrant(enabled=True, account_ids=frozenset({ACCOUNT_A, ACCOUNT_B})),
        ENDPOINT_B: EndpointGrant(enabled=False, account_ids=frozenset({ACCOUNT_A})),
    }
    # WHY: a plugin instance receives a definition; grant arrays must never reach it.
    names = {field.name for field in dataclasses.fields(config.endpoints[0])}
    assert names == {"id", "display_name", "origin", "validation_target", "targets"}


def test_definitions_are_immutable() -> None:
    config = parse_remote_endpoint_config(two_endpoint_document())

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(config.endpoints[0], "origin", "https://elsewhere.byom.test")
    grants: Any = config.grants
    with pytest.raises(TypeError):
        grants[ENDPOINT_A] = EndpointGrant(enabled=True, account_ids=frozenset())


def test_an_explicit_443_is_normalized_away() -> None:
    config = parse_remote_endpoint_config(document(endpoint(origin=ORIGIN_A + ":443")))

    assert config.endpoints[0].origin == ORIGIN_A


def test_an_empty_grant_list_is_valid_and_grants_nobody() -> None:
    config = parse_remote_endpoint_config(document(endpoint(accounts=())))

    assert config.grants[ENDPOINT_A].account_ids == frozenset()


def test_a_document_without_endpoints_configures_none() -> None:
    assert parse_remote_endpoint_config({"schema_version": 1}).endpoints == ()


def test_root_path_and_several_targets_are_accepted() -> None:
    targets = [chat_target(), chat_target(alias="model_v2", request_path="/")]
    config = parse_remote_endpoint_config(document(endpoint(targets=targets)))

    assert [t.request_path for t in config.endpoints[0].targets] == [CHAT_PATH, "/"]


# --- refused ------------------------------------------------------------------------------------


def test_a_non_mapping_document_is_refused() -> None:
    assert "document" in _refusal(["schema_version", 1])


@pytest.mark.parametrize("version", [None, 0, 2, "1", True])
def test_only_schema_version_1_is_accepted(version: Any) -> None:
    doc = document(endpoint())
    if version is None:
        del doc["schema_version"]
    else:
        doc["schema_version"] = version

    assert "schema_version" in _refusal(doc)


@pytest.mark.parametrize(
    "doc, location",
    [
        (document(endpoint(), extra=1), "extra"),
        (document(endpoint(region="eu")), "endpoints.0.region"),
        (document(endpoint(targets=[chat_target(headers="x")])), "endpoints.0.targets.0.headers"),
    ],
)
def test_unknown_fields_are_refused_at_every_level(doc: dict[str, Any], location: str) -> None:
    assert location in _refusal(doc)


@pytest.mark.parametrize("field", ["base_url", "models", "classifiers"])
def test_superseded_endpoint_forms_are_refused(field: str) -> None:
    superseded: dict[str, Any] = {field: "https://old.byom.test/v1"}
    doc = document(endpoint(**superseded))

    assert f"endpoints.0.{field}" in _refusal(doc)


@pytest.mark.parametrize(
    "endpoint_id",
    ["", "byom_" + "a" * 31, "byom_" + "A" * 32, "byom_" + "g" * 32, "anthropic", "a" * 37],
)
def test_endpoint_ids_must_be_byom_and_32_lowercase_hex(endpoint_id: str) -> None:
    assert "endpoints.0.id" in _refusal(document(endpoint(endpoint_id)))


@pytest.mark.parametrize(
    "origin",
    [
        "http://endpoint-a.byom.test",
        "https://endpoint-a.byom.test:8443",
        "https://endpoint-a.byom.test/",
        "https://endpoint-a.byom.test/v1",
        "https://user:pw@endpoint-a.byom.test",
        "https://endpoint-a.byom.test?x=1",
        "https://endpoint-a.byom.test#frag",
        "https://Endpoint-A.byom.test",
        "https://endpoint-a.byom.test.",
        "https://10.0.0.1",
        "https://[::1]",
        "https://localhost",
        "https://end\tpoint-a.byom.test",
        "https://-bad.byom.test",
        "endpoint-a.byom.test",
        "https://endpoint-a.byom.test:abc",
    ],
)
def test_origins_must_be_canonical_https_443_hostnames(origin: str) -> None:
    assert "endpoints.0.origin" in _refusal(document(endpoint(origin=origin)))


@pytest.mark.parametrize(
    "path",
    [
        "",
        "v1/chat/completions",
        "//attacker.byom.test/v1",
        "https://attacker.byom.test/v1",
        "/v1/../admin",
        "/v1/./chat",
        "/v1/chat/completions/",
        "/v1/{model}/chat",
        "/v1/chat?x=1",
        "/v1/chat#x",
        "/v1/%2e%2e/admin",
        "/v1/chat completions",
    ],
)
def test_request_paths_must_be_fixed_same_origin_paths(path: str) -> None:
    doc = document(endpoint(targets=[chat_target(request_path=path)]))

    assert "endpoints.0.targets.0.request_path" in _refusal(doc)


@pytest.mark.parametrize("alias", ["", "Model", "a/b", "-a", "a-", "a" * 65, "mödel"])
def test_aliases_are_route_safe(alias: str) -> None:
    doc = document(endpoint(targets=[chat_target(alias=alias)], validation_target=alias))

    assert "endpoints.0.targets.0.alias" in _refusal(doc)


@pytest.mark.parametrize("upstream", ["", "has space", "x" * 257, "tab\tmodel"])
def test_upstream_model_names_are_bounded_printable_ascii(upstream: str) -> None:
    doc = document(endpoint(targets=[chat_target(upstream_model=upstream)]))

    assert "endpoints.0.targets.0.upstream_model" in _refusal(doc)


def test_a_chat_target_requires_an_upstream_model() -> None:
    target = chat_target()
    del target["upstream_model"]

    assert "endpoints.0.targets.0.upstream_model" in _refusal(document(endpoint(targets=[target])))


@pytest.mark.parametrize(
    "overrides, location",
    [
        ({"task": "text-classification"}, "task"),
        ({"contract": "openai-chat-full-v1"}, "contract"),
    ],
)
def test_unsupported_tasks_and_contracts_are_refused(
    overrides: dict[str, Any], location: str
) -> None:
    doc = document(endpoint(targets=[chat_target(**overrides)]))

    assert f"endpoints.0.targets.0.{location}" in _refusal(doc)


@pytest.mark.parametrize("name", ["", " padded ", "x" * 129, "line\nbreak"])
def test_display_names_are_bounded_and_printable(name: str) -> None:
    assert "endpoints.0.display_name" in _refusal(document(endpoint(display_name=name)))


@pytest.mark.parametrize(
    "accounts",
    [
        ("not-a-uuid",),
        ("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa".upper(),),
        ("{" + ACCOUNT_A + "}",),
        (ACCOUNT_A.replace("-", ""),),
        (ACCOUNT_A, ACCOUNT_A),
    ],
)
def test_account_grants_must_be_distinct_canonical_uuids(accounts: tuple[str, ...]) -> None:
    assert "endpoints.0.allowed_account_ids" in _refusal(document(endpoint(accounts=accounts)))


@pytest.mark.parametrize("value", ["true", 1, None])
def test_enabled_must_be_an_explicit_boolean(value: Any) -> None:
    table = endpoint()
    if value is None:
        del table["enabled"]
    else:
        table["enabled"] = value

    assert "endpoints.0.enabled" in _refusal(document(table))


def test_duplicate_endpoint_ids_are_refused() -> None:
    doc = document(endpoint(ENDPOINT_A), endpoint(ENDPOINT_A, origin=ORIGIN_B))

    assert "duplicate endpoint id" in _refusal(doc)


def test_duplicate_aliases_within_an_endpoint_are_refused() -> None:
    doc = document(endpoint(targets=[chat_target(), chat_target(request_path="/")]))

    assert "duplicate target alias" in _refusal(doc)


def test_the_validation_target_must_name_a_declared_alias() -> None:
    assert "validation_target" in _refusal(document(endpoint(validation_target="model_v9")))


def test_an_endpoint_needs_at_least_one_target() -> None:
    assert "endpoints.0.targets" in _refusal(document(endpoint(targets=[])))


def test_refusals_never_echo_the_offending_value() -> None:
    secretish = "https://private-research-host.internal.example:8443/secret-path"
    message = _refusal(document(endpoint(origin=secretish), endpoint(ENDPOINT_B, region="x")))

    assert "private-research-host" not in message
    assert "secret-path" not in message
    assert "8443" not in message
