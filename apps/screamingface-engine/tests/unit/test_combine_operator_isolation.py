"""The v1 operators hold no shared state (OME-1289, E4a, unit 2).

FEATURE: two combine calls in one process never change each other's result.
INVARIANT: a plugin module holds no module-level mutable object (ports.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType

from combine_golden_support import MODULE_OPERATORS, find, load_fixtures, run_case

from screamingface_engine.combine.operators import _regex_ban, extract, normalize, reduce, select

_ROUNDS = 50
_MUTABLE = (list, dict, set, bytearray)


def test_concurrent_operator_calls_share_no_state() -> None:
    jobs = [
        (find(op_id), case)
        for op_id, fixture in sorted(load_fixtures().items())
        for case in fixture["cases"]
    ]
    assert jobs
    sequential = [run_case(descriptor, case) for descriptor, case in jobs]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(lambda job=job: run_case(*job)) for _ in range(_ROUNDS) for job in jobs
        ]
        parallel = [future.result() for future in futures]
    assert parallel == sequential * _ROUNDS


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


def test_plugin_modules_hold_no_mutable_module_state() -> None:
    for module in (extract, normalize, reduce, select, _regex_ban):
        for name, value in vars(module).items():
            if name.startswith("__"):
                continue
            assert not isinstance(value, _MUTABLE), f"{module.__name__}.{name}"


def test_operator_descriptors_expose_no_mutable_args_schema() -> None:
    # WHY nested plain dicts are tolerated: ports.catalog_entry deep-copies and the REST catalog
    # JSON-encodes the schema, and a mappingproxy supports neither; the top level must be immutable.
    for descriptor in MODULE_OPERATORS:
        schema = descriptor.args_schema
        assert not isinstance(schema, dict), descriptor.id
        assert _mutable_paths(schema, descriptor.id, tolerate_dicts=True) == [], descriptor.id


def test_the_args_schema_walk_catches_a_mutable_dict() -> None:
    assert _mutable_paths({"a": 1}, "x", tolerate_dicts=False) == ["x"]
    assert _mutable_paths(MappingProxyType({"a": ["b"]}), "x", tolerate_dicts=False) == ["x['a']"]
    assert _mutable_paths(MappingProxyType({"a": ("b",)}), "x", tolerate_dicts=False) == []
