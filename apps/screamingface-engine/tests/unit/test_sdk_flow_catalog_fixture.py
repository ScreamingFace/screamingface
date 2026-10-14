"""The SDK's flow operator fixture names exactly the engine built-ins (OME-1289 E4a, unit 10).

FEATURE: the SDK tests compile against a fixture catalog and never a live engine.
INVARIANT: that fixture lists the same (id, stage) pairs as the engine's built-in registry, so a new
or renamed built-in cannot drift from what the SDK tests assume.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS

_SDK_PACKAGE = Path(__file__).resolve().parents[4] / "packages" / "screamingface"
_FIXTURE = _SDK_PACKAGE / "tests" / "_combine_flow_fixtures.py"
_NAME = "FLOW_OPERATOR_IDS"

pytestmark = pytest.mark.skipif(not _SDK_PACKAGE.is_dir(), reason="the SDK package is absent")


def _flow_operator_ids() -> list[tuple[str, str]]:
    """The literal value of the ``FLOW_OPERATOR_IDS`` assignment (annotated or plain)."""
    for node in ast.parse(_FIXTURE.read_text("utf-8")).body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == _NAME:
            assert node.value is not None
            return list(ast.literal_eval(node.value))
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == _NAME for target in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise AssertionError(f"{_NAME} is not assigned in {_FIXTURE}")


def test_sdk_flow_catalog_names_exactly_the_builtins() -> None:
    listed = _flow_operator_ids()

    assert len(listed) == len(set(listed)), "the SDK fixture lists an operator twice"
    assert set(listed) == {(d.id, d.stage) for d in BUILTIN_OPERATORS}
