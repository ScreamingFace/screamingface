"""A replayed Router step on the real url4 executor (contracts C4, C5, C8; Unit 5.2).

FEATURE: Router Recipe extension. A hand-written url4 expression can name one Router step twice
for one binding: side by side, which url4 runs concurrently, or after the step already ran in the
same Case. Each step claims its step and binding in the Case before its first await, read,
provider call or publication, so a duplicate is an Engine contract error that reaches no
preflight, no classification call and no C5 record.

STORY: as an Engine operator, a replayed Router step can neither pay twice nor publish twice.
"""

from __future__ import annotations

import asyncio
from typing import Any

from router_block_support import QUESTION, SCOPE, block, world
from router_support import ROUTER, accepted, fixed_definition, router_gateway
from routing_support import CLASSIFICATIONS_PATH, CLASSIFIER, DETAILS_PATH, Gateway

from screamingface_engine.benchmarks.picture_admission import run_expression_scope
from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from screamingface_engine.request_scope import request_scope
from screamingface_engine.world.router_steps import NOT_RUN
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run

_ADMIT = "router_1_admit:0.0:/ensemble/router/v1/admit?binding=router_1"
_SCORES = "router_1_scores:0.0:/ensemble/router/v1/classify($router_1_admit)!''"
_JOIN = "router_1:0.0:/ensemble/router/v1/join?binding=router_1"
_DECIDE = "router_1_decide:0.0:/ensemble/router/v1/decide?binding=router_1"
_SETTLE = 10.0
"""Seconds a run may take; a step held by the Gateway would otherwise wait forever."""


async def _runs(gateway: Gateway, *sources: str) -> tuple[list[object], list[OperationCall]]:
    """Each source in turn, in ONE Case: its values (or url4 errors) and the Case's calls."""
    values: list[object] = []
    async with world(gateway) as node:
        with request_scope(SCOPE), capture_operation_calls() as recorded:
            for source in sources:
                with run_expression_scope(source):
                    try:
                        values.append(await asyncio.wait_for(url4_run(source, io=node), _SETTLE))
                    except ResolutionError as exc:
                        values.append(exc)
    return values, list(recorded)


def _run(gateway: Gateway, *sources: str) -> tuple[list[object], list[OperationCall]]:
    return asyncio.run(_runs(gateway, *sources))


def _twice(source: str, step: str, name: str) -> str:
    """``source`` with a second node running ``step`` (its ``name:0.0:...`` text) under ``name``,
    which the block's output also reads, so url4 runs both."""
    node, _, rest = step.partition(":0.0:")
    duplicate = source.replace(step, f"{step}, {name}:0.0:{rest}", 1)
    assert duplicate != source and node != name
    return duplicate.removesuffix("!'$router_1'") + f"!'$router_1${name}'"


def _block_text(source: str, prefix: str) -> str:
    """The one step text in ``source`` that starts with ``prefix``, through its own ``!''``."""
    start = source.index(prefix)
    return source[start : source.index("!''", start) + 3]


def _contract_error(value: object) -> bool:
    return isinstance(value, ResolutionError) and value.code == "benchmark_contract_error"


def _records(recorded: list[OperationCall]) -> list[dict[str, Any]]:
    return [call.router.document() for call in recorded if call.router is not None]


def _details_reads(gateway: Gateway) -> int:
    return gateway.calls().count(("GET", DETAILS_PATH, CLASSIFIER))


def _literal(name: str, document: str) -> str:
    assert "'" not in document
    return f"{name}:0.0:'{document}'"


# --- ADMIT ----------------------------------------------------------------------------------------


def test_a_second_admit_beside_one_in_its_preflight_reads_nothing() -> None:
    # INVARIANT: the claim precedes ADMIT's first await, so while one ADMIT waits on its
    # preflight a second one for the same binding refuses without a read of its own.
    gateway = router_gateway(hold=DETAILS_PATH)
    source = block(fixed_definition())
    admit = source[source.index(_ADMIT) : source.index(", router_1_scores")]

    (value,), recorded = _run(gateway, _twice(source, admit, "router_1_admit_b"))

    assert _contract_error(value)
    assert _details_reads(gateway) == 1 and gateway.cancelled.is_set()
    assert gateway.posts(CLASSIFICATIONS_PATH) == []
    assert _records(recorded) == []


