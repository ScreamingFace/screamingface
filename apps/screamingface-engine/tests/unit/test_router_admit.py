"""Router ADMIT (contracts C2, C4, C8, C11; Unit 5.2).

FEATURE: Router Recipe extension. ADMIT validates the C2 envelope and runs the per-occurrence
metadata preflight (`test_router_preflight`) for every model-bearing role before any provider I/O
of the occurrence. A refusal is data (`{"refused": ...}`) that DECIDE and JOIN carry to the one C5
record; an input failure is carried forward ahead of everything.

INVARIANT: a refusal reads no provider; only metadata GETs precede acceptance. A run-file
admission failure is a run refusal, re-raised unchanged.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from router_support import (
    INPUT_FAILED,
    QUESTION,
    ROUTER,
    SELECTOR_MODEL,
    admit_step,
    choice_definition,
    envelope,
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
)

from screamingface_engine.request_scope import RequestScope
from url4.core.errors import ResolutionError

_CAPTURE = RequestScope(origin="sync", identity_headers={}, capture=True)
_REPLAY = RequestScope(origin="sync", identity_headers={}, replay_frozen_copy="fc_1")
_SEEDED = RequestScope(origin="sync", identity_headers={}, answer_seed=7)


# --- acceptance -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("definition", "reads"),
    [
        pytest.param(
            fixed_definition(),
            [(DETAILS_PATH, CLASSIFIER)] + [(PARAMETERS_PATH, MODELS[label]) for label in LABELS],
            id="fixed-scoring",
        ),
        pytest.param(
            choice_definition(),
            [(DETAILS_PATH, CLASSIFIER)] + [(PARAMETERS_PATH, MODELS[label]) for label in LABELS],
            id="choice-scoring",
        ),
        pytest.param(
            llm_definition(),
            [(PARAMETERS_PATH, SELECTOR_MODEL)]
            + [(PARAMETERS_PATH, MODELS[label]) for label in LABELS],
            id="llm",
        ),
        pytest.param(
            regex_definition(), [(PARAMETERS_PATH, MODELS[label]) for label in LABELS], id="regex"
        ),
        pytest.param(
            fixed_definition(default=model(PUBLIC, max_tokens="32")),
            [(DETAILS_PATH, CLASSIFIER)]
            + [(PARAMETERS_PATH, MODELS[label]) for label in LABELS]
            + [(PARAMETERS_PATH, PUBLIC)],
            id="with-default",
        ),
    ],
)
def test_an_admitted_router_carries_its_question_and_envelope(
    definition: dict[str, Any], reads: list[tuple[str, str]]
) -> None:
    gateway = router_gateway()

    document = json.loads(admit_step(gateway, spec_text(definition)))

    assert document == {"input": QUESTION, "spec": envelope(definition)}
    assert list(document) == ["input", "spec"]
    # INVARIANT: metadata reads only, one per role in role order; no classifier or chat POST.
    assert [(path, name) for method, path, name in gateway.calls()] == reads
    assert {method for method, _, _ in gateway.calls()} == {"GET"}


def test_a_seeded_run_admits_a_scoring_router() -> None:
    # WHY (C8): the scoring classify step sends no seed and does not refuse a seeded run.
    gateway = router_gateway()

    document = json.loads(admit_step(gateway, spec_text(fixed_definition()), scope=_SEEDED))

    assert document["input"] == QUESTION


@pytest.mark.parametrize("scope", [_CAPTURE, _REPLAY], ids=["capture", "replay"])
def test_a_selector_router_runs_in_a_frozen_copy_mode(scope: RequestScope) -> None:
    gateway = router_gateway()

    assert (
        json.loads(admit_step(gateway, spec_text(llm_definition()), scope=scope))["input"]
        == QUESTION
    )


# --- the input carrier takes precedence -----------------------------------------------------------


def test_an_input_failure_is_carried_forward_before_anything_is_read() -> None:
    gateway = router_gateway()

    result = admit_step(gateway, "not a router spec", context=INPUT_FAILED, in_case=False)

    assert json.loads(result) == json.loads(INPUT_FAILED)
    assert gateway.calls() == []


@pytest.mark.parametrize(
    "context",
    [
        pytest.param("", id="empty"),
        pytest.param("not json", id="not-json"),
        pytest.param('["x"]', id="not-an-object"),
        pytest.param('{"input": 1}', id="input-not-text"),
        pytest.param('{"input": "q", "extra": 1}', id="extra-key"),
        pytest.param('{"input": "q", "input": "r"}', id="repeated-key"),
        pytest.param('{"failed": {"code": "x"}}', id="failure-without-permanence"),
        pytest.param('{"failed": {"code": "Not Bounded", "permanent": true}}', id="code-unbounded"),
        pytest.param('{"failed": {"code": "x", "permanent": 1}}', id="permanence-not-boolean"),
        pytest.param('{"refused": {"code": "x", "permanent": true}}', id="a-refusal-is-not-input"),
    ],
)
def test_a_malformed_input_document_is_a_contract_error(context: str) -> None:
    gateway = router_gateway()

    with pytest.raises(ResolutionError) as raised:
        admit_step(gateway, spec_text(fixed_definition()), context=context)

    assert raised.value.code == "benchmark_contract_error"
    assert gateway.calls() == []


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({}, id="none"),
        pytest.param({"binding": "gate_1"}, id="not-a-router-binding"),
        pytest.param({"binding": "router_0"}, id="router-zero"),
        pytest.param({"binding": ROUTER, "max_tokens": "5"}, id="extra-param"),
        pytest.param({"gate": ROUTER}, id="other-name"),
    ],
)
def test_admit_takes_exactly_one_router_binding(params: dict[str, str]) -> None:
    # WHY a contract error and not a record: without a valid binding there is no occurrence to
    # record (C4).
    gateway = router_gateway()

    with pytest.raises(ResolutionError) as raised:
        admit_step(gateway, spec_text(fixed_definition()), params=params)

    assert raised.value.code == "benchmark_contract_error"


# --- refusals before any read ---------------------------------------------------------------------


def test_outside_every_recorder_scope_a_router_is_unsupported() -> None:
    # INVARIANT (C4): a Router never runs model I/O where its record would be lost.
    gateway = router_gateway()

    result = admit_step(gateway, spec_text(fixed_definition()), in_case=False)

    assert json.loads(result) == refusal("router_unsupported")
    assert gateway.calls() == []


def _llm_on(name: str) -> dict[str, Any]:
    definition = llm_definition()
    definition["classifier"]["model"] = model(name, max_tokens="16")
    return definition


def _select_all() -> dict[str, Any]:
    definition = llm_definition(multi=True)
    definition["policy"] = {**definition["policy"], "select": "all"}
    definition["synthesizer"] = {"kind": "vote", "extract": None, "normalize": None}
    definition["quorum"] = "all"
    return definition


@pytest.mark.parametrize(
    "intent",
    [
        pytest.param("not json", id="not-json"),
        pytest.param(
            spec_text(fixed_definition(), revision="sha256:" + "0" * 64), id="stale-revision"
        ),
        pytest.param(spec_text(fixed_definition(), router="router_2"), id="another-occurrence"),
        pytest.param(spec_text(fixed_definition(), extra=1), id="unknown-key"),
        pytest.param(spec_text(fixed_definition(candidates=[])), id="no-candidates"),
    ],
)
def test_an_invalid_definition_is_refused_before_any_read(intent: str) -> None:
    gateway = router_gateway()

    assert json.loads(admit_step(gateway, intent)) == refusal("router_definition_invalid")
    assert gateway.calls() == []


_SUBSET_CALLS = {
    "classifier": "selector_1",
    "candidates": ["model_1", "model_2", "model_3"],
    "default": None,
    "synthesizer": "synthesis_1",
}


@pytest.mark.parametrize(
    "synthesizer",
    [
        {"kind": "vote", "extract": None, "normalize": None},
        {"kind": "model", "model": model(PUBLIC)},
    ],
    ids=["vote", "model"],
)
def test_a_subset_router_is_admitted_and_preflights_every_model_it_names(
    synthesizer: dict[str, Any],
) -> None:
    # WHY (C4): select="all" is admitted and decided here; its panel runs in Unit 6, so
    # ADMIT preflights every Model the occurrence can reach, the Model synthesizer included.
    gateway = router_gateway()
    definition = {**_select_all(), "synthesizer": synthesizer}

    document = json.loads(admit_step(gateway, spec_text(definition, calls=_SUBSET_CALLS)))

    assert set(document) == {"input", "spec"}
    assert document["spec"]["definition"]["policy"]["select"] == "all"
    reads = {(path, name) for method, path, name in gateway.calls() if method == "GET"}
    assert {(PARAMETERS_PATH, MODELS[label]) for label in LABELS} <= reads
    assert ((PARAMETERS_PATH, PUBLIC) in reads) == (synthesizer["kind"] == "model")
    assert posts(gateway) == []


@pytest.mark.parametrize("scope", [_CAPTURE, _REPLAY], ids=["capture", "replay"])
@pytest.mark.parametrize("definition", [fixed_definition(), choice_definition()])
def test_a_scoring_router_in_a_frozen_copy_mode_is_unsupported(
    scope: RequestScope, definition: dict[str, Any]
) -> None:
    # WHY: capture and replay of a Router's classification is C9 (Unit 6); a classification
    # neither stored nor replayed would be a paid, unrecorded call.
    gateway = router_gateway()

    assert json.loads(admit_step(gateway, spec_text(definition), scope=scope)) == refusal(
        "router_unsupported"
    )
    assert gateway.calls() == []


@pytest.mark.parametrize(
    "definition",
    [
        pytest.param(
            fixed_definition(candidates=[{"label": "general", "model": model("acme/elsewhere")}]),
            id="candidate",
        ),
        pytest.param(fixed_definition(default=model("acme/elsewhere")), id="default"),
        pytest.param(_llm_on("acme/elsewhere"), id="llm-classifier"),
    ],
)
def test_a_model_this_world_cannot_execute_is_refused_before_any_read(
    definition: dict[str, Any],
) -> None:
    gateway = router_gateway()

    assert json.loads(admit_step(gateway, spec_text(definition))) == refusal(
        "routing_profile_not_found"
    )
    assert gateway.calls() == []


# --- run-file admission ---------------------------------------------------------------------------


def test_admission_awaits_the_runs_file_check_before_accepting() -> None:
    gateway = router_gateway()
    seen: list[int] = []

    async def files() -> None:
        seen.append(len(gateway.calls()))

    result = admit_step(gateway, spec_text(fixed_definition()), files=files)

    assert json.loads(result)["input"] == QUESTION
    # WHY after the preflight: a refused occurrence needs no file check of its own.
    assert seen == [len(LABELS) + 1]


def test_a_refused_file_check_ends_the_run_unchanged() -> None:
    gateway = router_gateway()
    refusal = ResolutionError("a model cannot read pictures", code="intent_error", permanent=True)

    async def files() -> None:
        raise refusal

    with pytest.raises(ResolutionError) as raised:
        admit_step(gateway, spec_text(fixed_definition()), files=files)

    assert raised.value is refusal


def test_a_refused_occurrence_does_not_wait_for_the_file_check() -> None:
    gateway = router_gateway()
    gateway.script[(DETAILS_PATH, CLASSIFIER)] = httpx.Response(404)
    seen: list[str] = []

    async def files() -> None:
        seen.append("checked")

    admit_step(gateway, spec_text(fixed_definition()), files=files)

    assert seen == []
