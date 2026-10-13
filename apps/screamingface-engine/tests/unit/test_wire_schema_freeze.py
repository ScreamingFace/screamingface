"""The combine wire schemas are frozen per schema id (OME-1289 E4a gap-closure, unit 12; RT#2).

FEATURE: ``combine-spec.v1``, ``combine-evidence.v1`` (and ``budget.v1``) each have a pinned JSON
Schema file under ``data/combine_contract/schemas/<schema id>.json``.
STORY: as a maintainer, I change a wire model and this test fails unless I also bump the schema id,
so a released wire shape never changes under the same id.
INVARIANT defended: the pinned file is never overwritten by a run. Regeneration of a MISSING file
is an explicit act (``UPDATE_SCHEMA_SNAPSHOT=1``); it writes only missing files and still fails that
run, as the SDK public surface test does.
AIDEV-NOTE: a pure pydantic rendering change (a library upgrade that moves the schema text) is
accepted by deleting the file and regenerating it; that act shows in review.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args

import pytest
from schema_freeze_support import check_frozen

from screamingface_engine.budget import BUDGET_SCHEMA, budget_schemas
from screamingface_engine.combine.evidence import COMBINE_EVIDENCE_SCHEMA, CombineEvidence
from screamingface_engine.combine.spec import COMBINE_SPEC_SCHEMA, CombineSpec

SCHEMAS = Path(__file__).parent / "data" / "combine_contract" / "schemas"
UPDATE = os.environ.get("UPDATE_SCHEMA_SNAPSHOT", "").strip().lower() in {"1", "true"}
_SCHEMA = {"title": "Thing", "type": "object", "properties": {"a": {"type": "integer"}}}


def test_the_same_id_and_the_same_schema_passes(tmp_path: Path) -> None:
    (tmp_path / "x.v1.json").write_text(_rendered(_SCHEMA), encoding="utf-8")

    check_frozen(tmp_path, "x.v1", _SCHEMA, update=False)


def test_the_same_id_and_another_schema_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x.v1.json").write_text(_rendered(_SCHEMA), encoding="utf-8")
    other = {**_SCHEMA, "properties": {"a": {"type": "string"}}}

    with pytest.raises(AssertionError, match="without a schema id change"):
        check_frozen(tmp_path, "x.v1", other, update=False)


def test_a_missing_file_names_the_update_variable(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="UPDATE_SCHEMA_SNAPSHOT"):
        check_frozen(tmp_path, "x.v1", _SCHEMA, update=False)

    assert not (tmp_path / "x.v1.json").exists()


def test_update_mode_writes_a_missing_file_and_still_fails(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="written"):
        check_frozen(tmp_path, "x.v1", _SCHEMA, update=True)

    assert (tmp_path / "x.v1.json").read_text(encoding="utf-8") == _rendered(_SCHEMA)


def test_update_mode_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    pinned = tmp_path / "x.v1.json"
    pinned.write_text(_rendered(_SCHEMA), encoding="utf-8")
    before = pinned.read_bytes()
    other = {**_SCHEMA, "title": "Other"}

    with pytest.raises(AssertionError, match="without a schema id change"):
        check_frozen(tmp_path, "x.v1", other, update=True)

    assert pinned.read_bytes() == before


def _rendered(schema: Mapping[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


_WIRE = [
    pytest.param(
        COMBINE_SPEC_SCHEMA,
        CombineSpec.model_json_schema(by_alias=True, mode="validation"),
        id="combine-spec",
    ),
    pytest.param(
        COMBINE_EVIDENCE_SCHEMA,
        CombineEvidence.model_json_schema(by_alias=True, mode="validation"),
        id="combine-evidence",
    ),
    pytest.param(BUDGET_SCHEMA, budget_schemas(), id="budget"),
]


@pytest.mark.parametrize(
    ("schema_id", "model"),
    [(COMBINE_SPEC_SCHEMA, CombineSpec), (COMBINE_EVIDENCE_SCHEMA, CombineEvidence)],
)
def test_the_schema_literal_of_a_wire_model_is_the_module_constant(
    schema_id: str, model: Any
) -> None:
    assert get_args(model.model_fields["schema_id"].annotation) == (schema_id,)


@pytest.mark.parametrize(("schema_id", "schema"), _WIRE)
def test_frozen_wire_schemas_match_snapshot_unless_id_changes(
    schema_id: str, schema: Mapping[str, Any]
) -> None:
    check_frozen(SCHEMAS, schema_id, schema, update=UPDATE)
