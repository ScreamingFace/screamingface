"""The SDK's declared-name rule matches the Engine's (E4b part 3, DS#5 guard).

INVARIANT: the SDK keeps a deliberate copy of the Engine's declared-name rule: the name grammar,
the reserved prefixes and the cap of 8 declared signals. A change on one side and not the other
fails HERE. Parsed from the engine's source because an app's internals may never be imported.
A present app with a moved file must FAIL, not skip.
FEATURE: a Fusion declares signals={"conf": sf.Verbalized(...)}; the Engine refuses a name the SDK
accepted, after the member calls were paid.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from screamingface._signals import (
    ACCOUNTING_SIGNALS,
    DECLARED_NAME,
    MAX_DECLARED_SIGNALS,
    RESERVED_NAME_PREFIXES,
    is_signal_name,
)

# parents[4] = the monorepo root (tests/unit -> tests -> screamingface -> packages -> root)
_ENGINE_APP = Path(__file__).resolve().parents[4] / "apps" / "screamingface-engine"
_ENGINE_PORTS = _ENGINE_APP / "src" / "screamingface_engine" / "combine" / "ports.py"
_SDK_SIGNALS = Path(__file__).resolve().parents[2] / "src" / "screamingface" / "_signals.py"
_CORPUS = [
    "conf",
    "cost",
    "a" * 32,
    "a" * 33,
    "Cost",
    "",
    "cost_usd",
    "logprob_x",
    "entropy",
    "verbalized_y",
    "consistency",
    "field:x",
    "score:judge",
    "1a",
    "a-b",
]
_SKIP_NO_ENGINE = pytest.mark.skipif(
    not _ENGINE_APP.exists(), reason="engine app not present (installed run)"
)


def _segments(path: Path) -> dict[str, str]:
    """The source text of each module-level assignment, by target name."""
    source = path.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            segment = ast.get_source_segment(source, node.value)
            assert segment is not None
            found[node.target.id] = segment
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            segment = ast.get_source_segment(source, node.value)
            assert segment is not None
            found[node.targets[0].id] = segment
    return found


@_SKIP_NO_ENGINE
def test_sdk_declared_name_rule_matches_the_engine_ports() -> None:
    assert _ENGINE_PORTS.exists(), "engine combine/ports.py moved - update the bind"
    engine = _segments(_ENGINE_PORTS)
    sdk = _segments(_SDK_SIGNALS)

    for name in ("DECLARED_NAME", "RESERVED_NAME_PREFIXES", "MAX_DECLARED_SIGNALS"):
        assert engine[name] == sdk[name], name
    assert DECLARED_NAME.pattern == r"[a-z][a-z0-9_]{0,31}"
    assert RESERVED_NAME_PREFIXES == ("logprob", "entropy", "verbalized", "consistency")
    assert MAX_DECLARED_SIGNALS == 8


@_SKIP_NO_ENGINE
def test_declared_name_answers_agree_on_the_corpus() -> None:
    assert _ENGINE_PORTS.exists(), "engine combine/ports.py moved - update the bind"
    # WHY evaluate the engine's own constants: the engine rule is a function of these three names
    # and ACCOUNTING_SIGNALS, so the same rule body runs over the engine's text.
    engine = _segments(_ENGINE_PORTS)
    namespace: dict[str, Any] = {"re": re}
    exec(f"DECLARED_NAME = {engine['DECLARED_NAME']}", namespace)  # noqa: S102 - our own file
    namespace["RESERVED_NAME_PREFIXES"] = tuple(ast.literal_eval(engine["RESERVED_NAME_PREFIXES"]))
    namespace["ACCOUNTING_SIGNALS"] = tuple(ast.literal_eval(engine["ACCOUNTING_SIGNALS"]))

    def engine_rule(key: str) -> bool:
        return (
            namespace["DECLARED_NAME"].fullmatch(key) is not None
            and key not in namespace["ACCOUNTING_SIGNALS"]
            and not key.startswith(namespace["RESERVED_NAME_PREFIXES"])
        )

    assert ACCOUNTING_SIGNALS == tuple(namespace["ACCOUNTING_SIGNALS"])
    for key in _CORPUS:
        assert is_signal_name(key) == engine_rule(key), key
    assert [key for key in _CORPUS if is_signal_name(key)] == ["conf", "cost", "a" * 32]
