"""Dynamic-choice named profiles in the world file (Unit 5.2, contracts C2, C3 and C16).

FEATURE: Router Recipe extension. A named profile may state `revision_scheme =
"router-definition-v1"` and `instructions`, and give each branch a `description`. Its labels are
then any C16 labels, in table order, and it normalizes to a `ChoiceScoring` router definition `D`
whose C3 revision is the profile's revision.

INVARIANT: a fixed profile keeps exactly its keys, its three labels and its legacy revision bytes;
a mixed, missing, extra or mistyped key fails startup, naming the field and rule, never a value.
"""

from __future__ import annotations

import copy
import tomllib
from datetime import date
from typing import Any

import pytest

from screamingface_engine.world.config import WorldConfig, WorldConfigError, parse_config
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world.router_spec import Definition, canonical, definition_revision

_PROFILE_ID = "choice_router_v1"
_CLASSIFIER = "laya/router"
_CODE = "openrouter/openai/gpt-4o-mini"
_GENERAL = "openrouter/meta-llama/llama-3.1-70b-instruct"
_TILDED = "openrouter/qwen/qwen3-8b~free"
_INSTRUCTIONS = "Pick the expert for the question."

_GATEWAY = f"""
[aigateway]
base_url = "http://aigateway.test"
default_route = "/plain"

[[aigateway.models]]
id = "{_CODE}"
web_search = false

[[aigateway.models]]
id = "{_GENERAL}"
web_search = false

[[aigateway.models]]
id = "{_TILDED}"
web_search = false

[[aigateway.models]]
id = "plain"
web_search = false
"""

_PROFILE_TOML = f"""
[routing.profiles.{_PROFILE_ID}]
classifier = "{_CLASSIFIER}"
classifier_contract = "classification-scores-v1"
policy = "unique-argmax-v1"
revision_scheme = "router-definition-v1"
instructions = "{_INSTRUCTIONS}"

[routing.profiles.{_PROFILE_ID}.branches.code]
model = "{_CODE}"
max_tokens = 2048
description = "Programming questions."

[routing.profiles.{_PROFILE_ID}.branches.general]
model = "{_GENERAL}"
max_tokens = 1024
description = "Everything else."
"""


def _profile() -> dict[str, Any]:
    return copy.deepcopy(tomllib.loads(_PROFILE_TOML)["routing"]["profiles"][_PROFILE_ID])


def _parse(profiles: dict[str, Any]) -> WorldConfig:
    raw: dict[str, Any] = tomllib.loads(_GATEWAY)
    raw["routing"] = {"profiles": profiles}
    return parse_config(raw, {}, registry=EMPTY_MODEL_WORLD)


def _with(profile: dict[str, Any]) -> WorldConfig:
    return _parse({_PROFILE_ID: profile})


def _refused(profile: dict[str, Any], *fields: str) -> str:
    with pytest.raises(WorldConfigError) as caught:
        _with(profile)
    message = str(caught.value)
    assert _PROFILE_ID in message
    for name in fields:
        assert name in message
    return message


def _candidate(label: str, description: str, model: str, max_tokens: int) -> dict[str, Any]:
    return {
        "label": label,
        "description": description,
        "model": {
            "model": model,
            "prompt": None,
            "params": {"max_tokens": str(max_tokens), "web_search": "false"},
        },
    }


def _expected_definition() -> dict[str, Any]:
    return {
        "classifier": {
            "source": "scoring",
            "model": _CLASSIFIER,
            "contract": "classification-scores-v1",
            "input": "choice",
            "instructions": _INSTRUCTIONS,
        },
        "policy": {"type": "unique-argmax-v1"},
        "candidates": [
            _candidate("code", "Programming questions.", _CODE, 2048),
            _candidate("general", "Everything else.", _GENERAL, 1024),
        ],
        "default": None,
        "synthesizer": None,
        "quorum": None,
    }


# --- a valid dynamic profile ----------------------------------------------------------------------


def test_a_dynamic_profile_parses_with_its_choices_in_table_order() -> None:
    profile = _with(_profile()).routing[_PROFILE_ID]

    assert profile.revision_scheme == "router-definition-v1"
    assert profile.instructions == _INSTRUCTIONS
    assert profile.classifier_contract == "classification-scores-v1"
    assert profile.policy == "unique-argmax-v1"
    assert [(b.label, b.model, b.max_tokens, b.description) for b in profile.branches] == [
        ("code", _CODE, 2048, "Programming questions."),
        ("general", _GENERAL, 1024, "Everything else."),
    ]


