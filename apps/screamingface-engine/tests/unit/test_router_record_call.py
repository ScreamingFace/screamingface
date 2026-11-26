"""JOIN publishes the completed Router record on its own operation call (C4/C15, Unit 5.2).

FEATURE: Router Recipe extension. The completed C5 record rides the Case recorder beside the
calls it describes, as E4c publishes a Gate record (`record_gate_call`); the wire projection of
stored results is Unit 6.

INVARIANT: a Router record is not a provider call. The budget fold and the combine accounting
index read `is_provider`, so the record never counts as a priced round trip.
"""

from __future__ import annotations

import json

from screamingface_engine.operation_calls import (
    capture_operation_calls,
    provider_calls_by_fingerprint,
    record_router_call,
)
from screamingface_engine.router_decision import DECISION_SCHEMA, parse_router_decision

_ATTEMPTS = {"engine_attempts": 1, "upstream_attempts": 1, "possibly_billed": True}
_RECORD = {
    "schema": DECISION_SCHEMA,
    "router": "router_1",
    "revision": "sha256:" + "a" * 64,
    "revision_scheme": "router-definition-v1",
    "policy": {"type": "router-policy", "version": 1, "match": "best", "select": "one"},
    "evidence": {
        "source": "scoring",
        "model": "acme/router",
        "contract": "classification-scores-v1",
        "scores": [{"label": "code", "score": 0.9}],
    },
    "outcome": "selected",
    "reason": "unique_max",
    "selected": [{"index": 0, "label": "code", "model": "acme/coder"}],
    "unknown_labels": [],
    # INVARIANT: scores name their call, and an answer its answered branch.
    "classifier_call": {"binding": "router_1", "cost": None, **_ATTEMPTS},
    "branches": [
        {
            "role": "candidate",
            "index": 0,
            "label": "code",
            "model": "acme/coder",
            "status": "answered",
            "code": None,
            **_ATTEMPTS,
        }
    ],
    "quorum": None,
    "synthesis": None,
    "status": "answered",
    "failure": None,
}
_JOIN = "/ensemble/router/v1/join"


def test_the_record_is_published_on_the_join_call() -> None:
    record = parse_router_decision(json.dumps(_RECORD))

    with capture_operation_calls() as calls:
        record_router_call(_JOIN, {"binding": "router_1"}, "the answer", record)

    assert len(calls) == 1
    call = calls[0]
    assert (call.path, call.params, call.output) == (
        _JOIN,
        (("binding", "router_1"),),
        "the answer",
    )
    assert call.router is record
    assert call.accounting is None
    assert call.decision is None


def test_a_router_record_is_not_a_provider_call() -> None:
    record = parse_router_decision(json.dumps(_RECORD))

    with capture_operation_calls() as calls:
        record_router_call(_JOIN, {"binding": "router_1"}, "", record)

    assert calls[0].is_provider is False
    assert provider_calls_by_fingerprint(calls) == {}


def test_outside_every_scope_nothing_is_kept() -> None:
    record = parse_router_decision(json.dumps(_RECORD))

    record_router_call(_JOIN, {"binding": "router_1"}, "", record)

    with capture_operation_calls() as calls:
        pass
    assert calls == []
