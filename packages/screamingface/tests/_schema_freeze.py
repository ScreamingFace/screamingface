"""The schema freeze check for the SDK record field sets (not a test module; OME-1289, unit 12).

One JSON file per schema id holds the pinned field set of the SDK records that carry that id. A
change with the same id is refused: bump the id to ``v2``. The same contract as the Engine's
``schema_freeze_support.check_frozen`` (two separate packages, so two small copies).

AIDEV-NOTE: the freeze pins the field names and vocabularies only. A validator-rule or field-type
change under the same id is not caught, so a reviewer must check it by hand.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


def check_frozen(
    directory: Path, schema_id: str, schema: Mapping[str, object], *, update: bool
) -> None:
    """Pass when ``directory/<schema_id>.json`` holds ``schema``; fail otherwise.

    A missing file fails and names ``UPDATE_SCHEMA_SNAPSHOT=1``. With ``update`` the missing file
    is written and the run still fails. A file that differs fails in both modes and is never
    overwritten.
    """
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    path = directory / f"{schema_id}.json"
    if not path.exists():
        if update:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
            raise AssertionError(f"schema snapshot written at {path.name}; review it and re-run")
        raise AssertionError(
            f"missing schema snapshot {path}; write it once with UPDATE_SCHEMA_SNAPSHOT=1"
        )
    assert path.read_text(encoding="utf-8") == rendered, (
        f"{schema_id} changed without a schema id change; bump the id to v2 "
        f"(or delete {path.name} and regenerate it for a pure pydantic rendering change)"
    )