def test_the_dynamic_revision_is_the_c3_revision_of_the_normalized_definition() -> None:
    expected = _expected_definition()
    Definition.model_validate_json(canonical(expected))  # the normalized D is a valid C2 record

    assert _with(_profile()).routing[_PROFILE_ID].revision == definition_revision(expected)


def test_the_normalized_model_is_the_canonical_gateway_id() -> None:
    profile = _profile()
    profile["branches"]["code"]["model"] = _TILDED
    expected = _expected_definition()
    expected["candidates"][0]["model"]["model"] = "openrouter/qwen/qwen3-8b:free"

    parsed = _with(profile).routing[_PROFILE_ID]

    assert parsed.branches[0].model == _TILDED
    assert parsed.revision == definition_revision(expected)


def test_any_c16_labels_bind_in_a_dynamic_profile() -> None:
    profile = _profile()
    profile["branches"] = {
        "légal ✓": {"model": _CODE, "max_tokens": 1, "description": "x"},
        "x" * 64: {"model": _GENERAL, "max_tokens": 32768, "description": "y" * 1024},
    }
    profile["instructions"] = "i" * 4096

    labels = [b.label for b in _with(profile).routing[_PROFILE_ID].branches]

    assert labels == ["légal ✓", "x" * 64]


def test_one_label_and_thirty_two_labels_bind() -> None:
    one = _profile()
    del one["branches"]["general"]
    many = _profile()
    many["branches"] = {
        f"l{i}": {"model": _CODE, "max_tokens": 8, "description": "d"} for i in range(32)
    }

    assert len(_with(one).routing[_PROFILE_ID].branches) == 1
    assert len(_with(many).routing[_PROFILE_ID].branches) == 32


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda p: p.update(instructions="Other."), id="instructions"),
        pytest.param(lambda p: p["branches"]["code"].update(description="Code."), id="description"),
        pytest.param(lambda p: p["branches"]["code"].update(max_tokens=2047), id="max_tokens"),
        pytest.param(lambda p: p["branches"]["code"].update(model=_TILDED), id="model"),
        pytest.param(lambda p: p.update(classifier="laya/router2"), id="classifier"),
        pytest.param(
            lambda p: p.update(branches=dict(reversed(list(p["branches"].items())))), id="order"
        ),
    ],
)
def test_every_bound_value_and_the_branch_order_enter_the_revision(change: Any) -> None:
    baseline = _with(_profile()).routing[_PROFILE_ID].revision
    changed = _profile()
    change(changed)

    assert _with(changed).routing[_PROFILE_ID].revision != baseline


def test_the_profile_id_does_not_enter_the_revision() -> None:
    routing = _parse({_PROFILE_ID: _profile(), "second_v1": _profile()}).routing

    assert routing[_PROFILE_ID].revision == routing["second_v1"].revision


def test_a_fixed_profile_keeps_no_dynamic_fields() -> None:
    fixed = tomllib.loads(
        f"""
[routing.profiles.{_PROFILE_ID}]
classifier = "{_CLASSIFIER}"
classifier_contract = "classification-scores-v1"
policy = "unique-argmax-v1"
[routing.profiles.{_PROFILE_ID}.branches.general]
model = "{_GENERAL}"
max_tokens = 1
[routing.profiles.{_PROFILE_ID}.branches.code]
model = "{_CODE}"
max_tokens = 2
[routing.profiles.{_PROFILE_ID}.branches.math]
model = "{_CODE}"
max_tokens = 3
"""
    )["routing"]["profiles"][_PROFILE_ID]

    profile = _with(fixed).routing[_PROFILE_ID]

    assert (profile.revision_scheme, profile.instructions) == (None, None)
    assert {b.description for b in profile.branches} == {None}


# --- refusals: keys -------------------------------------------------------------------------------


def test_a_branch_without_a_description_is_a_mixed_profile() -> None:
    profile = _profile()
    del profile["branches"]["general"]["description"]

    _refused(profile, "branches.general", "description")


