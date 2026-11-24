"""Routing profiles in the declared world file: `[routing.profiles.<id>]` (OME-1822).

FEATURE: BYOM routing pilot (spec 3.1). A profile binds one classifier and exactly the labels
`general`, `code` and `math` to declared chat routes, each with its own `max_tokens`. Every rule
is local and structural and fails startup, so a world the App serves is a world every run reads
the same way.

INVARIANT: a refusal names the profile and the key, never a value. The world file can be a
mounted Secret, and its model IDs are private routes (`public_schema = false`).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tomllib
from typing import Any

import pytest

from screamingface_engine.world.config import WorldConfig, WorldConfigError, parse_config
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD

_ENDPOINT = "byom_" + "0123456789abcdef" * 2
_GENERAL = f"{_ENDPOINT}/general"
_CODE = f"{_ENDPOINT}/code"
_MATH = f"{_ENDPOINT}/math"
_SPARE = f"{_ENDPOINT}/spare"
_CLASSIFIER = f"{_ENDPOINT}/model_router_v1"
_PROFILE_ID = "expert_router_v1"
_REVISION = re.compile(r"sha256:[0-9a-f]{64}")

_GATEWAY = f"""
[aigateway]
base_url = "http://aigateway.test"
default_route = "/{_GENERAL}"

[[aigateway.models]]
id = "{_GENERAL}"
web_search = false
public_schema = false

[[aigateway.models]]
id = "{_CODE}"
web_search = false
public_schema = false

[[aigateway.models]]
id = "{_MATH}"
web_search = false
public_schema = false

[[aigateway.models]]
id = "{_SPARE}"
web_search = false
public_schema = false

[[aigateway.models]]
id = "plain"
web_search = false
"""

_PROFILE_TOML = f"""
[routing.profiles.{_PROFILE_ID}]
classifier = "{_CLASSIFIER}"
classifier_contract = "classification-scores-v1"
policy = "unique-argmax-v1"

[routing.profiles.{_PROFILE_ID}.branches.general]
model = "{_GENERAL}"
max_tokens = 1024

[routing.profiles.{_PROFILE_ID}.branches.code]
model = "{_CODE}"
max_tokens = 2048