def test_an_admit_after_its_occurrence_ran_reads_nothing() -> None:
    gateway = router_gateway()
    first = block(fixed_definition())
    again = first[: first.index(", router_1_scores")] + ")!'$router_1_admit'"

    (answer, value), recorded = _run(gateway, first, again)

    assert isinstance(answer, str) and _contract_error(value)
    assert _details_reads(gateway) == 1
    assert len(_records(recorded)) == 1


# --- CLASSIFY -------------------------------------------------------------------------------------


def test_a_second_classify_beside_one_in_flight_makes_no_call() -> None:
    # INVARIANT: CLASSIFY claims once its ADMIT result is proven accepted and before the port
    # call, so a parallel duplicate never reaches the paid classification endpoint.
    gateway = router_gateway(hold=CLASSIFICATIONS_PATH)

    (value,), recorded = _run(gateway, _twice(block(fixed_definition()), _SCORES, "scores_b"))

    assert _contract_error(value)
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == 1 and gateway.cancelled.is_set()
    assert _records(recorded) == []
    provider = [call for call in recorded if call.is_provider and call.path.endswith("classify")]
    assert len(provider) <= 1


def test_side_by_side_classifications_make_one_call() -> None:
    gateway = router_gateway()

    (value,), recorded = _run(gateway, _twice(block(fixed_definition()), _SCORES, "scores_b"))

    assert _contract_error(value)
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == 1
    assert _records(recorded) == []


def test_a_classify_after_its_occurrence_ran_makes_no_call() -> None:
    gateway = router_gateway()
    replay = (
        f"({_literal('admit', accepted(fixed_definition(), QUESTION))}, "
        "scores:0.0:/ensemble/router/v1/classify($admit)!'')!'$scores'"
    )

    (answer, value), recorded = _run(gateway, block(fixed_definition()), replay)

    assert isinstance(answer, str) and _contract_error(value)
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == 1
    classify = [
        call for call in recorded if ("binding", ROUTER) in call.params and call.is_provider
    ]
    assert len(classify) == 1
    assert len(_records(recorded)) == 1


# --- DECIDE and JOIN ------------------------------------------------------------------------------


def test_a_second_decide_drafts_nothing_and_nothing_is_published() -> None:
    source = block(fixed_definition())

    (value,), recorded = _run(
        router_gateway(), _twice(source, _block_text(source, _DECIDE), "decide_b")
    )

    assert _contract_error(value)
    assert _records(recorded) == []


def test_a_second_join_publishes_no_second_record() -> None:
    # INVARIANT (C4, C5): JOIN is the single publisher; it claims before reading, so a second
    # JOIN for the binding publishes nothing, whichever of the two ran first.
    source = block(fixed_definition())

    (value,), recorded = _run(
        router_gateway(), _twice(source, _block_text(source, _JOIN), "join_b")
    )

    assert _contract_error(value)
    assert len(_records(recorded)) == 1


# --- a classifier that never ran ------------------------------------------------------------------


def test_not_run_beside_an_accepted_admit_publishes_one_decide_failure_with_no_call() -> None:
    # WHY (C4, C5): `{"not_run": true}` beside an accepted ADMIT is `router_evidence_invalid` at
    # decide, and the classifier did not run, so the one record names no classifier call.
    gateway = router_gateway()
    source = block(fixed_definition()).replace(_SCORES, _literal("router_1_scores", NOT_RUN))

    (value,), recorded = _run(gateway, source)

    assert isinstance(value, ResolutionError) and value.code == "router_evidence_invalid"
    (record,) = _records(recorded)
    assert record["failure"] == {"phase": "decide", "code": "router_evidence_invalid"}
    assert (record["evidence"], record["classifier_call"], record["branches"]) == (None, None, [])
    assert gateway.posts(CLASSIFICATIONS_PATH) == []
