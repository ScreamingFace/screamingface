"""Shared fixtures for the Router runtime tests (contracts C2, C4, C5, Unit 5.2).

Each envelope is a valid `router-spec.v1` whose revision recomputes from its definition (C3), over
the models `routing_support` declares, so a test changes one field and states the expectation.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Literal

from routing_support import (
    CALLER,
    CLASSIFIER,
    DETAILS_PATH,
    LABELS,
    MODELS,
    PUBLIC,
    Gateway,
    classifier_document,
)

from screamingface_engine.operation_calls import (
    AttemptFact,
    OperationCall,
    capture_operation_calls,
    record_attempt_fact,
)
from screamingface_engine.operation_provenance import (
    CallOutcome,
    Step,
    record_call_outcome,
    record_step,
)
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.classifier_limits import LIMITS_CONTRACT
from screamingface_engine.world.router_admit import RouterPorts, admit, canonical_models
from screamingface_engine.world.router_spec import definition_revision
from screamingface_engine.world.router_steps import ROUTER_CLASSIFY_ROUTE, StepCall

ROUTER = "router_1"
SCORES = "classification-scores-v1"
SELECTOR_MODEL = MODELS["general"]
POLICY_BEST = {"type": "router-policy", "version": 1, "match": "best", "select": "one"}
POLICY_EXACT = {"type": "router-policy", "version": 1, "match": "exact", "select": "one"}
QUESTION = 'What is 2 + 2? It\'s "four".'


def model(name: str, **params: str) -> dict[str, Any]:
    return {"model": name, "prompt": None, "params": dict(params)}


def candidates(*, described: bool = False) -> list[dict[str, Any]]:
    """One candidate per `routing_support` label, in its label order."""
    rows: list[dict[str, Any]] = []
    for label in LABELS:
        row: dict[str, Any] = {"label": label, "model": model(MODELS[label], max_tokens="64")}
        if described:
            row["description"] = f"Questions about {label}."
        rows.append(row)
    return rows


def fixed_definition(**changes: Any) -> dict[str, Any]:
    classifier = {"source": "scoring", "model": CLASSIFIER, "contract": SCORES, "input": "text"}
    definition: dict[str, Any] = {
        "classifier": classifier,
        "policy": POLICY_BEST,
        "candidates": candidates(),
        "default": None,
        "synthesizer": None,
        "quorum": None,
    }
    definition.update(changes)
    return definition


def choice_definition(**changes: Any) -> dict[str, Any]:
    classifier = {
        "source": "scoring",
        "model": CLASSIFIER,
        "contract": SCORES,
        "input": "choice",
        "instructions": "Pick the expert for the question.",
    }
    return fixed_definition(classifier=classifier, candidates=candidates(described=True), **changes)


def llm_definition(*, multi: bool = False, **changes: Any) -> dict[str, Any]:
    classifier = {
        "source": "llm",
        "model": model(SELECTOR_MODEL, max_tokens="16"),
        "labels": list(LABELS),
        "prompt": None,
        "multi": multi,
    }
    return fixed_definition(classifier=classifier, policy=POLICY_EXACT, **changes)


def subset_definition(**changes: Any) -> dict[str, Any]:
    """A ``select="all"`` Router: a multi-label llm selector and a vote over every selection."""
    definition = llm_definition(multi=True, quorum="all", **changes)
    definition["policy"] = {**definition["policy"], "select": "all"}
    definition["synthesizer"] = {"kind": "vote", "extract": None, "normalize": None}
    return definition


def regex_definition(**changes: Any) -> dict[str, Any]:
    rules = [{"label": label, "pattern": label, "ignore_case": True} for label in LABELS]
    classifier = {"source": "regex", "rules": rules, "multi": False}
    return fixed_definition(classifier=classifier, policy=POLICY_EXACT, **changes)


def calls(definition: dict[str, Any]) -> dict[str, Any]:
    """The compiler's `Calls` for ``definition``: model_1.. per candidate, then the default."""
    count = len(definition["candidates"])
    return {
        "classifier": "selector_1" if definition["classifier"]["source"] == "llm" else None,
        "candidates": [f"model_{index + 1}" for index in range(count)],
        "default": None if definition["default"] is None else f"model_{count + 1}",
        "synthesizer": None if definition["synthesizer"] is None else "synthesis_1",
    }


