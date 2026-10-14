"""The SDK's canonical_params is the Engine's, expression for expression (OME-1289, SG#20).

FEATURE: the combine context's `sources[...].params` is built with the Engine's own rule.
STORY: as a researcher, my accounting weights never fall back to None because the SDK spelled a
param differently from the Engine.
INVARIANT: the Engine accepts only the one canonical text, so the two copies must not drift.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from screamingface._evaluation import combine_sources
from screamingface._evaluation.combine_sources import canonical_params

# parents[4] = the monorepo root (tests/unit → tests → screamingface → packages → root)
_ENGINE_APP = Path(__file__).resolve().parents[4] / "apps" / "screamingface-engine"
_ENGINE_SPEC = _ENGINE_APP / "src" / "screamingface_engine" / "combine" / "spec.py"
_SDK_SOURCES = Path(combine_sources.__file__)


def _canonical_params(path: Path) -> tuple[ast.FunctionDef, ast.Module]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "canonical_params"
    ]
    assert len(functions) == 1, f"{path.name} must define canonical_params exactly once"
    return functions[0], tree


def _returned(function: ast.FunctionDef) -> str:
    returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
    assert len(returns) == 1 and returns[0].value is not None
    return ast.dump(returns[0].value)


def _imports_quote_from_urllib(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "urllib.parse"
        and "quote" in {alias.name for alias in node.names}
        for node in ast.walk(tree)
    )


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_canonical_params_matches_the_engine() -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present app
    # with a moved spec file must FAIL, not skip (a dead-battery skip retires the bind silently).
    assert _ENGINE_SPEC.exists(), "engine combine/spec.py moved: update the bind"
    engine, engine_tree = _canonical_params(_ENGINE_SPEC)
    sdk, sdk_tree = _canonical_params(_SDK_SOURCES)

    assert [arg.arg for arg in sdk.args.args] == [arg.arg for arg in engine.args.args]
    assert _returned(sdk) == _returned(engine)
    assert _imports_quote_from_urllib(engine_tree)
    assert _imports_quote_from_urllib(sdk_tree)


def test_canonical_params_pins_the_engine_corpus() -> None:
    # The engine's own pins (tests/unit/test_combine_spec.py::test_canonical_params_round_trip).
    assert canonical_params((("x.y", "1"), ("a", "b c"))) == "a=b%20c&x.y=1"
    assert canonical_params(()) == ""
    assert canonical_params((("k", "a&b=c%"),)) == "k=a%26b%3Dc%25"
