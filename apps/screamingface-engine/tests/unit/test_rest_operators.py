"""``GET /v1/operators`` lists the combine operator registry (OME-1289 E4a, unit 3).

FEATURE: a client reads which combine operators this Engine runs, before it compiles a reducer.
STORY: as the SDK, I fetch the catalog once, cache it by ETag, and learn each operator's id,
stage and summary without a call to the combine route.
INVARIANT defended: the catalog lists exactly the built-in ids, and each one resolves. The App
reads ``app.state.operators`` (a test-only seam) while the runner's factory installs
``BUILTIN_OPERATORS``; both default to that one constant, and
``test_combine_wiring.py`` pins that the factory passes the same object the default App serves.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

import httpx
import pytest
from fastapi import FastAPI

from screamingface_engine.app import create_app
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS, BUILTIN_REGISTRATIONS
from screamingface_engine.combine.ports import (
    OpArgs,
    OperatorDescriptor,
    OperatorUnknown,
    StageResult,
    accepted,
)
from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

# Hand-written (not derived from the registry), in plain string order.
_BUILTIN_IDS = [
    "boxed@1",
    "first_holder@1",
    "identity@1",
    "inspect_aime@1",
    "inspect_number@1",
    "inspect_numeric@1",
    "json_field@1",
    "last_line@1",
    "last_number@1",
    "max_weight_holder@1",
    "median@1",
    "mode@1",
    "nearest@1",
    "numeric@1",
    "regex@1",
    "set@1",
    "text@1",
    "value@1",
    "weighted_mode@1",
    "whole@1",
]
_NEW_IDS = frozenset(
    {"inspect_aime@1", "inspect_number@1", "inspect_numeric@1", "regex@1", "set@1"}
)
# The ids that shipped before the regex, set and Inspect-rule operators.
_V1_IDS = frozenset(_BUILTIN_IDS) - _NEW_IDS


async def _get(
    app: FastAPI, path: str, *, headers: Mapping[str, str] | None = None
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        return await client.get(path, headers=headers)


def _unordered_registry() -> OperatorRegistry:
    def keep(text: str, args: OpArgs, /) -> StageResult:
        return accepted(text)

    return OperatorRegistry(
        (
            OperatorDescriptor("zeta", 2, "extract", "Last one.", keep),
            OperatorDescriptor("alpha", 1, "extract", "First one.", keep),
        )
    )


@pytest.mark.asyncio
async def test_get_v1_operators_lists_registry_sorted_with_etag_and_304() -> None:
    registry = _unordered_registry()
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream(), operators=registry)

    response = await _get(app, "/v1/operators")

    expected = {
        "object": "list",
        "data": [
            {
                "id": "alpha@1",
                "name": "alpha",
                "version": 1,
                "stage": "extract",
                "args_schema": {},
                "summary": "First one.",
            },
            {
                "id": "zeta@2",
                "name": "zeta",
                "version": 2,
                "stage": "extract",
                "args_schema": {},
                "summary": "Last one.",
            },
        ],
    }
    body = json.dumps(expected, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    etag = f'"{hashlib.sha256(body).hexdigest()[:32]}"'
    assert response.status_code == 200
    assert response.json() == expected
    assert response.content == body
    assert response.headers["etag"] == etag
    assert response.headers["cache-control"] == "public, max-age=300, must-revalidate"
    assert response.headers["content-type"].startswith("application/json")

    repeated = await _get(app, "/v1/operators", headers={"If-None-Match": etag})
    other = await _get(app, "/v1/operators", headers={"If-None-Match": '"not-this-one"'})

    assert repeated.status_code == 304
    assert repeated.content == b""
    assert repeated.headers["etag"] == etag
    assert other.status_code == 200
    assert other.json() == expected


@pytest.mark.asyncio
async def test_catalog_ids_equal_resolvable_ids() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())

    listed = (await _get(app, "/v1/operators")).json()["data"]

    ids = [entry["id"] for entry in listed]
    # WHY a subset for the hand-written list: later units add built-ins; the exact set is the
    # registry itself, sorted.
    assert ids == sorted(descriptor.id for descriptor in BUILTIN_OPERATORS)
    assert set(_BUILTIN_IDS) <= set(ids)
    for entry in listed:
        assert BUILTIN_OPERATORS.resolve(entry["id"], entry["stage"]).id == entry["id"]
    with pytest.raises(OperatorUnknown):
        BUILTIN_OPERATORS.resolve("last_number@9", "extract")


@pytest.mark.asyncio
async def test_operator_catalog_lists_regex_set_and_inspect_rules() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())

    listed = {entry["id"]: entry for entry in (await _get(app, "/v1/operators")).json()["data"]}

    assert {
        operator_id: (listed[operator_id]["stage"], listed[operator_id]["version"])
        for operator_id in sorted(_NEW_IDS)
    } == {
        "inspect_aime@1": ("extract", 1),
        "inspect_number@1": ("extract", 1),
        "inspect_numeric@1": ("normalize", 1),
        "regex@1": ("extract", 1),
        "set@1": ("normalize", 1),
    }
    assert listed["regex@1"]["args_schema"] == {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "minLength": 1, "maxLength": 256},
            "group": {"type": ["integer", "string"]},
            "occurrence": {"enum": ["last", "first"]},
            "ignore_case": {"type": "boolean"},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
    for operator_id in ("set@1", "inspect_number@1", "inspect_aime@1", "inspect_numeric@1"):
        assert listed[operator_id]["args_schema"] == {}
    assert {operator_id: listed[operator_id]["summary"] for operator_id in sorted(_NEW_IDS)} == {
        "inspect_aime@1": "The AIME answer, by inspect-evals 0.20.0 aime_scorer.",
        "inspect_number@1": "The last number word, by inspect-ai 0.3.263 match(numeric=True).",
        "inspect_numeric@1": (
            "The number as inspect-ai 0.3.263 compares it (5 significant digits)."
        ),
        "regex@1": "One regex group (RE2 syntax) from the last 1024 characters.",
        "set@1": "Sorted, casefolded, distinct list items as canonical JSON.",
    }


@pytest.mark.asyncio
async def test_new_operators_change_the_catalog_etag() -> None:
    v1_registry = OperatorRegistry(d for d in BUILTIN_REGISTRATIONS if d.id in _V1_IDS)
    v1_app = create_app(
        Settings(jwt_secret="s"), stream=InMemoryEventStream(), operators=v1_registry
    )
    default_app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())

    v1_response = await _get(v1_app, "/v1/operators")
    default_response = await _get(default_app, "/v1/operators")

    assert len(v1_response.json()["data"]) == len(_V1_IDS)
    assert v1_response.headers["etag"] != default_response.headers["etag"]
    for response in (v1_response, default_response):
        assert response.headers["etag"] == f'"{hashlib.sha256(response.content).hexdigest()[:32]}"'
