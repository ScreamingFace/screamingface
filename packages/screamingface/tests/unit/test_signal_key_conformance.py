"""The SDK's signal-key grammar and field-rule grammar match the Engine's (OME-1289 gap).

INVARIANT: the SDK keeps a deliberate copy of the Engine's field-path grammar, accounting keys,
reducer signal keys (``judge``, ``writer_<field>``) and ``field_rules@1`` grammars. A change on one
side and not the other fails HERE. Parsed from the engine's source because an app's internals may
never be imported. A present app with a moved file must FAIL, not skip.
FEATURE: a Merge model field reaches the combine call as ``signals["writer_<field>"]``; a key the
Engine refuses would fail every case at run time, after the member calls were paid.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import screamingface as sf
from screamingface._evaluation.topology import _signal_role
from screamingface._signals import (
    _FIELD_INDEX,
    _FIELD_KEY,
    ACCOUNTING_SIGNALS,
    FIELD_PATH,
    FIELD_SIGNAL_PREFIX,
    JUDGE_SIGNAL,
    is_signal_key,
)
from screamingface.fields import _FIELD_NAME, _MEMBER_ID, _RULE_KEYS, MergeNode
from screamingface.judge import JudgeNode

# parents[4] = the monorepo root (tests/unit -> tests -> screamingface -> packages -> root)
_ENGINE_APP = Path(__file__).resolve().parents[4] / "apps" / "screamingface-engine"
_ENGINE_COMBINE = _ENGINE_APP / "src" / "screamingface_engine" / "combine"
_ENGINE_PORTS = _ENGINE_COMBINE / "ports.py"
_ENGINE_SPEC = _ENGINE_COMBINE / "spec.py"
_ENGINE_FIELDS = _ENGINE_COMBINE / "operators" / "fields.py"
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
    for name in ("ACCOUNTING_SIGNALS", "FIELD_SIGNAL_PREFIX", "JUDGE_SIGNAL"):
        assert ast.literal_eval(engine[name]) == ast.literal_eval(sdk[name]), name
    assert _FIELD_KEY == r"[A-Za-z_][A-Za-z0-9_]*"
    assert _FIELD_INDEX == r"\[(?:0|[1-9][0-9]*)\]"
    assert ACCOUNTING_SIGNALS == ("cost_usd", "latency_ms", "tokens_in", "tokens_out")
    assert FIELD_SIGNAL_PREFIX == "field:"
    assert JUDGE_SIGNAL == "score:judge"
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

    assert "field:a.b[0]" in accepted and "score:judge" in accepted and "logprob_mean" in rejected
    assert all(is_signal_key(key) for key in accepted)
    assert not any(is_signal_key(key) for key in rejected)


def _engine_signal_pattern() -> re.Pattern[str]:
    tree = ast.parse(_ENGINE_SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_SIGNAL" for target in node.targets
        ):
            call = node.value
            assert isinstance(call, ast.Call)
            first = call.args[0]
            assert isinstance(first, ast.Constant)
            assert isinstance(first.value, str)
            return re.compile(first.value)
    raise AssertionError("the engine `_SIGNAL` pattern moved — update the bind")


def _sdk_keys() -> list[str]:
    # WHY the internal nodes: the signal calls are planned by the reducer nodes that the surface
    # steps ``sx.Merge`` and ``sx.JudgePick`` lower to.
    merge = MergeNode(
        fields={
            "summary": sf.FieldRule.model("provider/w", prompt="Write."),
            "a1": sf.FieldRule.model("provider/w", prompt="Write."),
            "_x": sf.FieldRule.model("provider/w", prompt="Write."),
            "F" + "z" * 63: sf.FieldRule.model("provider/w", prompt="Write."),
        }
    )
    judge = JudgeNode("provider/j", returns="label", rubric="Pick.")
    return [signal.key for reducer in (merge, judge) for signal in reducer._plan().signal_calls]


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_signal_key_grammar_matches_the_engine() -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent (an installed run);
    # a present app with a moved spec file must FAIL, not skip silently.
    assert _ENGINE_SPEC.exists(), "engine combine/spec.py moved — update the bind"
    pattern = _engine_signal_pattern()

    keys = _sdk_keys()
    assert {"judge", "writer_summary", "writer_a1", "writer__x"} <= set(keys)
    for key in keys:
        assert pattern.fullmatch(key), key
        assert _signal_role(key) is not None, key
    # what the Engine refuses, the SDK refuses too (a dotted key cannot be a url4 struct key)
    for refused in ("writer.summary", "writer_", "writer_1a", "jury", "Judge"):
        assert pattern.fullmatch(refused) is None, refused
        assert _signal_role(refused) is None, refused


def _engine_fields_value(name: str) -> ast.expr:
    tree = ast.parse(_ENGINE_FIELDS.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
    raise AssertionError(f"the engine `{name}` in operators/fields.py moved — update the bind")


def _engine_fields_pattern(name: str) -> str:
    call = _engine_fields_value(name)
    assert isinstance(call, ast.Call)
    first = call.args[0]
    assert isinstance(first, ast.Constant)
    assert isinstance(first.value, str)
    return first.value


def _engine_rule_keys() -> dict[str, frozenset[str]]:
    """``MappingProxyType({"rule": frozenset({"key", ...}), ...})`` as plain data."""

    call = _engine_fields_value("_RULE_KEYS")
    assert isinstance(call, ast.Call)
    table = call.args[0]
    assert isinstance(table, ast.Dict)
    keys: dict[str, frozenset[str]] = {}
    for rule, names in zip(table.keys, table.values, strict=True):
        assert isinstance(rule, ast.Constant)
        assert isinstance(names, ast.Call)
        members = names.args[0]
        assert isinstance(members, ast.Set)
        keys[str(rule.value)] = frozenset(
            str(element.value) for element in members.elts if isinstance(element, ast.Constant)
        )
    return keys


# WHY the same split guard as the signal-key bind: skip only when the whole engine APP is absent
# (an installed run); a present app whose combine/operators/fields.py moved must FAIL, not skip.
_NO_ENGINE_FIELDS = pytest.mark.skipif(
    not _ENGINE_APP.exists(), reason="engine app not present (installed run)"
)


def _require_engine_fields() -> None:
    assert _ENGINE_FIELDS.exists(), "engine combine/operators/fields.py moved — update the bind"


@_NO_ENGINE_FIELDS
def test_field_rule_keys_match_the_engine() -> None:
    _require_engine_fields()
    # INVARIANT: the rule objects the SDK writes have exactly the keys field_rules@1 accepts.
    assert {rule: frozenset(names) for rule, names in _RULE_KEYS.items()} == _engine_rule_keys()


@_NO_ENGINE_FIELDS
def test_field_and_member_grammars_match_the_engine() -> None:
    _require_engine_fields()
    # INVARIANT: a field name or member id the SDK accepts is one the Engine accepts, and the other
    # way round, so a Merge never fails in the Engine only after the member calls were paid.
    assert _FIELD_NAME.pattern == _engine_fields_pattern("_FIELD")
    assert _MEMBER_ID.pattern == _engine_fields_pattern("_MEMBER")
