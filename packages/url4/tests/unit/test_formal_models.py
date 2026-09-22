"""The formal models in ``tests/formal`` stay checkable — and stay broken on purpose.

The ``fm.py`` driver named in each model's header is a local skill, not a CI
dependency, so the two executor-memo models are checked here by a minimal
breadth-first checker: same model contract (``init`` / ``actions`` /
``INVARIANTS``), same verdict. The as-written model must stay clean; the bug
model must keep producing its violation — a model that silently stops
demonstrating its bug protects nothing.

The models mirror ``Executor._run``'s memo invariant and the ``spawn_hook``
compile-cache invariant (dag/executor.py, the INVARIANT comments above the
check-then-act blocks): the shared child of a diamond resolves exactly once,
and a unique spawned text compiles exactly once — each only while the check
and the store are one atomic action.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_MODELS = Path(__file__).resolve().parent.parent / "formal"

# Both models stay under ~30 states; the bound only catches a runaway edit that
# grows an unbounded field (the driver's "state must be hashable-after-freezing"
# rule), turning a silent hang into a loud failure.
_MAX_STATES = 10_000


def _load(name: str) -> ModuleType:
    path = _MODELS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None  # the file ships with the tests
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _freeze(state: object) -> object:
    """A hashable canonical form, so equal states dedupe in the seen-set."""
    if isinstance(state, dict):
        return tuple(sorted((key, _freeze(value)) for key, value in state.items()))
    if isinstance(state, (set, frozenset, list, tuple)):
        return _freeze_items(state)
    return state


def _freeze_items(
    items: set[object] | frozenset[object] | list[object] | tuple[object, ...],
) -> object:
    if isinstance(items, (set, frozenset)):
        return frozenset(_freeze(item) for item in items)  # order-insensitive, like the set
    return tuple(_freeze(item) for item in items)


def _violations(model: ModuleType) -> dict[str, list[dict[str, object]]]:
    """Explore every reachable state; return each invariant with a witness state."""
    bad: dict[str, list[dict[str, object]]] = {}
    seen: set[object] = set()
    frontier: list[dict[str, object]] = [model.init()]
    while frontier:
        assert len(seen) < _MAX_STATES, "state bound hit — the model grew an unbounded field"
        state = frontier.pop()
        key = _freeze(state)
        if key in seen:
            continue
        seen.add(key)
        for name, holds in model.INVARIANTS.items():
            if not holds(state):
                bad.setdefault(name, []).append(state)
        frontier.extend(next_state for _, next_state in model.actions(state))
    return bad


def test_executor_memo_model_as_written_is_clean() -> None:
    """The atomic check-then-act keeps ``evals <= 1`` across every reachable state."""
    assert _violations(_load("executor_memo_fixed")) == {}


def test_executor_memo_buggy_model_still_produces_its_violation() -> None:
    """Splitting the check from the store by a yield point must stay refutable."""
    bad = _violations(_load("executor_memo_buggy"))
    assert "child_resolved_at_most_once" in bad, "the bug model stopped demonstrating the bug"
    assert any(state["evals"] == 2 for state in bad["child_resolved_at_most_once"])


def test_spawn_cache_model_as_written_is_clean() -> None:
    """The atomic get → compile → store keeps ``compiles <= 1`` in every state."""
    assert _violations(_load("spawn_cache_fixed")) == {}


def test_spawn_cache_buggy_model_still_produces_its_violation() -> None:
    """An await between the cache get and the store must stay refutable."""
    bad = _violations(_load("spawn_cache_buggy"))
    assert "one_compile_per_unique_text" in bad, "the bug model stopped demonstrating the bug"
    assert any(state["compiles"] == 2 for state in bad["one_compile_per_unique_text"])
