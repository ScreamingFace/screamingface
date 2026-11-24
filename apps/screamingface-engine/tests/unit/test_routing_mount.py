"""`GET /route-answer?q=` through the real App, the in-process runner and a fake Gateway.

FEATURE: BYOM routing pilot (spec 3.2, 3.5). The route is a direct mount like `/classify`: the
App refuses what it can before any run (the 8 KiB bound, an escape that is not UTF-8, the
frozen-copy headers), and every routing code answers its own status.

WHY substitutes: this proves the Engine half on a fake Gateway, with `InProcessJobRunner` in place
of the queue and a worker. The hosted check through Linux, NATS and JetStream, a real worker and
the real Gateway stays pending; nothing here claims it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from routing_support import (
    CHAT_PATH,
    CLASSIFICATIONS_PATH,
    CLASSIFIER,
    DETAILS_PATH,
    ENDPOINT,
    MODELS,
    PARAMETERS_PATH,
    PROFILE,
    Gateway,
    call,
    classifier_document,
    context,
    engine,
    max_tokens_rule,
    parameters_document,
    query,
    revision,
    write_world,
)

from screamingface_engine.rest.mounts import RUN_HEADER

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]

_LIMIT = 8192 - len("/route-answer?")


def _error(resp: httpx.Response) -> dict[str, Any]:
    return resp.json()["error"]


def _tie(_: httpx.Request) -> dict[str, Any]:
    return {
        "object": "classification",
        "model": CLASSIFIER,
        "contract": "classification-scores-v1",
        "scores": [
            {"label": "general", "score": 0.4},
            {"label": "code", "score": 0.4},
            {"label": "math", "score": 0.2},
        ],
    }


def _extra(_: httpx.Request) -> dict[str, Any]:
    return {
        "object": "classification",
        "model": CLASSIFIER,
        "contract": "classification-scores-v1",
        "scores": [{"label": "legal", "score": 1.0}],
    }


_JSON = httpx.Response


@pytest.mark.parametrize(
    ("script", "raw_context", "status", "code"),
    [
        pytest.param({}, context(profile="missing_v1"), 404, "routing_profile_not_found", id="404"),
        pytest.param(
            {(PARAMETERS_PATH, MODELS["math"]): _JSON(409, json={"detail": {"code": "pending"}})},
            context(),
            409,
            "routing_connection_missing",
            id="409",
        ),
        pytest.param(
            {(DETAILS_PATH, CLASSIFIER): _JSON(503, json={"detail": "down"})},
            context(),
            502,
            "routing_preflight_unavailable",
            id="unavailable",
        ),
        pytest.param(
            {(DETAILS_PATH, CLASSIFIER): _JSON(403, json={"detail": "no"})},
            context(),
            502,
            "routing_preflight_failed",
            id="failed",
        ),
        pytest.param(
            {
                (PARAMETERS_PATH, MODELS["code"]): _JSON(
                    200,
                    json=parameters_document(
                        MODELS["code"], rule=max_tokens_rule(gateway={"status": "disabled"})
                    ),
                )
            },
            context(),
            502,
            "routing_profile_mismatch",
            id="mismatch",
        ),
        pytest.param(
            {(CLASSIFICATIONS_PATH, CLASSIFIER): _extra},
            context(),
            502,
            "routing_invalid_scores",
            id="invalid-scores",
        ),
        pytest.param(
            {(CLASSIFICATIONS_PATH, CLASSIFIER): _tie},
            context(),
            422,
            "routing_ambiguous",
            id="ambiguous",
        ),
        pytest.param({}, context(text=""), 400, "malformed_source", id="malformed"),
    ],
)
async def test_each_routing_outcome_answers_its_status(
    tmp_path: Path, script: dict[Any, Any], raw_context: str, status: int, code: str
) -> None:
    gateway = Gateway(script=script)
    async with engine(gateway, write_world(tmp_path)) as (app, _):
        resp = await call(app, query(raw_context))

    assert (resp.status_code, _error(resp)["code"]) == (status, code)
    assert gateway.posts(CHAT_PATH) == []
    assert ENDPOINT not in resp.text


@pytest.mark.parametrize("warm", [False, True], ids=["cold", "warm"])
async def test_a_routed_answer_is_served_cold_and_warm_with_one_revision(
    tmp_path: Path, warm: bool
) -> None:
    gateway = Gateway(top="math")
    async with engine(gateway, write_world(tmp_path), warm=warm) as (app, _):
        resp = await call(app, query(context()))

    assert resp.status_code == 200
    document = resp.json()
    assert document["selected"] == {"label": "math", "model": MODELS["math"]}
    assert document["revision"] == revision()


async def test_an_answer_seed_is_refused_before_any_gateway_call(tmp_path: Path) -> None:
    gateway = Gateway()
    async with engine(gateway, write_world(tmp_path)) as (app, _):
        resp = await call(app, query(context()), **{"X-Answer-Seed": "7"})

    assert (resp.status_code, _error(resp)["code"]) == (400, "routing_unsupported")
    assert gateway.requests == []


@pytest.mark.parametrize(
    "header",
    [{"X-Capture": "true"}, {"X-Replay-Frozen-Copy": "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"}],
    ids=["capture", "replay"],
)
async def test_a_frozen_copy_header_is_refused_with_no_run(
    tmp_path: Path, header: dict[str, str]
) -> None:
    gateway = Gateway()
    async with engine(gateway, write_world(tmp_path)) as (app, _):
        resp = await call(app, query(context()), **header)

    assert (resp.status_code, _error(resp)["code"]) == (400, "capture_unsupported")
    assert RUN_HEADER not in resp.headers
    assert gateway.requests == []


async def test_the_8_kib_bound_counts_the_raw_path_and_query(tmp_path: Path) -> None:
    gateway = Gateway()
    filler = len(query(context(text="")))
    fits = "a" * (_LIMIT - filler)
    assert len(query(context(text=fits))) == _LIMIT

    async with engine(gateway, write_world(tmp_path)) as (app, _):
        accepted = await call(app, query(context(text=fits)))
        refused = await call(app, query(context(text=fits + "a")))

    assert accepted.status_code == 200
    assert (refused.status_code, _error(refused)["code"]) == (414, "uri_too_long")
    assert [body["input"] for body in gateway.posts(CLASSIFICATIONS_PATH)] == [fits]


@pytest.mark.parametrize(
    "escape", ["%FF", "%ED%A0%80", "%C3"], ids=["not-utf8", "encoded-surrogate", "truncated"]
)
async def test_an_escape_that_is_not_utf8_is_refused_before_any_run(
    tmp_path: Path, escape: str
) -> None:
    gateway = Gateway()
    raw = query(context(text="zz-HOLE-zz"))
    assert "zz-HOLE-zz" in raw

    async with engine(gateway, write_world(tmp_path)) as (app, _):
        refused = await call(app, raw.replace("HOLE", escape))
        control = await call(app, raw.replace("HOLE", "%C3%A9"))

    assert (refused.status_code, _error(refused)["code"]) == (400, "malformed_source")
    assert RUN_HEADER not in refused.headers
    assert control.status_code == 200
    assert [body["input"] for body in gateway.posts(CLASSIFICATIONS_PATH)] == ["zz-é-zz"]


async def test_no_profile_or_model_id_reaches_the_schema_or_a_metric(tmp_path: Path) -> None:
    gateway = Gateway()
    async with engine(gateway, write_world(tmp_path)) as (app, _):
        resp = await call(app, query(context()))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
        ) as client:
            schema = json.dumps((await client.get("/openapi.json")).json())
            metrics = (await client.get("/metrics")).text

    assert resp.status_code == 200
    assert "/route-answer" in schema
    for private in (PROFILE, ENDPOINT):
        assert private not in schema
        assert private not in metrics
    assert (
        'screamingface_engine_mount_calls_total{path="/route-answer",status="200"} 1.0' in metrics
    )


async def test_the_answer_reaches_the_caller_unchanged(tmp_path: Path) -> None:
    gateway = Gateway(top="general")
    gateway.script[(CHAT_PATH, MODELS["general"])] = lambda _: {
        "choices": [
            {
                "message": {"role": "assistant", "content": 'line one\n"two" & ü 😀'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    }
    gateway.script[(DETAILS_PATH, CLASSIFIER)] = lambda _: classifier_document()
    async with engine(gateway, write_world(tmp_path)) as (app, _):
        resp = await call(app, query(context()))

    assert resp.json()["answer"] == 'line one\n"two" & ü 😀'


async def test_a_metadata_body_too_deep_to_read_is_a_failed_preflight(tmp_path: Path) -> None:
    """WHY through the App: an unreadable metadata body is the preflight's verdict, not a `500`."""
    too_deep = httpx.Response(200, content=b"[" * 20_000 + b"]" * 20_000)
    gateway = Gateway(script={(DETAILS_PATH, CLASSIFIER): too_deep})
    async with engine(gateway, write_world(tmp_path)) as (app, _):
        resp = await call(app, query(context()))

    assert (resp.status_code, _error(resp)["code"]) == (502, "routing_preflight_failed")
    assert [request.method for request in gateway.requests] == ["GET"]
