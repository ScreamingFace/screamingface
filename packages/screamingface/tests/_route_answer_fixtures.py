"""Shared helpers for the `Client.route_answer` tests (not a test module; OME-1823).

A fake Engine is a handler on an `httpx.MockTransport`; `route` runs one routed answer against it
and returns the answer or the error, with every request the Engine received.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

import screamingface as sf

PROFILE = "expert_router_v1"
ENDPOINT = "byom_" + "0" * 32
CLASSIFIER = f"{ENDPOINT}/model_router_v1"
CODE_MODEL = f"{ENDPOINT}/code"
REVISION = "sha256:" + "ab" * 32
SCORES = [
    {"label": "general", "score": 0.07},
    {"label": "code", "score": 0.91},
    {"label": "math", "score": 0.02},
]
RERUN_HINT = "Asking again may run and bill the classifier, and the selected model, again."
SIGNED = "/artifacts/" + "ab" * 32 + "?exp=1&sig=" + "0f" * 32
Handler = Callable[[httpx.Request], httpx.Response]


def routed_result(**changes: Any) -> dict[str, Any]:
    """The Engine's `routed-answer-v1` document for ``PROFILE``, with ``changes`` applied."""

    document: dict[str, Any] = {
        "object": "routed_answer",
        "contract": "routed-answer-v1",
        "profile": PROFILE,
        "revision": REVISION,
        "policy": "unique-argmax-v1",
        "classification": {
            "model": CLASSIFIER,
            "contract": "classification-scores-v1",
            "scores": SCORES,
        },
        "selected": {"label": "code", "model": CODE_MODEL},
        "answer": "Use a list comprehension.",
    }
    document.update(changes)
    return document


def with_classification(**changes: Any) -> dict[str, Any]:
    return routed_result(classification={**routed_result()["classification"], **changes})


def with_selected(**changes: Any) -> dict[str, Any]:
    return routed_result(selected={**routed_result()["selected"], **changes})


def with_scores(*pairs: tuple[Any, Any], label: str = "code") -> dict[str, Any]:
    scores = [{"label": name, "score": score} for name, score in pairs]
    return routed_result(
        classification={**routed_result()["classification"], "scores": scores},
        selected={"label": label, "model": CODE_MODEL},
    )


def engine_client(handler: Handler, requests: list[httpx.Request]) -> sf.Client:
    """A Client whose engine is ``handler``; every request it receives lands in ``requests``."""

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return sf.Client(
        engine_url="http://engine.test",
        scoreboard_url="http://scoreboard.test",
        http_transport=httpx.MockTransport(respond),
        save_results=False,
    )


def ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=routed_result())


def answering(status: int, body: object = None, **headers: str) -> Handler:
    return lambda _request: httpx.Response(status, json=body, headers=headers)


def envelope(code: str, message: str = "refused") -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def route(handler: Handler, text: str = "question") -> tuple[Any, list[httpx.Request]]:
    """The routed answer, or the error it raised, and the requests the Engine received."""

    requests: list[httpx.Request] = []
    with engine_client(handler, requests) as client:
        try:
            return client.route_answer(PROFILE, text), requests
        except sf.ScreamingFaceError as exc:
            return exc, requests


def route_error(handler: Handler) -> sf.ScreamingFaceError:
    """The error one routed answer raises, after exactly one `/route-answer` request."""

    outcome, requests = route(handler)
    assert isinstance(outcome, sf.ScreamingFaceError), outcome
    assert [request.url.path for request in requests] == ["/route-answer"]
    return outcome
