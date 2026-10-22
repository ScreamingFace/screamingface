"""The Engine reads a Case's inline pictures with the gateway's own ``data:`` URI pattern.

FEATURE (OME-1678): the envelope module checks each picture's ``data:`` prefix before the Case
leaves the Engine, and the gateway checks it again on arrival. If the two patterns drift, a Case
the Engine accepted fails at the gateway mid-run, or the Engine refuses a picture the gateway
would take (spec §2.7 gate 4, #1450).

The gateway's pattern is read from its source with ``ast``, never imported: aigateway is a
separate uv project and is not installed here (the approach of
``test_judge_params_match_aigateway.py``). The gateway suite holds the twin of this test
(``apps/aigateway/tests/unit/test_data_uri_matches_engine.py``), so a change on either side
fails that side's own CI.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from screamingface_engine.benchmarks.candidate_input import _DATA_URI_RE

_REPO_ROOT = Path(__file__).resolve().parents[4]
_GATEWAY_PARTS = _REPO_ROOT / "apps/aigateway/src/aigateway/core/content_parts.py"


def _compiled_pattern(source: Path, name: str) -> tuple[str, set[str]]:
    """The pattern text and ``re`` flag names of ``name = re.compile(...)`` in a source file."""

    for node in ast.walk(ast.parse(source.read_text())):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.args[0], ast.Constant)
            and isinstance(node.value.args[0].value, str)
        ):
            flags: set[str] = {
                arg.attr for arg in node.value.args[1:] if isinstance(arg, ast.Attribute)
            }
            return node.value.args[0].value, flags
    raise AssertionError(f"{name} = re.compile(...) not found in {source}")


def test_engine_data_uri_pattern_is_the_gateways() -> None:
    gateway_pattern, gateway_flags = _compiled_pattern(_GATEWAY_PARTS, "_DATA_URI_RE")

    assert _DATA_URI_RE.pattern == gateway_pattern
    assert (
        _DATA_URI_RE.flags
        == re.compile(
            gateway_pattern, sum((getattr(re, flag) for flag in gateway_flags), re.NOFLAG)
        ).flags
    )
