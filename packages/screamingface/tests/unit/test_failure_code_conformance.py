"""The SDK's failure-code vocabulary: refusal + conformance with the engine (OME-1235).

FEATURE: tell the researcher what kind of failure ended their run (OME-1233).
STORY: as a researcher, the failure code in my report always comes from the one
declared list — the engine and SDK copies cannot drift apart.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from screamingface._report_primitives import (
    DECLARED_FAILURE_CODES,
    Failure,
    is_declared_failure_code,
)

_ENGINE_CONTRACT = (
    # parents[4] = the monorepo root (tests/unit → tests → screamingface → packages → root)
    Path(__file__).resolve().parents[4]
    / "apps"
    / "screamingface-engine"
    / "src"
    / "screamingface_engine"
    / "benchmarks"
    / "contract.py"
)


def _failure(code: str) -> Failure:
    return Failure(stage="grading", code=code, message="a message")


def test_an_undeclared_code_is_refused() -> None:
    # INVARIANT: an undeclared code cannot enter a Report object — the same
    # refusal the engine model makes, mirrored on the consuming side.
    with pytest.raises(ValueError, match="undeclared failure code"):
        _failure("a_code_nobody_declared")


def test_declared_codes_and_the_http_family_pass() -> None:
    assert _failure("judge_reply_invalid").code == "judge_reply_invalid"
    assert _failure("upstream_error").code == "upstream_error"
    # INVARIANT: the connector's per-status family is declared by pattern —
    # the status number is load-bearing for retry advice.
    assert _failure("aigateway_http_429").code == "aigateway_http_429"
    assert not is_declared_failure_code("aigateway_http_9999")


def test_retired_spellings_are_refused() -> None:
    # INVARIANT: the reconciled-away grader spelling and the removed board
    # hatch cannot come back through the SDK either.
    for retired in ("no_valid_judge_verdict", "board_owned_code"):
        with pytest.raises(ValueError, match="undeclared failure code"):
            _failure(retired)


@pytest.mark.skipif(not _ENGINE_CONTRACT.exists(), reason="engine source not present")
def test_the_sdk_copy_matches_the_engine_copy() -> None:
    # INVARIANT (the conformance bind, OME-1233): the engine and SDK keep two
    # deliberate copies of one list — a code added on one side and forgotten on
    # the other fails HERE, loudly, instead of drifting apart. Parsed from the
    # engine's source because an app's internals may never be imported.
    tree = ast.parse(_ENGINE_CONTRACT.read_text(encoding="utf-8"))
    engine_codes: set[str] | None = None
    engine_family: str | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == (
            "DECLARED_FAILURE_CODES"
        ):
            constants: list[ast.Constant] = [
                item for item in ast.walk(node) if isinstance(item, ast.Constant)
            ]
            engine_codes = {item.value for item in constants if isinstance(item.value, str)}
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "_AIGATEWAY_HTTP_CODE" for target in node.targets
        ):
            patterns: list[str] = [
                item.value
                for item in ast.walk(node)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            engine_family = patterns[0] if patterns else None
    assert engine_codes is not None, "engine DECLARED_FAILURE_CODES not found"
    assert engine_codes == set(DECLARED_FAILURE_CODES)
    assert engine_family is not None, "engine aigateway_http family pattern not found"
    assert is_declared_failure_code("aigateway_http_500")
    assert engine_family == r"aigateway_http_[1-5][0-9]{2}"
