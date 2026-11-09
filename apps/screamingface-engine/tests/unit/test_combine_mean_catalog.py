"""The catalog and the pinned wire schemas name mean@1, weighted_mean@1 and the evidence `mean`.

FEATURE: an SDK can compile sf.Mean only against an Engine whose catalog lists the two reduce ids,
and the combine wire schemas say what a mean spec and a mean evidence look like (E4b unit 3).
STORY: as a Fusion author on an SF Engine, `GET /v1/operators` tells me the mean operators exist.
INVARIANT defended: the schema ids do not change (ans:Q5); only the listed enum values and the one
optional `mean` property are added.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from screamingface_engine.app import create_app
from screamingface_engine.combine.evidence import COMBINE_EVIDENCE_SCHEMA
from screamingface_engine.combine.spec import COMBINE_SPEC_SCHEMA, CombineSpec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

SCHEMAS = Path(__file__).parent / "data" / "combine_contract" / "schemas"


async def _get(
    app: FastAPI, path: str, *, headers: Mapping[str, str] | None = None
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        return await client.get(path, headers=headers)


@pytest.mark.asyncio
async def test_operator_catalog_lists_the_new_reduce_ids() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())
    listed = {e["id"]: e for e in (await _get(app, "/v1/operators")).json()["data"]}
    assert {
        i: (listed[i]["stage"], listed[i]["version"], listed[i]["args_schema"])
        for i in ("mean@1", "weighted_mean@1")
    } == {"mean@1": ("reduce", 1, {}), "weighted_mean@1": ("reduce", 1, {})}


def test_combine_spec_v1_lists_mean_in_the_reducer_enum() -> None:
    pinned = json.loads((SCHEMAS / "screamingface.combine-spec.v1.json").read_text("utf-8"))
    assert "mean" in pinned["properties"]["reducer"]["enum"]
    assert COMBINE_SPEC_SCHEMA == "screamingface.combine-spec.v1"
    live = CombineSpec.model_json_schema(by_alias=True, mode="validation")
    assert "mean" in live["properties"]["reducer"]["enum"]


def test_combine_evidence_v1_has_an_optional_mean_field() -> None:
    pinned = json.loads((SCHEMAS / "screamingface.combine-evidence.v1.json").read_text("utf-8"))
    # INVARIANT (P8): `mean` is optional on the wire; the key is written only for the mean reducer.
    assert pinned["properties"]["mean"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "default": None,
        "title": "Mean",
    }
    assert "mean" not in pinned["required"]
    assert "mean" in pinned["properties"]["reducer"]["enum"]
    assert COMBINE_EVIDENCE_SCHEMA == "screamingface.combine-evidence.v1"
