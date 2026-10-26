"""The largest picture Case the importer saves still fits in one gateway request (OME-1271).

FEATURE: every Candidate call carries the whole Case, pictures inline, and the gateway refuses
a request body over its cap with a permanent 413 before any upstream spend (OME-1542). If the
importer's Case limit plus what a request adds around the Case passed that cap, a Case the
importer accepted would fail on every run. INVARIANT: the Case limit plus the request headroom
is at most the gateway's default body cap.

The gateway's cap is read from its source with ``ast``, never imported: aigateway is a separate
uv project and is not installed here (the approach of ``test_data_uri_matches_aigateway.py``).
"""

from __future__ import annotations

import ast
import operator
from pathlib import Path

from screamingface_engine_inspect.picture_input import MAX_CASE_BYTES, MAX_PICTURE_BYTES

_REPO_ROOT = Path(__file__).resolve().parents[4]
_GATEWAY_CONFIG = _REPO_ROOT / "apps/aigateway/src/aigateway/config.py"

# WHY 256 KiB: what a request carries besides the Case (model, parameters, the JSON around the
# messages, and a Fusion synthesizer's member answers, which ride beside the same pictures).
# A synthesizer's text is the Case's text without the base64 plus five members' answers, tens
# of KB in the Benchmarks run so far; the rest of the 8 MiB cap is spare.
_REQUEST_HEADROOM_BYTES = 256 * 1024

_OPERATORS = {ast.Mult: operator.mul, ast.Add: operator.add}


def _number(node: ast.expr) -> int:
    """The value of an integer literal or a product or sum of them, e.g. ``8 * 1024 * 1024``."""

    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_number(node.left), _number(node.right))
    raise AssertionError(f"not an integer expression: {ast.dump(node)}")


def _gateway_body_cap() -> int:
    """The ``default=`` of the gateway's ``max_request_bytes`` setting, from its source."""

    for node in ast.walk(ast.parse(_GATEWAY_CONFIG.read_text())):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "max_request_bytes"
            and isinstance(node.value, ast.Call)
        ):
            for keyword in node.value.keywords:
                if keyword.arg == "default":
                    return _number(keyword.value)
    raise AssertionError(f"max_request_bytes = Field(default=...) not found in {_GATEWAY_CONFIG}")


def test_the_largest_case_plus_its_request_fits_under_the_gateways_body_cap() -> None:
    assert MAX_CASE_BYTES + _REQUEST_HEADROOM_BYTES <= _gateway_body_cap()


def test_one_picture_fits_inside_one_case() -> None:
    # WHY: a picture limit above the Case limit could never be reached; it would only mislead.
    assert MAX_PICTURE_BYTES < MAX_CASE_BYTES
