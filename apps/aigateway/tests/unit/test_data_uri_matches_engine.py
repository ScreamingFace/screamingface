"""The gateway's ``data:`` URI pattern is the one the Engine checks a Case's pictures with.

FEATURE (OME-1678): the Engine's candidate-input module copies this pattern, so a Case it accepts
also passes here. If the two drift, a picture Case fails at the gateway mid-run, or the Engine
refuses a picture the gateway would take (spec §2.7 gate 4, #1450).

The Engine's pattern is read from its source with ``ast``, never imported: apps never import each
other. The Engine suite holds the twin of this test
(``apps/screamingface-engine/tests/unit/test_data_uri_matches_aigateway.py``), so a change on
either side fails that side's own CI.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from aigateway.core.content_parts import _DATA_URI_RE

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ENGINE_ENVELOPE = (
    _REPO_ROOT / "apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_input.py"
)


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


def test_gateway_data_uri_pattern_is_the_engines() -> None:
    engine_pattern, engine_flags = _compiled_pattern(_ENGINE_ENVELOPE, "_DATA_URI_RE")

    assert _DATA_URI_RE.pattern == engine_pattern
    assert (
        _DATA_URI_RE.flags
        == re.compile(
            engine_pattern, sum((getattr(re, flag) for flag in engine_flags), re.NOFLAG)
        ).flags
    )
