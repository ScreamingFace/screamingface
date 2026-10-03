"""The SDK-local evidence fixture is the Engine fixture (OME-1289 E4a gap-closure, unit 12; I-E5).

``data/combine_evidence_cases.json`` is hand-run output of the Engine, kept in the SDK because an
installed run has no Engine app. It must never drift from ``evidence_cases.json``, which the
Engine test pins byte for byte. Each SDK-local entry must equal the Engine entry of the same name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _combine_contract import COMBINE_CONTRACT, requires_engine_app

_LOCAL = Path(__file__).parent / "data" / "combine_evidence_cases.json"
_ENGINE = COMBINE_CONTRACT / "evidence_cases.json"


def _load(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"missing evidence fixture {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@requires_engine_app
def test_the_sdk_local_fixture_is_the_engine_fixture() -> None:
    local, engine = _load(_LOCAL), _load(_ENGINE)

    for name, wire in local.items():
        assert name in engine, f"{name} is not an Engine fixture name"
        assert json.dumps(wire) == json.dumps(engine[name]), f"{name} drifted from the Engine"
