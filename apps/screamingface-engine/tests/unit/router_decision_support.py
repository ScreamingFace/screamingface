"""Shared documents for the C5 Router decision codec tests (Unit 5.2).

Each builder returns a valid document; a test changes one key and states the expectation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from screamingface_engine.router_decision import DECISION_SCHEMA, DRAFT_SCHEMA

REVISION = "sha256:" + "a" * 64
BEST_ONE = {"type": "router-policy", "version": 1, "match": "best", "select": "one"}
EXACT_ONE = {"type": "router-policy", "version": 1, "match": "exact", "select": "one"}
EXACT_ALL = {"type": "router-policy", "version": 1, "match": "exact", "select": "all"}
SCORING = {
    "source": "scoring",
    "model": "acme/router",
    "contract": "classification-scores-v1",
    "scores": [{"label": "code", "score": 0.9}, {"label": "chit", "score": 0.05}],
}


def llm_evidence(labels: list[str], unknown: list[str], parse: str) -> dict[str, Any]:
    return {"source": "llm", "labels": labels, "unknown": unknown, "parse": parse}


def draft_document(**changes: Any) -> dict[str, Any]:
    """A valid selected draft (scoring, best/one); ``changes`` replace keys in order."""
    draft: dict[str, Any] = {
        "schema": DRAFT_SCHEMA,
        "router": "router_1",
        "revision": REVISION,
        "revision_scheme": "router-definition-v1",
        "policy": BEST_ONE,
        "evidence": SCORING,
        "outcome": "selected",
        "reason": "unique_max",
        "selected": [0],
        "unknown_labels": ["chit"],
    }
    draft.update(changes)
    return draft


def failed_draft(phase: str, code: str = "aigateway_http_503", permanent: bool = False) -> Any:
    definition = phase not in ("input", "admit")
    return draft_document(
        revision=REVISION if definition else None,
        revision_scheme="router-definition-v1" if definition else None,
        policy=BEST_ONE if definition else None,
        evidence=None,
        outcome="failed",
        reason=None,
        selected=[],
        unknown_labels=[],
        failure={"phase": phase, "code": code, "permanent": permanent},
    )


def attempts(engine: int = 1, upstream: int | None = 1, billed: bool = True) -> dict[str, Any]:
    return {"engine_attempts": engine, "upstream_attempts": upstream, "possibly_billed": billed}


def record_document(**changes: Any) -> dict[str, Any]:
    """A valid answered record (scoring, best/one); ``changes`` replace keys in order."""
    record: dict[str, Any] = {
        "schema": DECISION_SCHEMA,
        "router": "router_1",
        "revision": REVISION,
        "revision_scheme": "router-definition-v1",
        "policy": BEST_ONE,
        "evidence": SCORING,
        "outcome": "selected",
        "reason": "unique_max",
        "selected": [{"index": 0, "label": "code", "model": "acme/coder"}],
        "unknown_labels": ["chit"],
        "classifier_call": {"binding": "router_1", "cost": None, **attempts()},
        "branches": [
            {
                "role": "candidate",
                "index": 0,
                "label": "code",
                "model": "acme/coder",
                "status": "answered",
                "code": None,
                **attempts(),
            }
        ],
        "quorum": None,
        "synthesis": None,
        "status": "answered",
        "failure": None,
    }
    record.update(changes)
    return record


DROP = object()
"""A `mutate` value that deletes the key instead of replacing it."""


def mutate(path: tuple[str | int, ...], value: object) -> Callable[[dict[str, Any]], None]:
    def apply(document: dict[str, Any]) -> None:
        target: Any = document
        for part in path[:-1]:
            target = target[part]
        if value is DROP:
            del target[path[-1]]
        else:
            target[path[-1]] = value

    return apply
