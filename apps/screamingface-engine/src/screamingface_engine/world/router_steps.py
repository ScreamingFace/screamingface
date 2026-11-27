"""What every Router step reads: its binding, its context and the ADMIT result (C4, Unit 5.2).

FEATURE: Router Recipe extension. A Router occurrence compiles to one url4 block of five Engine
steps on the E4c substrate:

    router_N_admit  = /ensemble/router/v1/admit?binding=router_N&q=($router_N_input)!'<spec>'
    router_N_scores = /ensemble/router/v1/classify($router_N_admit)                    scoring
    router_N_open_s = /ensemble/router/v1/open($router_N_admit)!'classify'             llm, regex
    router_N_decide = /ensemble/router/v1/decide?binding=router_N&q=({admit, evidence})
    router_N_open_K = /ensemble/router/v1/open($router_N_decide)!'c<K>'                per candidate
    router_N_open_d = /ensemble/router/v1/open($router_N_decide)!'default'             with default
    router_N        = /ensemble/router/v1/join?binding=router_N&q=({admit, decision, c<K>?, d?})

ADMIT's result is the one document every later step reads: accepted (``input`` and ``spec``), an
ADMIT refusal, or the input adapter's failure carried forward.

WHY no url4 import: these modules are not on the url4 allowlist
(`tests/unit/test_url4_executor.py`); `gateway_endpoints` registers them on the node.
INVARIANT: an error message names a field or a rule, never a value from the context.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from screamingface_engine.benchmarks.failure_classes import benchmark_contract_error
from screamingface_engine.combine.ports import utf8_exceeds
from screamingface_engine.router_decision import (
    RouterDecisionError,
    RouterDraft,
    parse_router_draft,
)
from screamingface_engine.router_vocabulary import CODE, ROUTER_BINDING, strict_json
from screamingface_engine.world.router_spec import RouterSpec, RouterSpecError, parse_router_spec

ROUTER_PREFIX = "/ensemble/router/v1"
ROUTER_ADMIT_ROUTE = f"{ROUTER_PREFIX}/admit"
ROUTER_CLASSIFY_ROUTE = f"{ROUTER_PREFIX}/classify"
ROUTER_DECIDE_ROUTE = f"{ROUTER_PREFIX}/decide"
ROUTER_OPEN_ROUTE = f"{ROUTER_PREFIX}/open"
ROUTER_JOIN_ROUTE = f"{ROUTER_PREFIX}/join"
MAX_ROUTER_CONTEXT_BYTES = 1024 * 1024
"""Every step context's bound, as an E4c branch step's (`branch.MAX_BRANCH_CONTEXT_BYTES`)."""

NOT_RUN = '{"not_run":true}'
"""The scoring CLASSIFY result beside a non-accepted ADMIT: nothing ran (C4)."""

FAILURE_KEYS = frozenset({"code", "permanent"})
"""The keys of a failure carried as data: its bounded code and its permanence (C4)."""
_CARRIERS: Mapping[str, Literal["input", "admit"]] = {"failed": "input", "refused": "admit"}


@dataclass(frozen=True, slots=True)
class StepCall:
    """One Router step request, without its transport: context, intent and params."""

    context: str
    intent: str
    params: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Accepted:
    """ADMIT accepted the occurrence: the question and the validated envelope."""

    question: str
    admitted: RouterSpec


@dataclass(frozen=True, slots=True)
class Carried:
    """ADMIT did not accept: the input failure (phase ``input``) or its own refusal (``admit``)."""

    phase: Literal["input", "admit"]
    code: str
    permanent: bool


Admission = Accepted | Carried


def step_binding(params: Mapping[str, str], step: str) -> str:
    """The occurrence binding of a step that takes exactly ``binding=router_N``."""
    value = params.get("binding")
    if set(params) != {"binding"} or value is None or ROUTER_BINDING.fullmatch(value) is None:
        raise benchmark_contract_error(f"router {step} takes exactly one param, binding=router_N")
    return value


def no_params(call: StepCall, step: str, *, intent: str = "") -> None:
    """A step that takes no param and exactly ``intent``."""
    if call.params or call.intent != intent:
        raise benchmark_contract_error(f"router {step} takes no param and its fixed intent")


def step_object(text: str, step: str) -> dict[str, object]:
    """A step's context: one strict JSON object of at most 1 MiB."""
    if len(text) > MAX_ROUTER_CONTEXT_BYTES or utf8_exceeds(text, MAX_ROUTER_CONTEXT_BYTES):
        raise benchmark_contract_error(f"router {step} context is larger than 1 MiB")
    try:
        decoded = strict_json(text)
    except ValueError:
        raise benchmark_contract_error(f"router {step} context is not strict JSON") from None
    if not isinstance(decoded, dict):
        raise benchmark_contract_error(f"router {step} context is a JSON object")
    return decoded


def check_keys(
    context: Mapping[str, object], allowed: frozenset[str], required: frozenset[str], step: str
) -> None:
    if not required <= context.keys() <= allowed:
        raise benchmark_contract_error(f"router {step} context has an unknown or missing key")


def read_input(text: str) -> Carried | str:
    """The input adapter's strict document: the question, or its failure (phase ``input``)."""
    document = step_object(text, "admit")
    if set(document) == {"input"} and isinstance(document["input"], str):
        return document["input"]
    if set(document) == {"failed"}:
        return _failure(document["failed"], "input", "admit")
    raise benchmark_contract_error("router admit context is the input or its failure")


