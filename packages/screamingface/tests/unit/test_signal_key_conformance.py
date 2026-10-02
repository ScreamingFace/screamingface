"""The SDK's signal-key grammar matches the Engine's combine ports (OME-1289 gap, SG#4).

INVARIANT: the SDK keeps a deliberate copy of the Engine's field-path grammar and accounting keys.
A change on one side and not the other fails HERE. Parsed from the engine's source because an app's
internals may never be imported. A present app with a moved file must FAIL, not skip.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from screamingface._signals import (
    _FIELD_INDEX,
    _FIELD_KEY,
    ACCOUNTING_SIGNALS,
    FIELD_PATH,
    FIELD_SIGNAL_PREFIX,
    is_signal_key,
)

# parents[4] = the monorepo root (tests/unit -> tests -> screamingface -> packages -> root)
_ENGINE_APP = Path(__file__).resolve().parents[4] / "apps" / "screamingface-engine"
_ENGINE_PORTS = _ENGINE_APP / "src" / "screamingface_engine" / "combine" / "ports.py"
_ENGINE_PORTS_TEST = _ENGINE_APP / "tests" / "unit" / "test_combine_ports.py"
_SDK_SIGNALS = Path(__file__).resolve().parents[2] / "src" / "screamingface" / "_signals.py"


def _assignments(path: Path) -> dict[str, ast.expr]:
    source = path.read_text(encoding="utf-8")
    found: dict[str, ast.expr] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            found[node.targets[0].id] = node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            found[node.target.id] = node.value
    return found


def _segment(path: Path, node: ast.expr) -> str:
    segment = ast.get_source_segment(path.read_text(encoding="utf-8"), node)
    assert segment is not None
    return segment


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_sdk_field_path_and_accounting_keys_match_the_engine_ports() -> None:
    assert _ENGINE_PORTS.exists(), "engine combine/ports.py moved - update the bind"
    engine = _assignments(_ENGINE_PORTS)
    sdk = _assignments(_SDK_SIGNALS)

    for name in ("_FIELD_KEY", "_FIELD_INDEX", "FIELD_PATH"):
        assert _segment(_ENGINE_PORTS, engine[name]) == _segment(_SDK_SIGNALS, sdk[name]), name
    for name in ("ACCOUNTING_SIGNALS", "FIELD_SIGNAL_PREFIX"):
        assert ast.literal_eval(engine[name]) == ast.literal_eval(sdk[name]), name
    assert _FIELD_KEY == r"[A-Za-z_][A-Za-z0-9_]*"
    assert _FIELD_INDEX == r"\[(?:0|[1-9][0-9]*)\]"
    assert ACCOUNTING_SIGNALS == ("cost_usd", "latency_ms", "tokens_in", "tokens_out")
    assert FIELD_SIGNAL_PREFIX == "field:"
    assert FIELD_PATH.fullmatch("a.b[0]") and not FIELD_PATH.fullmatch("a..b")


def _engine_corpus() -> tuple[list[object], list[object]]:
    """The accepted and rejected keys of the Engine's own signal-key test, read by AST."""

    assert _ENGINE_PORTS_TEST.exists(), "engine test_combine_ports.py moved - update the bind"
    tree = ast.parse(_ENGINE_PORTS_TEST.read_text(encoding="utf-8"))
    tests = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_signal_keys_are_the_accounting_keys_and_field_paths"
    ]
    assert len(tests) == 1, "engine signal-key test not found - update the bind"
    loops = [node.iter for node in ast.walk(tests[0]) if isinstance(node, ast.For)]
    assert len(loops) == 2, "engine signal-key corpus changed shape - update the bind"
    return _elements(loops[0]), _elements(loops[1])


def _elements(node: ast.expr) -> list[object]:
    assert isinstance(node, ast.Tuple)
    found: list[object] = []
    for item in node.elts:
        if isinstance(item, ast.Starred):
            assert ast.unparse(item.value) == "ACCOUNTING_SIGNALS"
            found.extend(ACCOUNTING_SIGNALS)
        else:
            found.append(ast.literal_eval(item))
    return found


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_sdk_signal_key_corpus_agrees_with_the_engine_corpus() -> None:
    accepted, rejected = _engine_corpus()

    assert "field:a.b[0]" in accepted and "logprob_mean" in rejected
    assert all(is_signal_key(key) for key in accepted)
    # `score:judge` is accepted by the SDK now (I-S1) and by the Engine from unit 8E, so it is the
    # one key the two corpora are allowed to disagree on.
    assert not any(is_signal_key(key) for key in rejected if key != "score:judge")
    assert is_signal_key("score:judge")
