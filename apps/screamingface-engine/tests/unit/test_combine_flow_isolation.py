"""The flow operators hold no shared state (OME-1289, E4a, units 8 to 10; OP-18).

FEATURE: two combine calls in one process never change each other's result.
INVARIANT: a plugin module holds no module-level mutable object (ports.py), and no built-in
operator publishes a mutable args schema.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType

from combine_flow_support import find_builtin, load_flow_fixtures, run_flow_case

from screamingface_engine.combine import operators
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS

_ROUNDS = 50
_MUTABLE = (list, dict, set, bytearray)


def test_flow_operator_calls_share_no_state() -> None:
    jobs = [
        (find_builtin(op_id), case)
        for op_id, fixture in sorted(load_flow_fixtures().items())
        for case in fixture["cases"]
    ]
    assert jobs
    sequential = [run_flow_case(descriptor, case) for descriptor, case in jobs]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(lambda job=job: run_flow_case(*job)) for _ in range(_ROUNDS) for job in jobs
        ]
        parallel = [future.result() for future in futures]
    assert parallel == sequential * _ROUNDS


def test_every_plugin_module_holds_no_mutable_state() -> None:
    names = [info.name for info in pkgutil.iter_modules(operators.__path__)]
    assert "judge" in names
    for name in names:
        module = importlib.import_module(f"{operators.__name__}.{name}")
        for attribute, value in vars(module).items():
            if attribute.startswith("__"):
                continue
            assert not isinstance(value, _MUTABLE), f"{module.__name__}.{attribute}"


def _mutable_paths(value: object, path: str, *, tolerate_dicts: bool) -> list[str]:
    """Every place under ``value`` that holds a list, set, bytearray or (unless tolerated) dict."""
    if isinstance(value, (list, set, bytearray)) or (
        isinstance(value, dict) and not tolerate_dicts
    ):
        return [path]
    if isinstance(value, Mapping):
        children = [(f"{path}[{key!r}]", child) for key, child in value.items()]
        nested_dicts = True
    elif isinstance(value, tuple):
        children = [(f"{path}[{index}]", child) for index, child in enumerate(value)]
        nested_dicts = tolerate_dicts
    else:
        return []
    return [
        found
        for child_path, child in children
        for found in _mutable_paths(child, child_path, tolerate_dicts=nested_dicts)
    ]


def test_every_builtin_args_schema_is_immutable() -> None:
    # WHY nested plain dicts are tolerated: ports.catalog_entry deep-copies and the REST catalog
    # JSON-encodes the schema, and a mappingproxy supports neither; the top level must be immutable.
    for descriptor in BUILTIN_OPERATORS:
        schema = descriptor.args_schema
        assert not isinstance(schema, dict), descriptor.id
        assert _mutable_paths(schema, descriptor.id, tolerate_dicts=True) == [], descriptor.id


def test_the_args_schema_walk_catches_a_mutable_dict() -> None:
    assert _mutable_paths({"a": 1}, "x", tolerate_dicts=False) == ["x"]
    assert _mutable_paths(MappingProxyType({"a": ["b"]}), "x", tolerate_dicts=False) == ["x['a']"]
    assert _mutable_paths(MappingProxyType({"a": ("b",)}), "x", tolerate_dicts=False) == []
