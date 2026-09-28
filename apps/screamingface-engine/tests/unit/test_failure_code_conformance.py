"""Engine-side twin of the SDK failure-code conformance bind (OME-1235).

FEATURE: tell the researcher what kind of failure ended their run (OME-1233).
WHY a twin on the engine side: CI is path-filtered — the SDK's conformance test
never runs on an engine-only PR, so an engine edit to the declared list would
merge green and only fail later on an unrelated SDK PR. This twin runs in the
ENGINE lane and parses the SDK's source, so whichever side drifts, the lane that
carried the drift goes red. No cross-app import in either direction.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.contract import (
    _AIGATEWAY_HTTP_CODE,
    DECLARED_FAILURE_CODES,
)

# parents[3] = apps/, so its parent is the monorepo root
_SDK_PACKAGE = Path(__file__).resolve().parents[3].parent / "packages" / "screamingface"
_SDK_PRIMITIVES = _SDK_PACKAGE / "src" / "screamingface" / "_report_primitives.py"


@pytest.mark.skipif(not _SDK_PACKAGE.exists(), reason="SDK package not present")
def test_the_engine_copy_matches_the_sdk_copy() -> None:
    # INVARIANT (the conformance bind, OME-1233): whichever side adds or removes
    # a code, the lane running THAT side's tests fails loudly. A present SDK
    # package with a missing/renamed primitives file must FAIL, not skip.
    assert _SDK_PRIMITIVES.exists(), "SDK _report_primitives.py moved — update the bind"
    tree = ast.parse(_SDK_PRIMITIVES.read_text(encoding="utf-8"))
    sdk_codes: set[str] | None = None
    sdk_family: str | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == (
            "DECLARED_FAILURE_CODES"
        ):
            constants: list[ast.Constant] = [
                item for item in ast.walk(node) if isinstance(item, ast.Constant)
            ]
            sdk_codes = {item.value for item in constants if isinstance(item.value, str)}
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "_AIGATEWAY_HTTP_CODE" for target in node.targets
        ):
            patterns: list[str] = [
                item.value
                for item in ast.walk(node)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            sdk_family = patterns[0] if patterns else None
    assert sdk_codes is not None, "SDK DECLARED_FAILURE_CODES not found"
    assert sdk_codes == set(DECLARED_FAILURE_CODES)
    assert sdk_family is not None, "SDK aigateway_http family pattern not found"
    assert _AIGATEWAY_HTTP_CODE.pattern == sdk_family
