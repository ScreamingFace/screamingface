"""Router OPEN (contracts C4, C5; Unit 5.2).

FEATURE: Router Recipe extension. OPEN gates each body on ADMIT's result (``classify``) or on
DECIDE's draft (``c<K>``, ``default``), so an unselected body makes zero calls.

INVARIANT (C4): OPEN reads only the ADMIT result and draft this occurrence recorded; ``panel``
never opens, and a selected subset (``select="all"``) is refused, its panel being Unit 6's.
"""

from __future__ import annotations

from typing import Any

import pytest
from router_support import (
    INPUT_FAILED,
    REFUSED,
    ROUTER,
    accepted,
    case,
    classified,
    fixed_definition,
    llm_definition,
    model,
    regex_definition,
    scores,
    step,
    text,
)
from routing_support import PUBLIC

from screamingface_engine.world.router_decide import decide, open_branch
from screamingface_engine.world.router_steps import StepCall
from url4.core.errors import ResolutionError

_BINDING = {"binding": ROUTER}


def _open(context: str, intent: str, params: dict[str, str] | None = None) -> str:
    return open_branch(StepCall(context=context, intent=intent, params=params or {}))


def _opened(definition: dict[str, Any], evidence: str, *slots: str) -> list[str]:
    """OPEN of each slot in the Case whose ADMIT, classification and DECIDE produced the draft."""
    admit = accepted(definition)
    with case(*classified(evidence)):
        step("admit", admit)
        draft = decide(StepCall(text({"admit": admit, "evidence": evidence}), "", _BINDING))
        return [_open(draft, slot) for slot in slots or ("c0", "c1", "c2", "default")]


@pytest.mark.parametrize("definition", [llm_definition(), regex_definition()])
def test_an_accepted_selector_opens_its_classifier(definition: dict[str, Any]) -> None:
    with case():
        assert _open(step("admit", accepted(definition)), "classify") == "[{}]"


@pytest.mark.parametrize("admit", [INPUT_FAILED, REFUSED])
def test_a_refused_occurrence_opens_no_classifier(admit: str) -> None:
    assert _open(admit, "classify") == "[]"


def test_only_the_selected_candidate_opens() -> None:
    opened = _opened(
        fixed_definition(default=model(PUBLIC)), scores(general=0.0, code=1.0, math=0.0)
    )

    assert opened == ["[]", "[{}]", "[]", "[]"]


def test_only_the_default_opens_when_the_policy_chose_it() -> None:
    opened = _opened(
        fixed_definition(default=model(PUBLIC)), scores(general=1.0, code=1.0, math=0.0)
    )

    assert opened == ["[]", "[]", "[]", "[{}]"]


@pytest.mark.parametrize(
    "evidence",
    [
        pytest.param(scores(general=1.0, code=1.0, math=0.0), id="no-selection"),
        pytest.param(text({"failed": {"code": "timeout", "permanent": False}}), id="failed"),
    ],
)
def test_nothing_opens_without_a_selection_or_default(evidence: str) -> None:
    assert set(_opened(fixed_definition(), evidence)) == {"[]"}


@pytest.mark.parametrize(
    ("context", "intent", "params"),
    [
        pytest.param(accepted(fixed_definition()), "classify", {}, id="classify-a-scoring-source"),
        pytest.param(REFUSED, "c01", {}, id="leading-zero"),
        pytest.param(REFUSED, "c-1", {}, id="negative"),
        pytest.param(REFUSED, "C0", {}, id="upper-case"),
        pytest.param(REFUSED, "", {}, id="no-intent"),
        pytest.param(accepted(llm_definition()), "classify", _BINDING, id="a-param"),
        pytest.param(REFUSED, "c0", {}, id="an-admit-result-is-not-a-draft"),
        pytest.param("{}", "default", {}, id="not-a-draft"),
    ],
)
def test_a_malformed_open_is_a_contract_error(
    context: str, intent: str, params: dict[str, str]
) -> None:
    with pytest.raises(ResolutionError) as raised, case():
        if context.startswith('{"input"'):
            step("admit", context)
        _open(context, intent, params)

    assert raised.value.code == "benchmark_contract_error"