def envelope(definition: dict[str, Any], *, router: str = ROUTER, **changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": "screamingface.router-spec.v1",
        "router": router,
        "revision": definition_revision(definition),
        "revision_scheme": "router-definition-v1",
        "calls": calls(definition),
        "definition": definition,
    }
    document.update(changes)
    return document


def text(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


def accepted(definition: dict[str, Any], question: str = QUESTION) -> str:
    """The ADMIT document of an accepted ``definition``."""
    return text({"input": question, "spec": envelope(definition)})


def scores(**values: float) -> str:
    """A scoring CLASSIFY answer from `routing_support`'s classifier, in argument order."""
    return text(
        {
            "object": "classification",
            "model": CLASSIFIER,
            "contract": SCORES,
            "scores": [{"label": label, "score": score} for label, score in values.items()],
        }
    )


def rows(*values: str) -> str:
    """An iterate result as url4 packs it (url4 spec §5.3.8, `_rows_to_json`).

    WHY not a list of strings: url4 embeds a visibly structured row (an error row, a KEYWORDS
    result, a JSON-shaped reply) as a JSON value, with Python's default JSON encoder.
    """
    return json.dumps([_url4_row(value) if value[:1] in "[{" else value for value in values])


def _url4_row(value: str) -> object:
    try:
        return json.loads(value)
    except ValueError:
        return value


def error_row(code: str | None = "aigateway_http_503", *, retryable: bool = False) -> str:
    """A url4 ``collect`` error row (`url4.dag.nodes._shared`), with a message nothing keeps."""
    error: dict[str, Any] = {"kind": "resolution", "message": "an upstream said no"}
    if code is not None:
        error["code"] = code
    error["retryable"] = retryable
    return text({"error": error})


REFUSED = text({"refused": {"code": "router_definition_invalid", "permanent": True}})
INPUT_FAILED = text({"failed": {"code": "router_input_missing", "permanent": True}})


def fact(
    binding: str, status: Literal["answered", "failed"] = "answered", code: str | None = None
) -> AttemptFact:
    return AttemptFact(
        binding=binding,
        status=status,
        code=code,
        engine_attempts=1,
        upstream_attempts=1,
        possibly_billed=True,
    )


Record = AttemptFact | CallOutcome
"""What a bound call leaves in its Case: its attempt fact (C8) and its outcome."""


@contextmanager
def case(*records: Record) -> Iterator[list[OperationCall]]:
    """A Case recorder scope holding ``records``, as a benchmark Case opens one."""
    with capture_operation_calls() as recorded:
        for item in records:
            if isinstance(item, AttemptFact):
                record_attempt_fact(item)
            else:
                record_call_outcome(item)
        yield recorded


def step(name: Step, document: str, router: str = ROUTER) -> str:
    """Record ``document`` as the open Case's ``name`` result for ``router``, as the step does."""
    record_step(name, router, json.loads(document))
    return document


def answered(binding: str, model_id: str, reply: str) -> tuple[Record, Record]:
    """A bound Model call that answered ``reply``: its outcome and its attempt fact."""
    return CallOutcome(binding, "/" + model_id, "answered", reply), fact(binding)


def failed_call(
    binding: str,
    model_id: str,
    code: str | None = "aigateway_http_503",
    *,
    permanent: bool = True,
    fact_code: str | None = None,
    attempted: bool = True,
) -> tuple[Record, ...]:
    """A bound Model call that raised ``code``: its outcome and, when it sent one, its fact.

    ``fact_code`` is the fact's origin code (a Gateway refusal's `aigateway_http_<status>`),
    ``code`` by default.
    """
    outcome = CallOutcome(binding, "/" + model_id, "failed", code=code, permanent=permanent)
    if not attempted:
        return (outcome,)
    return outcome, fact(binding, "failed", code if fact_code is None else fact_code)


def classified(evidence: str, router: str = ROUTER) -> tuple[Record, ...]:
    """The scoring CLASSIFY call behind ``evidence``: an answer has its attempt fact, a failure
    document (a classifier that refused before any attempt) none."""
    if evidence.startswith('{"failed"'):
        return (CallOutcome(router, ROUTER_CLASSIFY_ROUTE, "failed", evidence),)
    return CallOutcome(router, ROUTER_CLASSIFY_ROUTE, "answered", evidence), fact(router)


ROUTES = frozenset("/" + name for name in (*MODELS.values(), PUBLIC))
"""Every chat route the `routing_support` world declares: the Router's executable Models."""
CHOICE_LIMITS = {
    "contract": LIMITS_CONTRACT,
    "max_labels": 8,
    "max_label_bytes": 64,
    "max_text_chars": 4096,
    "max_options": 8,
    "max_description_chars": 256,
    "max_instructions_chars": 256,
}


def classifier_details(*contracts: str, limits: object = None) -> Any:
    """A `/v1/classifiers/details` answer that takes ``contracts`` under ``limits``."""
    document = classifier_document(input_contracts=list(contracts or ("text",)), limits=limits)
    return lambda _request: document


def router_gateway(**changes: Any) -> Gateway:
    """A Gateway whose classifier takes text and choice inputs within `CHOICE_LIMITS`."""
    gateway = Gateway(**changes)
    gateway.script[(DETAILS_PATH, CLASSIFIER)] = classifier_details(
        "text", "choice", limits=CHOICE_LIMITS
    )
    return gateway


def scoped[T](scenario: Callable[[], Awaitable[T]], *, scope: RequestScope | None = None) -> T:
    """Run ``scenario`` under a caller's request scope."""

    async def bound() -> T:
        with request_scope(scope or RequestScope(origin="sync", identity_headers=CALLER)):
            return await scenario()

    return asyncio.run(bound())


# --- ADMIT, as the ADMIT, preflight and CLASSIFY tests drive it ----------------------------------

BINDING: Mapping[str, str] = {"binding": ROUTER}


class ClassifierPort:
    """A fake classification port: records each call, answers ``reply`` or raises it."""

    def __init__(self, reply: str | BaseException = '{"scores":[]}') -> None:
        self.reply = reply
        self.calls: list[tuple[str, object, str]] = []

    async def __call__(self, model: str, value: str | Mapping[str, object], binding: str) -> str:
        self.calls.append((model, value, binding))
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


async def _no_files() -> None:
    return None


def admit_step(
    gateway: Gateway,
    intent: str,
    *,
    context: str | None = None,
    params: Mapping[str, str] = BINDING,
    routes: frozenset[str] = ROUTES,
    files: Callable[[], Awaitable[None]] = _no_files,
    in_case: bool = True,
    scope: RequestScope | None = None,
) -> str:
    """ADMIT over the adapter's ``{"input": QUESTION}`` (or ``context``) in a Case."""

    async def scenario() -> str:
        async with gateway.client() as client:
            models = canonical_models(routes)
            ports = RouterPorts(client=client, models=models, classify=ClassifierPort())
            step = context if context is not None else text({"input": QUESTION})
            call = StepCall(context=step, intent=intent, params=params)
            if not in_case:
                return await admit(ports, call, files)
            with case():
                return await admit(ports, call, files)

    return scoped(scenario, scope=scope)


def spec_text(definition: dict[str, Any], **changes: Any) -> str:
    return text(envelope(definition, **changes))


def refusal(code: str, *, permanent: bool = True) -> dict[str, Any]:
    return {"refused": {"code": code, "permanent": permanent}}


def posts(gateway: Gateway) -> list[tuple[str, str, str]]:
    return [call for call in gateway.calls() if call[0] != "GET"]
