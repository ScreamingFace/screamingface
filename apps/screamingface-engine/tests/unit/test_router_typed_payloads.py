"""A Router occurrence validates its spec once and its draft once (contracts C2, C4, C5; Unit 5.2).

FEATURE: Router Recipe extension. ADMIT validates the C2 envelope and DECIDE validates the C5
draft it writes. Each records its typed result beside the canonical document in the capture
scope's provenance channel; CLASSIFY, OPEN, DECIDE and JOIN read that typed result back once
their context is proven to be the recorded document.

INVARIANT: canonical equality precedes the typed value. A context that is not the recorded
document never reaches the recorded value, so a forged context cannot borrow a proven one.
INVARIANT: no process-wide cache holds a definition; a typed value lives as long as its scope.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from router_block_support import block, run_block, selector_reply
from router_support import (
    choice_definition,
    fixed_definition,
    llm_definition,
    model,
    regex_definition,
    router_gateway,
)
from routing_support import CHAT_PATH, MODELS, PUBLIC

from screamingface_engine.operation_calls import capture_operation_calls
from screamingface_engine.operation_provenance import (
    record_step,
    recorded_step,
    step_payload,
)
from screamingface_engine.router_decision import RouterDraft
from screamingface_engine.world.router_spec import RouterSpec


@pytest.fixture
def validations(monkeypatch: pytest.MonkeyPatch) -> Iterator[Counter[str]]:
    """How many times each typed Router document is validated."""
    counts: Counter[str] = Counter()
    for kind in (RouterSpec, RouterDraft):
        original: Callable[..., Any] = kind.model_validate_json

        def counted(
            text: Any,
            *args: Any,
            _original: Callable[..., Any] = original,
            _name: str = kind.__name__,
        ) -> Any:
            counts[_name] += 1
            return _original(text, *args)

        monkeypatch.setattr(kind, "model_validate_json", staticmethod(counted))
    yield counts


@pytest.mark.parametrize(
    "definition",
    [
        fixed_definition(default=model(PUBLIC)),
        choice_definition(),
        llm_definition(),
        regex_definition(),
    ],
    ids=["fixed-with-default", "choice", "llm", "regex"],
)
def test_one_occurrence_validates_its_spec_once_and_its_draft_once(
    definition: dict[str, Any], validations: Counter[str]
) -> None:
    gateway = router_gateway()
    gateway.script[(CHAT_PATH, MODELS["general"])] = selector_reply("code")

    value, recorded = asyncio.run(run_block(gateway, block(definition)))

    assert isinstance(value, str)
    assert [call.router for call in recorded if call.router is not None] != []
    assert validations == {"RouterSpec": 1, "RouterDraft": 1}


def test_a_recorded_value_is_read_only_for_its_own_canonical_document() -> None:
    payload = object()
    with capture_operation_calls():
        record_step("admit", "router_1", {"b": 1, "a": [1, 2]}, payload)

        recorded = recorded_step("admit", "router_1")
        assert recorded is not None
        assert step_payload("admit", "router_1", recorded) is payload
        assert step_payload("admit", "router_1", '{"a":[1,2],"b":1}') is payload
        assert step_payload("admit", "router_1", '{"a":[1,2],"b":1.0}') is None
        assert step_payload("admit", "router_1", '{"a":[2,1],"b":1}') is None
        assert step_payload("admit", "router_2", '{"a":[1,2],"b":1}') is None
        assert step_payload("decide", "router_1", '{"a":[1,2],"b":1}') is None
    assert step_payload("admit", "router_1", '{"a":[1,2],"b":1}') is None


def test_a_document_recorded_without_a_value_has_none() -> None:
    with capture_operation_calls():
        record_step("decide", "router_1", {"a": 1})

        assert recorded_step("decide", "router_1") == '{"a":1}'
        assert step_payload("decide", "router_1", '{"a":1}') is None
