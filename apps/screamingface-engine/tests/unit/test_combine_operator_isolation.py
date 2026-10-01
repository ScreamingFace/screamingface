"""The v1 operators hold no shared state (OME-1289, E4a, unit 2).

FEATURE: two combine calls in one process never change each other's result.
INVARIANT: a plugin module holds no module-level mutable object (ports.py).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from combine_golden_support import find, load_fixtures, run_case

from screamingface_engine.combine.operators import extract, normalize, reduce, select

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


def test_plugin_modules_hold_no_mutable_module_state() -> None:
    for module in (extract, normalize, reduce, select):
        for name, value in vars(module).items():
            if name.startswith("__"):
                continue
            assert not isinstance(value, _MUTABLE), f"{module.__name__}.{name}"
