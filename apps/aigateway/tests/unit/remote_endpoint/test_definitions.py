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


# FEATURE: hosted BYOM Unit 1 — an operator approves HTTP or HTTPS origins by DNS name or address,
# on any port, including a private host, a loopback server or a Docker service name.
@pytest.mark.parametrize(
    ("origin", "canonical"),
    [
        ("http://endpoint-a.byom.test", "http://endpoint-a.byom.test"),
        ("https://endpoint-a.byom.test:8443", "https://endpoint-a.byom.test:8443"),
        ("https://endpoint-a.byom.test:80", "https://endpoint-a.byom.test:80"),
        ("http://endpoint-a.byom.test:443", "http://endpoint-a.byom.test:443"),
        ("http://localhost", "http://localhost"),
        ("http://lm-studio:1234", "http://lm-studio:1234"),
        ("http://lm_studio:1234", "http://lm_studio:1234"),
        ("http://192.168.1.20:1234", "http://192.168.1.20:1234"),
        ("https://10.0.0.1", "https://10.0.0.1"),
        ("http://127.0.0.1:65535", "http://127.0.0.1:65535"),
        ("http://169.254.10.20:1", "http://169.254.10.20:1"),
        ("https://[::1]", "https://[::1]"),
        ("http://[fd00::20]:8080", "http://[fd00::20]:8080"),
        ("http://[fe80::1]:8080", "http://[fe80::1]:8080"),
    ],
)
def test_approved_origins_are_accepted(origin: str, canonical: str) -> None:
    config = parse_remote_endpoint_config(document(endpoint(origin=origin)))

    assert config.endpoints[0].origin == canonical


@pytest.mark.parametrize(
    ("spelled", "canonical"),
    [
        ("http://endpoint-a.byom.test:80", "http://endpoint-a.byom.test"),
        ("https://endpoint-a.byom.test:443", "https://endpoint-a.byom.test"),
        ("http://192.168.1.20:80", "http://192.168.1.20"),
        ("https://[::1]:443", "https://[::1]"),
    ],
)
def test_the_default_port_of_the_scheme_is_normalized_away(spelled: str, canonical: str) -> None:
    # INVARIANT: one origin has one spelling, so the origin bound into a stored key compares equal
    # however the operator wrote the default port.
    config = parse_remote_endpoint_config(document(endpoint(origin=spelled)))

    assert config.endpoints[0].origin == canonical


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
        "https://endpoint-a.byom.test/",
        "https://endpoint-a.byom.test/v1",
        "https://user:pw@endpoint-a.byom.test",
        "https://endpoint-a.byom.test?x=1",
        "https://endpoint-a.byom.test#frag",
        "https://Endpoint-A.byom.test",
        "https://endpoint-a.byom.test.",
        "https://end\tpoint-a.byom.test",
        "https://-bad.byom.test",
        "endpoint-a.byom.test",
        "https://endpoint-a.byom.test:abc",
    ],
)
def test_non_canonical_origins_are_refused(origin: str) -> None:
    assert "endpoints.0.origin" in _refusal(document(endpoint(origin=origin)))


@pytest.mark.parametrize(
    "origin", ["http://0.0.0.0", "http://0.0.0.0:8080", "http://[::]", "https://[::]:8443"]
)
def test_an_unspecified_address_is_refused_as_a_destination(origin: str) -> None:
    message = _refusal(document(endpoint(origin=origin)))

    assert "endpoints.0.origin: Value error, must not be an unspecified address" in message


@pytest.mark.parametrize(
    "origin",
    [
        "http://[::ffff:10.0.0.1]",
        "http://[::ffff:a00:1]",
        "http://[::FFFF:A00:1]",
        "http://[0:0:0:0:0:ffff:a00:1]",
        "https://[::ffff:c0a8:114]:8443",
    ],
)
def test_ipv4_mapped_ipv6_is_refused_in_every_spelling(origin: str) -> None:
    # WHY the rule is asserted: the parsed address is checked, so a hexadecimal spelling is refused
    # for being IPv4-mapped, not merely for being a non-canonical IPv6 spelling.
    message = _refusal(document(endpoint(origin=origin)))

    assert "endpoints.0.origin: Value error, must write an IPv4 address in dotted form" in message


@pytest.mark.parametrize(
    "origin", ["http://[private-host]", "https://[private-host]:8443", "http://[private-host"]
)
def test_a_bracketed_host_that_is_no_address_is_refused_without_echo(origin: str) -> None:
    # WHY: the URL parser's own error quotes the bracketed text, so it must not reach the refusal.
    message = _refusal(document(endpoint(origin=origin)))

    assert "endpoints.0.origin" in message
    assert "private-host" not in message


def test_an_ipv6_zone_is_refused() -> None:
    message = _refusal(document(endpoint(origin="http://[fe80::1%25eth0]:8080")))

    assert "endpoints.0.origin: Value error, must not carry an IPv6 zone" in message


@pytest.mark.parametrize(
    "origin",
    [
        # Numbers a resolver would read as an IPv4 address in another spelling.
        "http://010.0.0.1",
        "http://10.0.0.01",
        "http://10.1",
        "http://0",
        "http://2130706433",
        "http://0x7f000001",
        "http://0x0",
        "http://localhost.0x1",
        # IPv6 outside its one canonical spelling, dotted IPv4 notation included.
        "http://fd00::1",
        "http://[FD00::1]",
        "http://[fd00:0::1]",
        "http://[::10.0.0.1]",
        # Ports outside 1 to 65535, or spelled otherwise than in decimal.
        "http://endpoint-a.byom.test:0",
        "http://endpoint-a.byom.test:65536",
        "http://endpoint-a.byom.test:080",
        "http://endpoint-a.byom.test:",
        "http://endpoint-a.byom.test:+80",
        # Other schemes, or a scheme not in lower case.
        "ftp://endpoint-a.byom.test",
        "ws://endpoint-a.byom.test",
        "HTTP://endpoint-a.byom.test",
        "http:/endpoint-a.byom.test",
        "http://",
        # Labels a resolver would not take as written.
        "http://_lm-studio",
        "http://lm-studio_",
        "http://lm..studio",
        # Anything after the authority.
        "http://192.168.1.20:1234/",
        "http://192.168.1.20:1234/v1",
        "http://user@192.168.1.20:1234",
        "http://[::1]?x=1",
    ],
)
def test_unapproved_origins_are_refused(origin: str) -> None:
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