def admit_document(value: object, step: str) -> dict[str, object]:
    """ADMIT's result as a later step's context carries it: JSON text of one strict object."""
    if not isinstance(value, str):
        raise benchmark_contract_error(f"router {step} admit is JSON text")
    return step_object(value, step)


def admit_router(document: Mapping[str, object]) -> str | None:
    """The router an accepted ADMIT result names, or None (a carried failure names none)."""
    spec = document.get("spec") if set(document) == {"input", "spec"} else None
    router = spec.get("router") if isinstance(spec, dict) else None
    return router if isinstance(router, str) else None


def read_admit(document: Mapping[str, object], step: str) -> Admission:
    """An ADMIT result no step recorded a typed value for, read and validated from its document.

    WHY only then: a step that proves its context is the recorded ADMIT result reads the value
    ADMIT recorded (`router_provenance.proven_admit`), so this runs for a context it cannot prove
    (to refuse it by its rule) or for a document recorded without its value.
    """
    if set(document) == {"input", "spec"} and isinstance(document["input"], str):
        return Accepted(document["input"], _admitted(document["spec"], step))
    if len(document) == 1:
        key = next(iter(document))
        phase = _CARRIERS.get(key)
        if phase is not None:
            return _failure(document[key], phase, step)
    raise benchmark_contract_error(f"router {step} admit is an ADMIT result")


def read_draft(value: object, step: str) -> RouterDraft:
    """DECIDE's draft, as OPEN and JOIN read it (C5): strict, never a completed record."""
    if not isinstance(value, str) or utf8_exceeds(value, MAX_ROUTER_CONTEXT_BYTES):
        raise benchmark_contract_error(f"router {step} decision is JSON text of at most 1 MiB")
    try:
        return parse_router_draft(value)
    except RouterDecisionError:
        raise benchmark_contract_error(f"router {step} decision is not a valid draft") from None


def failed_document(code: str, permanent: bool) -> str:
    """A failure carried as data: the input adapter's, or the scoring classifier's (C4)."""
    return compact_json({"failed": {"code": code, "permanent": permanent}})


def refused_document(code: str, permanent: bool) -> str:
    """ADMIT's refusal of a definition or of its metadata preflight (C4)."""
    return compact_json({"refused": {"code": code, "permanent": permanent}})


def accepted_document(question: str, envelope: object) -> str:
    return compact_json({"input": question, "spec": envelope})


def read_rows(value: object, owner: str) -> list[str]:
    """An iterate result: ``[]`` (not opened) or its rows as text.

    WHY url4's own codec: url4 writes an iterate result with Python's default JSON encoder and
    embeds a visibly structured row (an error row, a KEYWORDS result, a JSON-shaped reply) as a
    JSON value (url4 spec 5.3.8, `_rows_to_json`). So the array is read as url4 wrote it, and a
    structured row becomes its JSON text again: equal as JSON, not byte for byte.
    """
    if not isinstance(value, str):
        raise benchmark_contract_error(f"router {owner} is JSON text")
    try:
        rows = json.loads(value)
    except (ValueError, RecursionError):
        raise benchmark_contract_error(f"router {owner} is not JSON") from None
    if not isinstance(rows, list) or not all(isinstance(row, str | dict | list) for row in rows):
        raise benchmark_contract_error(f"router {owner} is an iterate result")
    return [row if isinstance(row, str) else json.dumps(row, ensure_ascii=False) for row in rows]


def _failure(value: object, phase: Literal["input", "admit"], step: str) -> Carried:
    if (
        not isinstance(value, dict)
        or set(value) != FAILURE_KEYS
        or not isinstance(value["code"], str)
        or CODE.fullmatch(value["code"]) is None
        or not isinstance(value["permanent"], bool)
    ):
        raise benchmark_contract_error(f"router {step} {phase} failure is a code and permanence")
    return Carried(phase, value["code"], value["permanent"])


def _admitted(envelope: object, step: str) -> RouterSpec:
    """The envelope of an unproven ADMIT result, validated: a later step trusts no context."""
    try:
        return parse_router_spec(compact_json(envelope))
    except RouterSpecError:
        raise benchmark_contract_error(f"router {step} admit holds no valid spec") from None


def compact_json(document: object) -> str:
    """One JSON document as the Router steps exchange it: compact, UTF-8, finite."""
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


__all__ = [
    "FAILURE_KEYS",
    "MAX_ROUTER_CONTEXT_BYTES",
    "NOT_RUN",
    "ROUTER_ADMIT_ROUTE",
    "ROUTER_CLASSIFY_ROUTE",
    "ROUTER_DECIDE_ROUTE",
    "ROUTER_JOIN_ROUTE",
    "ROUTER_OPEN_ROUTE",
    "ROUTER_PREFIX",
    "Accepted",
    "Admission",
    "Carried",
    "StepCall",
    "accepted_document",
    "admit_document",
    "admit_router",
    "check_keys",
    "compact_json",
    "failed_document",
    "no_params",
    "read_admit",
    "read_draft",
    "read_input",
    "read_rows",
    "refused_document",
    "step_binding",
    "step_object",
]