[routing.profiles.{_PROFILE_ID}.branches.math]
model = "{_MATH}"
max_tokens = 512
"""


def _profile() -> dict[str, Any]:
    return copy.deepcopy(tomllib.loads(_PROFILE_TOML)["routing"]["profiles"][_PROFILE_ID])


def _parse(routing: object, *, gateway: bool = True) -> WorldConfig:
    raw: dict[str, Any] = tomllib.loads(_GATEWAY) if gateway else {}
    raw["routing"] = routing
    return parse_config(raw, {}, registry=EMPTY_MODEL_WORLD)


def _with(profile: dict[str, Any], profile_id: str = _PROFILE_ID) -> WorldConfig:
    return _parse({"profiles": {profile_id: profile}})


def _refused(profile: dict[str, Any], *keys: str) -> str:
    """The refusal message for one bad profile, checked to name the profile and each key."""
    with pytest.raises(WorldConfigError) as caught:
        _with(profile)
    message = str(caught.value)
    assert _PROFILE_ID in message
    for key in keys:
        assert key in message
    return message


# --- a valid profile ------------------------------------------------------------------------------


def test_the_spec_profile_parses_with_its_branches_in_file_order() -> None:
    profile = _parse(tomllib.loads(_PROFILE_TOML)["routing"]).routing[_PROFILE_ID]

    assert profile.id == _PROFILE_ID
    assert profile.classifier == _CLASSIFIER
    assert profile.classifier_contract == "classification-scores-v1"
    assert profile.policy == "unique-argmax-v1"
    assert [(b.label, b.model, b.max_tokens) for b in profile.branches] == [
        ("general", _GENERAL, 1024),
        ("code", _CODE, 2048),
        ("math", _MATH, 512),
    ]
    assert _REVISION.fullmatch(profile.revision)


def test_a_full_world_file_reads_the_routing_table_beside_the_gateway() -> None:
    config = parse_config(tomllib.loads(_GATEWAY + _PROFILE_TOML), {}, registry=EMPTY_MODEL_WORLD)

    assert list(config.routing) == [_PROFILE_ID]


def test_a_world_without_routing_has_no_profiles() -> None:
    gateway = parse_config(tomllib.loads(_GATEWAY), {}, registry=EMPTY_MODEL_WORLD)
    tokenless = parse_config({}, {}, registry=EMPTY_MODEL_WORLD)

    assert gateway.routing == {}
    assert gateway.aigateway is not None
    assert tokenless == WorldConfig()


def test_two_labels_may_share_one_model() -> None:
    profile = _profile()
    profile["branches"]["math"]["model"] = _GENERAL

    branches = _with(profile).routing[_PROFILE_ID].branches

    assert [b.model for b in branches] == [_GENERAL, _CODE, _GENERAL]


def test_several_profiles_parse_independently() -> None:
    other = _profile()
    other["branches"]["code"]["model"] = _SPARE

    routing = _parse({"profiles": {_PROFILE_ID: _profile(), "second_v1": other}}).routing

    assert list(routing) == [_PROFILE_ID, "second_v1"]
    assert routing["second_v1"].branches[1].model == _SPARE
    assert routing[_PROFILE_ID].revision != routing["second_v1"].revision


@pytest.mark.parametrize("max_tokens", [1, 32768])
def test_max_tokens_accepts_both_bounds(max_tokens: int) -> None:
    profile = _profile()
    profile["branches"]["general"]["max_tokens"] = max_tokens

    assert _with(profile).routing[_PROFILE_ID].branches[0].max_tokens == max_tokens


# --- revision -------------------------------------------------------------------------------------


def test_the_revision_is_the_digest_of_the_canonical_profile_json() -> None:
    profile = _with(_profile()).routing[_PROFILE_ID]
    canonical = {
        "id": _PROFILE_ID,
        "classifier": _CLASSIFIER,
        "classifier_contract": "classification-scores-v1",
        "policy": "unique-argmax-v1",
        "branches": {
            "general": {"model": _GENERAL, "max_tokens": 1024},
            "code": {"model": _CODE, "max_tokens": 2048},
            "math": {"model": _MATH, "max_tokens": 512},
        },
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()

    assert profile.revision == "sha256:" + hashlib.sha256(encoded).hexdigest()


def test_the_revision_is_stable_across_parses_and_table_order() -> None:
    first = _with(_profile()).routing[_PROFILE_ID].revision
    reordered = _profile()
    reordered["branches"] = dict(reversed(list(reordered["branches"].items())))

    assert _with(_profile()).routing[_PROFILE_ID].revision == first
    assert _with(reordered).routing[_PROFILE_ID].revision == first


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("classifier",), f"{_ENDPOINT}/model_router_v2"),
        (("branches", "code", "model"), _SPARE),
        (("branches", "math", "max_tokens"), 513),
    ],
)
def test_the_revision_changes_with_any_bound_value(path: tuple[str, ...], value: object) -> None:
    before = _with(_profile()).routing[_PROFILE_ID].revision
    changed = _profile()
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    assert _with(changed).routing[_PROFILE_ID].revision != before


def test_the_revision_changes_with_the_profile_id() -> None:
    before = _with(_profile()).routing[_PROFILE_ID].revision

    assert _with(_profile(), "expert_router_v2").routing["expert_router_v2"].revision != before


# --- R1: the [routing] table ----------------------------------------------------------------------


def test_routing_requires_the_gateway() -> None:
    with pytest.raises(WorldConfigError, match=r"\[routing\] requires \[aigateway\]"):
        _parse({"profiles": {_PROFILE_ID: _profile()}}, gateway=False)


@pytest.mark.parametrize(
    "routing",
    [
        pytest.param("profiles", id="not-a-table"),
        pytest.param({}, id="no-profiles"),
        pytest.param({"profiles": {}}, id="empty-profiles"),
        pytest.param({"profiles": ["expert_router_v1"]}, id="profiles-not-a-table"),
    ],
)
def test_routing_needs_a_non_empty_profiles_table(routing: object) -> None:
    with pytest.raises(WorldConfigError, match=r"\[routing\]"):
        _parse(routing)


def test_routing_has_no_key_but_profiles() -> None:
    with pytest.raises(WorldConfigError, match=r"\[routing\].*'default'"):
        _parse({"profiles": {_PROFILE_ID: _profile()}, "default": _PROFILE_ID})


# --- R2: profile ID and keys ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "profile_id",
    ["Expert", "1router", "_router", "expert-router", "expert.router", "e" * 65, ""],
)
def test_a_profile_id_is_lowercase_snake_case_up_to_64(profile_id: str) -> None:
    with pytest.raises(WorldConfigError, match="profile ID"):
        _with(_profile(), profile_id)


def test_a_profile_id_of_64_characters_is_accepted() -> None:
    profile_id = "e" * 64

    assert list(_with(_profile(), profile_id).routing) == [profile_id]


def test_a_profile_must_be_a_table() -> None:
    with pytest.raises(WorldConfigError, match=_PROFILE_ID):
        _parse({"profiles": {_PROFILE_ID: _CLASSIFIER}})


@pytest.mark.parametrize("key", ["classifier", "classifier_contract", "policy", "branches"])
def test_a_profile_needs_every_key(key: str) -> None:
    profile = _profile()
    del profile[key]

    _refused(profile, key)


def test_a_profile_takes_no_other_key() -> None:
    profile = _profile()
    profile["fallback"] = "general"

    _refused(profile, "fallback")


# --- R3: classifier -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "classifier",
    [
        pytest.param("model_router_v1", id="no-provider"),
        pytest.param("/model_router_v1", id="empty-provider"),
        pytest.param(f"{_ENDPOINT}/", id="empty-alias"),
        pytest.param(7, id="not-a-string"),
    ],
)
def test_a_classifier_is_a_provider_prefixed_id(classifier: object) -> None:
    profile = _profile()
    profile["classifier"] = classifier

    message = _refused(profile, "classifier")

    assert str(classifier) not in message


def test_a_classifier_is_not_checked_against_the_declared_routes() -> None:
    # WHY (R3): the Gateway owns classifiers (Unit 3); no Engine list names them.
    profile = _profile()
    profile["classifier"] = "other_provider/any_classifier"

    assert _with(profile).routing[_PROFILE_ID].classifier == "other_provider/any_classifier"


# --- R4: contract and policy ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("classifier_contract", "classification-scores-v2"),
        ("classifier_contract", 1),
        ("policy", "argmax-v1"),
        ("policy", "unique-argmax-v2"),
    ],
)
def test_only_the_supported_contract_and_policy_are_accepted(key: str, value: object) -> None:
    profile = _profile()
    profile[key] = value

    _refused(profile, key)


# --- R5: labels -----------------------------------------------------------------------------------


def test_a_fourth_label_is_refused() -> None:
    profile = _profile()
    profile["branches"]["legal"] = {"model": _SPARE, "max_tokens": 64}

    _refused(profile, "branches", "legal")


def test_a_missing_label_is_refused() -> None:
    profile = _profile()
    del profile["branches"]["math"]

    _refused(profile, "branches", "math")


def test_a_renamed_label_is_refused() -> None:
    profile = _profile()
    profile["branches"]["maths"] = profile["branches"].pop("math")

    _refused(profile, "branches", "math")


def test_branches_must_be_a_table() -> None:
    profile = _profile()
    profile["branches"] = [_GENERAL, _CODE, _MATH]

    _refused(profile, "branches")


# --- R6: branch keys and model --------------------------------------------------------------------


def test_temperature_is_not_a_branch_parameter() -> None:
    # WHY (R7): `openai-chat-basic-v1` carries `max_tokens` and no other generation parameter.
    profile = _profile()
    profile["branches"]["code"]["temperature"] = 0.2

    _refused(profile, "code", "temperature")


@pytest.mark.parametrize("key", ["model", "max_tokens"])
def test_a_branch_needs_model_and_max_tokens(key: str) -> None:
    profile = _profile()
    del profile["branches"]["general"][key]

    _refused(profile, "general", key)


def test_a_branch_must_be_a_table() -> None:
    profile = _profile()
    profile["branches"]["general"] = _GENERAL

    _refused(profile, "general")


@pytest.mark.parametrize(
    "model",
    [
        pytest.param(f"{_ENDPOINT}/undeclared", id="undeclared"),
        pytest.param(f"/{_GENERAL}", id="route-path"),
        pytest.param("plain", id="declared-without-provider"),
        pytest.param(42, id="not-a-string"),
    ],
)
def test_a_branch_model_is_a_declared_provider_prefixed_route(model: object) -> None:
    profile = _profile()
    profile["branches"]["general"]["model"] = model

    message = _refused(profile, "general", "model")

    assert str(model) not in message


# --- R7: max_tokens -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "max_tokens",
    [
        pytest.param(True, id="boolean"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(32769, id="above-maximum"),
        pytest.param(1024.0, id="float"),
        pytest.param("1024", id="string"),
    ],
)
def test_max_tokens_is_an_integer_in_range(max_tokens: object) -> None:
    profile = _profile()
    profile["branches"]["code"]["max_tokens"] = max_tokens

    message = _refused(profile, "code", "max_tokens")

    assert repr(max_tokens) not in message