def test_a_dynamic_profile_without_instructions_fails() -> None:
    profile = _profile()
    del profile["instructions"]

    _refused(profile, "instructions")


def test_instructions_without_the_revision_scheme_fail() -> None:
    profile = _profile()
    del profile["revision_scheme"]

    _refused(profile, "instructions")


def test_a_fixed_profile_branch_with_a_description_fails() -> None:
    profile = _profile()
    del profile["revision_scheme"], profile["instructions"]
    profile["branches"] = {
        label: {
            "model": _CODE,
            "max_tokens": 1,
            **({"description": "d"} if label == "math" else {}),
        }
        for label in ("general", "code", "math")
    }

    _refused(profile, "branches.math", "description")


@pytest.mark.parametrize("value", ["router-definition-v2", "", 1])
def test_another_revision_scheme_fails(value: object) -> None:
    profile = _profile()
    profile["revision_scheme"] = value

    _refused(profile, "revision_scheme")


def test_an_extra_key_fails() -> None:
    profile = _profile()
    profile["temperature"] = "0"

    _refused(profile, "temperature")


def test_an_extra_branch_key_fails() -> None:
    profile = _profile()
    profile["branches"]["code"]["temperature"] = 0

    _refused(profile, "branches.code", "temperature")


# --- refusals: values -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "field"),
    [
        pytest.param(lambda p: p.update(instructions=7), "instructions", id="instructions-int"),
        pytest.param(
            lambda p: p.update(instructions=date(2026, 1, 1)), "instructions", id="instr-date"
        ),
        pytest.param(lambda p: p.update(instructions=""), "instructions", id="instructions-empty"),
        pytest.param(
            lambda p: p.update(instructions="i" * 4097), "instructions", id="instructions-4097"
        ),
        pytest.param(
            lambda p: p["branches"]["code"].update(description=True), "description", id="desc-bool"
        ),
        pytest.param(
            lambda p: p["branches"]["code"].update(description=""), "description", id="desc-empty"
        ),
        pytest.param(
            lambda p: p["branches"]["code"].update(description="d" * 1025),
            "description",
            id="desc-1025",
        ),
        pytest.param(
            lambda p: p["branches"]["code"].update(max_tokens=True), "max_tokens", id="max-bool"
        ),
        pytest.param(
            lambda p: p["branches"]["code"].update(model="plain"), "model", id="model-unprefixed"
        ),
        pytest.param(lambda p: p.update(classifier="router"), "classifier", id="classifier"),
        pytest.param(lambda p: p.update(policy="router-policy"), "policy", id="router-policy"),
    ],
)
def test_a_bad_value_fails_naming_its_field(change: Any, field: str) -> None:
    profile = _profile()
    change(profile)

    _refused(profile, field)


@pytest.mark.parametrize(
    "label",
    ["", "x" * 65, "é" * 33, "tab\there", "line\nbreak", "\x7f"],
    ids=["empty", "65-bytes", "66-utf8-bytes", "tab", "newline", "delete"],
)
def test_a_label_outside_c16_fails_without_naming_it(label: str) -> None:
    profile = _profile()
    profile["branches"][label] = {"model": _CODE, "max_tokens": 1, "description": "d"}

    message = _refused(profile, "label")

    assert label not in message or label == ""


def test_no_branch_fails() -> None:
    profile = _profile()
    profile["branches"] = {}

    _refused(profile, "branches")


def test_thirty_three_labels_fail() -> None:
    profile = _profile()
    profile["branches"] = {
        f"l{i}": {"model": _CODE, "max_tokens": 8, "description": "d"} for i in range(33)
    }

    _refused(profile, "branches")


def test_a_normalized_definition_over_64_kib_fails() -> None:
    profile = _profile()
    # WHY a non-ASCII description: C3's canonical JSON escapes it to six bytes per character.
    profile["branches"] = {
        f"l{i}": {"model": _CODE, "max_tokens": 8, "description": "é" * 1024} for i in range(32)
    }

    _refused(profile, "65536")


def test_a_refusal_names_no_value() -> None:
    profile = _profile()
    secret = "do-not-echo-" + "s" * 1100
    profile["branches"]["code"]["description"] = secret
    profile["instructions"] = "keep-private"

    message = _refused(profile, "description")

    assert "do-not-echo" not in message
    assert "keep-private" not in message
