"""The strict Router IR ``screamingface.router-spec.v1`` and its revision (contracts C2, C3, C16).

FEATURE: Router Recipe extension, Unit 5.2. The Engine owns validation of the Router definition;
the SDK is only its author. ADMIT refuses a definition that is not exactly one variant of every
record before any I/O of the occurrence.

INVARIANT: the revision is the SHA-256 of the canonical ``{"scheme", "definition"}`` JSON, so the
five golden vectors below are byte-exact and shared with the SDK writer (Unit 6).
INVARIANT: a refusal names the field and the rule, never a value from the definition.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from screamingface_engine.world.router_spec import (
    REVISION_SCHEME,
    ROUTER_SPEC_SCHEMA,
    RouterSpecError,
    definition_revision,
    parse_router_spec,
)

_D = (
    '{"candidates":[{"description":"Programming questions.","label":"code","model":{"model":'
    '"openrouter/openai/gpt-4o-mini","params":{},"prompt":null}},{"description":"Everything '
    'else.","label":"general","model":{"model":"openrouter/meta-llama/llama-3.1-70b-instruct",'
    '"params":{},"prompt":null}}],"classifier":{"contract":"classification-scores-v1","input":'
    '"choice","instructions":"Pick the expert for the question.","model":"laya/router","source":'
    '"scoring"},"default":null,"policy":{"match":"best","select":"one","type":"router-policy",'
    '"version":1},"quorum":null,"synthesizer":null}'
)
_F = (
    '{"candidates":[{"label":"LABEL_0","model":{"model":"openrouter/openai/gpt-4o-mini","params":'
    '{},"prompt":null}},{"label":"LABEL_1","model":{"model":"openrouter/meta-llama/llama-3.1-70b-'
    'instruct","params":{},"prompt":null}}],"classifier":{"contract":"classification-scores-v1",'
    '"input":"text","model":"bert/router","source":"scoring"},"default":null,"policy":{"match":'
    '"best","select":"one","type":"router-policy","version":1},"quorum":null,"synthesizer":null}'
)


def _d() -> dict[str, Any]:
    return json.loads(_D)


def _v2() -> dict[str, Any]:
    value = _d()
    value["candidates"].reverse()
    return value


def _v3() -> dict[str, Any]:
    value = _d()
    value["policy"] = {"type": "unique-argmax-v1"}
    return value


def _v5() -> dict[str, Any]:
    value = _d()
    value["candidates"][0]["model"]["params"] = {
        "logprobs": "true",
        "max_tokens": "256",
        "stop": "END",
        "temperature": "0.2",
    }
    return value


@pytest.mark.parametrize(
    ("definition", "revision"),
    [
        (_d(), "sha256:25d95f844082f8802647d75bbfcc0cb4452528990df72d92a640ead3b4e98930"),
        (_v2(), "sha256:61273d67ca5ac7ad6711072150f20d21f36662690d2cdfcc8a7d81db870477eb"),
        (_v3(), "sha256:4817721933b6f2fe964f8fc6f856fe71fc3a211bc48b0b02ded1bc7188a2b208"),
        (json.loads(_F), "sha256:c75782a7999e73e1ba8bad72ae16b2083daba323c2d385c9ce9e5f1e357985ae"),
        (_v5(), "sha256:71feeae5684881461a5c4b70513cfd1841f471d54666df3d56ffbacb1f5a2a9f"),
    ],
    ids=["V1", "V2", "V3", "V4", "V5"],
)
def test_golden_revision_vectors(definition: dict[str, Any], revision: str) -> None:
    assert definition_revision(definition) == revision


def _envelope(definition: dict[str, Any] | None = None, **calls: Any) -> dict[str, Any]:
    body = _d() if definition is None else definition
    count = len(body["candidates"])
    return {
        "schema": ROUTER_SPEC_SCHEMA,
        "router": "router_1",
        "revision": definition_revision(body),
        "revision_scheme": REVISION_SCHEME,
        "calls": {
            "classifier": None,
            "candidates": [f"model_{index}" for index in range(1, count + 1)],
            "default": None,
            "synthesizer": None,
            **calls,
        },
        "definition": body,
    }


def _text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _refused(value: dict[str, Any] | str) -> RouterSpecError:
    with pytest.raises(RouterSpecError) as caught:
        parse_router_spec(value if isinstance(value, str) else _text(value))
    return caught.value


def _model(name: str) -> dict[str, Any]:
    return {"model": name, "prompt": None, "params": {}}


def _llm_definition(*, select: str = "one", multi: bool = False) -> dict[str, Any]:
    definition = json.loads(_F)
    definition["classifier"] = {
        "source": "llm",
        "model": _model("openrouter/openai/gpt-4o-mini"),
        "labels": ["LABEL_0", "LABEL_1"],
        "prompt": None,
        "multi": multi,
    }
    definition["policy"] = {
        "type": "router-policy",
        "version": 1,
        "match": "exact",
        "select": select,
    }
    if select == "all":
        definition["synthesizer"] = {"kind": "model", "model": _model("openrouter/x/y")}
        definition["quorum"] = "all"
    return definition


def test_accepted_choice_envelope_keeps_calls_and_definition() -> None:
    spec = parse_router_spec(_text(_envelope()))

    assert spec.router == "router_1"
    assert (
        spec.revision == "sha256:25d95f844082f8802647d75bbfcc0cb4452528990df72d92a640ead3b4e98930"
    )
    assert spec.calls.candidates == ("model_1", "model_2")
    assert [candidate.label for candidate in spec.definition.candidates] == ["code", "general"]
    assert spec.definition.model_dump(mode="json", by_alias=True) == _d()


def test_accepted_fixed_and_selector_envelopes() -> None:
    assert parse_router_spec(_text(_envelope(json.loads(_F)))).router == "router_1"
    llm = parse_router_spec(_text(_envelope(_llm_definition(), classifier="selector_1")))
    assert llm.calls.classifier == "selector_1"
    subset = _envelope(
        _llm_definition(select="all", multi=True),
        classifier="selector_1",
        synthesizer="synthesis_1",
    )
    assert parse_router_spec(_text(subset)).definition.quorum == "all"


def test_regex_selector_envelope() -> None:
    definition = json.loads(_F)
    definition["classifier"] = {
        "source": "regex",
        "rules": [
            {"label": "LABEL_0", "pattern": "def |class "},
            {"label": "LABEL_1", "pattern": "why", "ignore_case": True},
        ],
        "multi": False,
    }
    definition["policy"] = {
        "type": "router-policy",
        "version": 1,
        "match": "exact",
        "select": "one",
    }

    assert parse_router_spec(_text(_envelope(definition))).calls.classifier is None


def _mutated(path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    envelope = _envelope()
    target: Any = envelope
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    if path[0] == "definition":
        envelope["revision"] = definition_revision(envelope["definition"])
    return envelope


def _without(path: tuple[Any, ...]) -> dict[str, Any]:
    envelope = _envelope()
    target: Any = envelope
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    if path[0] == "definition":
        envelope["revision"] = definition_revision(envelope["definition"])
    return envelope


@pytest.mark.parametrize(
    "envelope",
    [
        _without(("calls",)),
        _without(("definition", "quorum")),
        _without(("definition", "candidates", 0, "description")),
        _without(("definition", "classifier", "instructions")),
        _mutated(("extra",), 1),
        _mutated(("definition", "extra"), None),
        _mutated(("definition", "candidates", 0, "model", "seed"), "1"),
        _mutated(("schema",), "screamingface.router-spec.v2"),
        _mutated(("revision_scheme",), "router-definition-v2"),
        _mutated(("revision",), "sha256:" + "0" * 64),
        _mutated(("router",), "gate_1"),
        _mutated(("router",), "router_0"),
        _mutated(("definition", "candidates", 0, "model", "params"), {"max_tokens": 256}),
        _mutated(("definition", "candidates", 0, "model", "prompt"), 1),
        _mutated(("definition", "policy"), {"type": "unique-argmax-v1"}),
        _mutated(("definition", "policy", "version"), 2),
        _mutated(("definition", "policy", "version"), True),
        _mutated(("definition", "policy", "select"), "all"),
        _mutated(("definition", "policy", "match"), "exact"),
        _mutated(("definition", "quorum"), 1),
        _mutated(("definition", "candidates", 1, "label"), "code"),
        _mutated(("definition", "candidates", 0, "description"), ""),
        _mutated(("definition", "candidates", 0, "description"), "x" * 1025),
        _mutated(("definition", "classifier", "instructions"), ""),
        _mutated(("definition", "classifier", "instructions"), "x" * 4097),
        _mutated(("definition", "candidates", 0, "label"), "x" * 65),
        _mutated(("definition", "candidates", 0, "label"), "é" * 33),
        _mutated(("definition", "candidates", 0, "label"), ""),
        _mutated(("definition", "candidates", 0, "label"), "co\nde"),
        _mutated(("definition", "candidates"), []),
        _mutated(("definition", "classifier", "contract"), "classification-scores-v2"),
        _mutated(("calls", "classifier"), "selector_1"),
        _mutated(("calls", "candidates"), ["model_1"]),
        _mutated(("calls", "candidates"), ["model_1", "model_1"]),
        _mutated(("calls", "candidates"), ["model_1", "selector_2"]),
        _mutated(("calls", "default"), "model_3"),
        _mutated(("calls", "synthesizer"), "synthesis_1"),
    ],
)
def test_strict_refusals(envelope: dict[str, Any]) -> None:
    error = _refused(envelope)

    assert error.code == "router_definition_invalid"


def test_fixed_scoring_with_an_instructions_key_matches_no_variant() -> None:
    for value in (None, "", "Pick one."):
        definition = json.loads(_F)
        definition["classifier"]["instructions"] = value
        _refused(_envelope(definition))


def test_fixed_scoring_refuses_a_described_candidate() -> None:
    definition = json.loads(_F)
    definition["candidates"][0]["description"] = "Code."
    _refused(_envelope(definition))


def test_choice_scoring_refuses_a_plain_candidate() -> None:
    definition = _d()
    del definition["candidates"][1]["description"]
    _refused(_envelope(definition))


def test_candidate_count_bound() -> None:
    definition = json.loads(_F)
    model = definition["candidates"][0]["model"]
    definition["candidates"] = [{"label": f"L{index}", "model": model} for index in range(33)]
    calls = [f"model_{index}" for index in range(1, 34)]
    _refused(_envelope(definition, candidates=calls))
    definition["candidates"] = definition["candidates"][:32]
    accepted = parse_router_spec(_text(_envelope(definition, candidates=calls[:32])))
    assert len(accepted.definition.candidates) == 32


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_non_finite_numbers_are_refused(constant: str) -> None:
    text = _text(_envelope()).replace('"quorum": null', f'"quorum": {constant}')
    assert constant in text
    _refused(text)


def test_a_repeated_key_is_refused() -> None:
    text = _text(_envelope()).replace('"quorum": null', '"quorum": null, "quorum": null')
    _refused(text)


def test_size_bound_is_64_kib_of_the_serialized_envelope() -> None:
    envelope = _envelope()
    base = len(_text(envelope).encode("utf-8"))
    envelope["definition"]["candidates"][0]["model"]["prompt"] = "x" * (65_536 - base - 2)
    envelope["revision"] = definition_revision(envelope["definition"])
    exact = _text(envelope)
    assert len(exact.encode("utf-8")) <= 65_536
    parse_router_spec(exact)
    envelope["definition"]["candidates"][0]["model"]["prompt"] += "x" * 64
    envelope["revision"] = definition_revision(envelope["definition"])
    _refused(envelope)


def test_not_json_and_not_an_object_are_refused() -> None:
    _refused("{")
    _refused("[]")


def test_selector_rules() -> None:
    # Policy and source compatibility (C1/C2): best needs scoring; exact needs a selector.
    best_llm = _llm_definition()
    best_llm["policy"]["match"] = "best"
    _refused(_envelope(best_llm, classifier="selector_1"))
    # The llm source names its call binding; a scoring or regex source names none.
    _refused(_envelope(_llm_definition()))
    # A selector's declared labels equal the candidate labels.
    unequal = _llm_definition()
    unequal["classifier"]["labels"] = ["LABEL_0", "LABEL_2"]
    _refused(_envelope(unequal, classifier="selector_1"))
    # select="all" needs both synthesizer and quorum; quorum is 1..len(candidates), never a bool.
    subset = _llm_definition(select="all", multi=True)
    for quorum in (0, 3, True, "any"):
        subset["quorum"] = quorum
        _refused(_envelope(subset, classifier="selector_1", synthesizer="synthesis_1"))
    subset["quorum"] = 2
    assert (
        parse_router_spec(
            _text(_envelope(subset, classifier="selector_1", synthesizer="synthesis_1"))
        ).definition.quorum
        == 2
    )
    subset["synthesizer"] = None
    _refused(_envelope(subset, classifier="selector_1"))


def test_default_needs_its_binding() -> None:
    definition = _d()
    definition["default"] = _model("openrouter/x/default")
    _refused(_envelope(definition))
    accepted = parse_router_spec(_text(_envelope(definition, default="model_3")))
    assert accepted.calls.default == "model_3"
    _refused(_envelope(definition, default="model_1"))


def test_a_refusal_names_the_field_never_the_value() -> None:
    secret = "private-label-☃"
    definition = copy.deepcopy(_d())
    definition["candidates"][0]["label"] = secret * 8
    error = _refused(_envelope(definition))

    assert secret not in str(error)
    assert "label" in str(error)
