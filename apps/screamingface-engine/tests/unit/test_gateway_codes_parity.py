"""The Engine lifts exactly the codes the Gateway declares (spec 3.4, gateway code provenance).

FEATURE: Gateway code provenance (`docs/spec/2026-11-23-gateway-code-provenance.md`).
INVARIANT: `GATEWAY_CODES` is the Gateway fixture's `codes | retired` less the Engine-reserved
codes, exactly. A code the Engine lifts and the Gateway does not declare fails here, and so does a
declared code the Engine misses. The overlap with `ENGINE_RESERVED_CODES` is pinned, so a new
collision fails until it is reviewed.

The fixture is the Gateway's own (`apps/aigateway/tests/fixtures/gateway_error_codes/`), checked
against its source by the Gateway suite; the Engine workflow runs on a change to it.
"""

from __future__ import annotations

import json
from pathlib import Path

from screamingface_engine.error_text import ENGINE_RESERVED_CODES
from screamingface_engine.world.gateway_codes import GATEWAY_CODES

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIXTURE = _REPO_ROOT / "apps/aigateway/tests/fixtures/gateway_error_codes/codes.json"

# WHY these three: the Gateway writes them and the Engine keeps them as its own. The two replay
# refusals are read before `_raise_for_status` (`world/connector.py::_replay_refusal`), and
# `result_too_large` is the Engine's own delivery failure.
_RESERVED_OVERLAP = frozenset({"frozen_copy_miss", "frozen_copy_unavailable", "result_too_large"})


def _declared() -> frozenset[str]:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return frozenset(fixture["codes"]) | frozenset(fixture["retired"])


def test_the_engine_lifts_exactly_the_declared_gateway_codes() -> None:
    assert GATEWAY_CODES == _declared() - ENGINE_RESERVED_CODES


def test_the_gateway_codes_the_engine_reserves_are_exactly_the_pinned_three() -> None:
    assert _declared() & ENGINE_RESERVED_CODES == _RESERVED_OVERLAP
