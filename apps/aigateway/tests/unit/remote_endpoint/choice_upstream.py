"""Structured-choice targets, their config documents and native SystemOne answers (contract C7).

# FEATURE: Router Recipe extension Unit 5.1 — a `systemone-choice-v1` classifier is a target of
# the same endpoint document, answered by the same fake classifier upstream as an HF target.
# WHY the classifier path: the fake upstream routes that one path to its classifier reply, so a
# choice target there needs no second fake.
# WHY a TOML writer of its own: the shared fixture writer renders flat targets only, and a choice
# target carries a `limits` sub-table.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from fastapi.testclient import TestClient

from . import conftest
from .classifier_upstream import ClassifierUpstream, started
from .conftest import Harness
from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    ALIAS,
    CLASSIFIER_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    ORIGIN_A,
    ORIGIN_B,
    _value,
    chat_target,
    classifier_target,
    document,
    endpoint,
)

CHOICE_ALIAS = "router_v1"
CHOICE_CONTRACT = "systemone-choice-v1"
INPUT_CONTRACT = "classification-choice-input-v1"
LIMITS: dict[str, int] = {
    "max_labels": 8,
    "max_label_bytes": 16,
    "max_text_chars": 200,
    "max_options": 6,
    "max_description_chars": 64,
    "max_instructions_chars": 80,
}
INSTRUCTIONS = "Pick the model family that should answer."
# Not in label order on purpose, and `LABEL_0` must reach the upstream exactly as written.
OPTIONS = [
    {"label": "general", "description": "Everyday questions"},
    {"label": "LABEL_0", "description": "Source code and stack traces"},
    {"label": "math", "description": "Arithmetic and word problems"},
]


def choice_target(**overrides: Any) -> dict[str, Any]:
    target: dict[str, Any] = {
        "alias": CHOICE_ALIAS,
        "task": "text-classification",
        "contract": CHOICE_CONTRACT,
        "request_path": CLASSIFIER_PATH,
        "limits": dict(LIMITS),
    }
    target.update(overrides)
    return target


def choice_document(
    *,
    a_target: dict[str, Any] | None = None,
    b_target: dict[str, Any] | None = None,
    with_hf: bool = False,
) -> dict[str, Any]:
    """Both endpoints granted as in the Unit 0 matrix, each with a chat and a choice target."""

    def targets(choice: dict[str, Any] | None) -> list[dict[str, Any]]:
        listed = [chat_target(), choice or choice_target()]
        if with_hf:
            listed.append(classifier_target(request_path="/models/hf"))
        return listed

    return document(
        endpoint(
            ENDPOINT_A,
            origin=ORIGIN_A,
            accounts=(ACCOUNT_A, ACCOUNT_B),
            targets=targets(a_target),
            validation_target=ALIAS,
        ),
        endpoint(
            ENDPOINT_B,
            origin=ORIGIN_B,
            accounts=(ACCOUNT_A,),
            targets=targets(b_target),
            validation_target=ALIAS,
        ),
    )


def to_toml(doc: dict[str, Any]) -> str:
    """The shared fixture writer's output, plus each target's `limits` sub-table."""
    lines = [f"{key} = {_value(value)}" for key, value in doc.items() if key != "endpoints"]
    for table in doc.get("endpoints", []):
        lines += ["", "[[endpoints]]"]
        lines += [f"{key} = {_value(value)}" for key, value in table.items() if key != "targets"]
        for target in table.get("targets", []):
            lines += ["", "[[endpoints.targets]]"]
            lines += [f"{key} = {_value(v)}" for key, v in target.items() if key != "limits"]
            if "limits" in target:
                lines += ["", "[endpoints.targets.limits]"]
                lines += [f"{key} = {_value(v)}" for key, v in target["limits"].items()]
    return "\n".join(lines) + "\n"


@contextmanager
def started_choice(
    byom: Harness, doc: dict[str, Any]
) -> Iterator[tuple[TestClient, ClassifierUpstream]]:
    byom.monkeypatch.setattr(conftest, "to_toml", to_toml)
    with started(byom, doc) as (client, upstream):
        yield client, upstream


def choice_input(
    text: str = "What is 17 times 23?",
    *,
    instructions: str = INSTRUCTIONS,
    options: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "contract": INPUT_CONTRACT,
        "text": text,
        "instructions": instructions,
        "options": OPTIONS if options is None else options,
        **extra,
    }


def choice_body(provider: str, value: Any, alias: str = CHOICE_ALIAS) -> dict[str, Any]:
    return {"model": f"{provider}/{alias}", "input": value}


def native_answer(probabilities: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """A SystemOne answer to the one `choice` question, as Laya and Jev both write it."""
    best = max(probabilities, key=lambda label: probabilities[label]) if probabilities else None
    answer = {"type": "choice", "choice": best, "probabilities": probabilities, "confidence": 0.9}
    return {"model": "upstream-checkpoint", "answers": {"choice": answer}, **fields}


def answering(body: dict[str, Any]):
    """An upstream reply that answers every classification with ``body``."""

    def reply(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=body)

    return reply
