"""The public SDK surface moves only with a deliberate snapshot update + changelog.

Mental model: a tripwire, not a bug detector. `public_surface_snapshot.json` (next to
this file) is a checked-in photograph of everything a user can import from
`screamingface` — the top-level exports, the signatures of the public callables, the
public methods and fields of the public classes, and the pinned submodule namespaces.
When this test goes red it means "you changed the interface users program against —
write the changelog and tell users", which is exactly requirement R6 of OME-956.

The photograph is taken in three stages:

1. Stage 1 — enumerate: for each pinned module (`screamingface` plus the public
   submodules and `screamingface.report`), walk its `__all__`.
2. Stage 2 — describe: every export becomes one human-readable JSON entry — functions
   render their full `inspect.signature` (parameter names, kinds, defaults, annotations
   as strings), classes list only the members DEFINED inside this package (an MRO walk
   skips everything inherited from `object`/`str`/`Exception`, so stdlib churn cannot
   trip the wire), and PEP 695 type aliases render their value.
3. Stage 3 — compare: the JSON (sorted keys, one entry per line, so PR diffs of
   intended changes are reviewable) is diffed byte-for-byte against the snapshot; a
   mismatch fails with a unified diff plus the exact regeneration command.

Deliberately shallow where refactors are internal: module paths of defining classes,
private helpers, docstrings, and `__all__` ordering are NOT recorded — renaming a
private module or reordering exports stays green. Deliberately deep where users feel
it: renaming/removing/re-signing any public callable, method, property, or field
turns the test red.

Regeneration is an explicit human act, never automatic in CI:

    UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py

which rewrites the snapshot and STILL fails that run (so an update can never be
mistaken for a green build), then passes on the next plain run.
"""

from __future__ import annotations

import difflib
import functools
import importlib
import inspect
import json
import os
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import screamingface as sf
from screamingface import _default_client

SNAPSHOT_PATH = Path(__file__).resolve().parent / "public_surface_snapshot.json"
UPDATE_ENV_VAR = "UPDATE_SURFACE_SNAPSHOT"
REGENERATE_COMMAND = f"{UPDATE_ENV_VAR}=1 uv run pytest tests/test_public_surface.py"

# The pinned namespaces. `screamingface.report` is not re-exported by the top-level
# `__all__` but is the documented home of the result types, so it is pinned by name.
PINNED_MODULES = (
    "screamingface",
    "screamingface.benchmarks",
    "screamingface.connections",
    "screamingface.events",
    "screamingface.leaderboards",
    "screamingface.models",
    "screamingface.report",
)

# Dunders that are part of the surface when this package defines them (a user-visible
# constructor or protocol hook), unlike the rest of the dunder namespace.
SURFACE_DUNDERS = frozenset({"__init__", "__call__", "__enter__", "__exit__"})


def _is_package_module(module_name: str) -> bool:
    """True only for `screamingface` itself and its submodules.

    A bare `startswith("screamingface")` would also match sibling packages like
    `screamingface_engine`, silently pinning (or skipping) their members.
    """

    return module_name == "screamingface" or module_name.startswith("screamingface.")


def _signature_of(obj: Any) -> str:
    """Render a callable's signature with annotations as strings.

    `from __future__ import annotations` keeps every annotation a plain string, so
    `str(inspect.signature(...))` renders source text, not resolved objects. Two leaks
    are guarded against because either would break this test's own invariants:

    - a memory address (`0x...`) in a default value's repr would make the snapshot
      nondeterministic across runs — rejected loudly here rather than committed;
    - an internal module path (`screamingface.<internal>.X`) in an annotation means
      the defining module lacks the future import, so renaming that internal module
      would turn the test red — violating "internal refactors stay green".
    """

    rendered = str(inspect.signature(obj))
    for pattern, problem, remedy in (
        (
            r"\b0x[0-9a-fA-F]+\b",
            "embeds a memory address, which is nondeterministic across runs",
            "give the default a named sentinel with a stable repr",
        ),
        (
            r"\bscreamingface\.\w+\.",
            "embeds an internal module path, so renaming that module would go red",
            "add `from __future__ import annotations` to the module defining it",
        ),
    ):
        if re.search(pattern, rendered):
            raise AssertionError(
                f"unstable signature for {getattr(obj, '__qualname__', obj)!r}: "
                f"{rendered}\nit {problem}; {remedy}."
            )
    return rendered


def _describe_member(cls: type, name: str, raw: Any) -> str:
    """One class member → one snapshot line: its kind, plus a signature if it has one."""

    if isinstance(raw, (property, functools.cached_property)):
        line = "property"
    elif isinstance(raw, classmethod):
        line = f"classmethod {_signature_of(getattr(cls, name))}"
    elif isinstance(raw, staticmethod):
        line = f"staticmethod {_signature_of(raw.__func__)}"
    elif inspect.ismemberdescriptor(raw):
        line = "field"
    elif callable(raw):
        line = f"method {_signature_of(raw)}"
    else:
        line = "attribute"
    return line


def _describe_class(cls: type) -> dict[str, Any]:
    """Describe the package-defined members of a public class.

    The MRO walk finds where each attribute is DEFINED; only definitions living in a
    `screamingface` module are recorded. Example: `Url4(str)` exposes all of `str`'s
    methods, but only the ones this package adds belong to the pinned surface —
    `str.upper` changing between Python versions must not turn CI red.
    """

    members: dict[str, str] = {}
    for name in dir(cls):
        if name.startswith("_") and name not in SURFACE_DUNDERS:
            continue
        defining = next((klass for klass in cls.__mro__ if name in vars(klass)), None)
        if defining is None or not _is_package_module(defining.__module__):
            continue
        members[name] = _describe_member(cls, name, vars(defining)[name])
    description: dict[str, Any] = {"kind": "class", "members": members}
    if issubclass(cls, BaseException):
        # Which `except`/warning-filter clauses catch this class is part of the
        # contract, so EVERY public ancestor is pinned — this package's exception
        # types AND stdlib ones (e.g. `EvaluationWarning` staying a `UserWarning`
        # is what keeps users' warning filters working). Only private package
        # internals and `BaseException`/`object` plumbing are skipped.
        public_bases = [
            klass.__name__
            for klass in cls.__mro__[1:]
            if klass not in (BaseException, object) and not klass.__name__.startswith("_")
        ]
        description["catches_as"] = public_bases
    return description


def _describe_export(obj: Any) -> dict[str, Any]:
    """Describe one `__all__` entry as a human-readable snapshot value."""

    if inspect.ismodule(obj):
        description: dict[str, Any] = {"kind": "module", "module": obj.__name__}
    elif inspect.isclass(obj):
        description = _describe_class(obj)
    elif type(obj).__name__ == "TypeAliasType":  # PEP 695 `type X = ...`
        description = {"kind": "type alias", "value": str(obj.__value__)}
    elif callable(obj):
        description = {"kind": "function", "signature": _signature_of(obj)}
    else:
        description = {"kind": "value", "type": type(obj).__name__}
    return description


def _describe_module(module: ModuleType) -> dict[str, Any]:
    """Describe a pinned module: its export names plus one entry per export.

    `__all__` is snapshotted SORTED — reordering exports changes nothing a user can
    observe, so it must stay green (internal refactors stay green).
    """

    exports: dict[str, Any] = {}
    for name in module.__all__:
        try:
            exported = getattr(module, name)
        except AttributeError:
            raise AssertionError(
                f"{module.__name__}.__all__ names {name!r}, but the module has no such "
                "attribute — `from module import *` would crash for users. Fix the "
                "export before pinning the surface."
            ) from None
        exports[name] = _describe_export(exported)
    return {"__all__": sorted(module.__all__), "exports": exports}


def build_public_surface() -> dict[str, Any]:
    """Stage 1+2 — photograph the live public surface of the installed package."""

    return {name: _describe_module(importlib.import_module(name)) for name in PINNED_MODULES}


def _render(surface: dict[str, Any]) -> str:
    return json.dumps(surface, indent=2, sort_keys=True) + "\n"


def test_public_surface_matches_the_committed_snapshot() -> None:
    """INVARIANT: the public surface moves only with a deliberate snapshot update
    + changelog entry — a red run here is a communication trigger, not a bug.
    """

    current = _render(build_public_surface())

    # Only an explicit opt-in counts — `UPDATE_SURFACE_SNAPSHOT=0` must NOT update.
    if os.environ.get(UPDATE_ENV_VAR, "").strip().lower() in {"1", "true"}:
        SNAPSHOT_PATH.write_text(current)
        pytest.fail(
            f"public surface snapshot regenerated at {SNAPSHOT_PATH.name}.\n"
            "This failure is deliberate so a regeneration run is never mistaken for a\n"
            "green build. Review the snapshot diff, record the interface change in the\n"
            "changelog, commit both, then re-run plainly:\n"
            "    uv run pytest tests/test_public_surface.py",
            pytrace=False,
        )

    if not SNAPSHOT_PATH.exists():
        pytest.fail(
            f"missing public surface snapshot: {SNAPSHOT_PATH}\n"
            f"Generate it deliberately with:\n    {REGENERATE_COMMAND}",
            pytrace=False,
        )

    committed = SNAPSHOT_PATH.read_text()
    if committed != current:
        diff = "".join(
            difflib.unified_diff(
                committed.splitlines(keepends=True),
                current.splitlines(keepends=True),
                fromfile=f"committed {SNAPSHOT_PATH.name}",
                tofile="current public surface",
            )
        )
        pytest.fail(
            "the public SDK surface changed — this is a communication trigger, not a\n"
            "bug: users program against these names and signatures.\n\n"
            f"{diff}\n"
            "If the change is intended: write the changelog entry, then regenerate the\n"
            f"snapshot deliberately with:\n    {REGENERATE_COMMAND}\n"
            "and commit the snapshot together with the changelog. Never regenerate in CI.",
            pytrace=False,
        )


def test_public_v1_surface_has_no_legacy_aliases() -> None:
    """The snapshot pins `__all__`; this guards the names that must stay GONE even as
    plain attributes (legacy plan-era aliases removed from the v1 surface)."""

    for removed in (
        "config",
        "Plan",
        "Candidate",
        "Operation",
        "plan",
        "run",
        # WHY "Benchmark" left this list: OME-724 reintroduces it deliberately as the
        # rich discovery value (spec 2026-08-03-OME-722) — not the legacy plan-era type.
        "Case",
        "StudyReport",
        "Grader",
        "Aggregator",
        "EvaluationPlan",
        "PlannedCandidate",
        "PlannedOperation",
        "CandidateReport",
        "MemberReport",
        "Reducer",
        "reducers",
    ):
        assert not hasattr(sf, removed)


def test_module_evaluate_delegates_to_the_lazy_default_client(monkeypatch: Any) -> None:
    sentinel = object()
    calls: list[tuple[object, str | None, int | None]] = []

    class FakeClient:
        def evaluate(
            self,
            candidates: object,
            *,
            benchmark: str | None = None,
            limit: int | None = None,
            **_: object,
        ) -> object:
            calls.append((candidates, benchmark, limit))
            return sentinel

    monkeypatch.setattr(_default_client, "default_client", lambda: FakeClient())

    candidates = sf.Model("provider/model")
    result = sf.evaluate(candidates, benchmark="draco", limit=1)

    assert result is sentinel
    assert calls == [(candidates, "draco", 1)]

    result = sf.evaluate("(candidate:0.0:'recipe')!'done'", progress=False)

    assert result is sentinel
    assert calls[-1] == ("(candidate:0.0:'recipe')!'done'", None, None)


def test_default_client_is_lazy_and_reads_environment_once(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(_default_client, "_client", None)
    monkeypatch.setenv("SCREAMINGFACE_ENGINE_URL", "https://first.example")

    first = _default_client.default_client()
    monkeypatch.setenv("SCREAMINGFACE_ENGINE_URL", "https://second.example")
    second = _default_client.default_client()

    assert first is second
    assert first.engine_url == "https://first.example"
    first.close()
    monkeypatch.setattr(_default_client, "_client", None)


def test_default_client_lazily_selects_the_hosted_engine_without_an_override(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(_default_client, "_client", None)
    monkeypatch.delenv("SCREAMINGFACE_ENGINE_URL", raising=False)

    client = _default_client.default_client()

    assert client.engine_url == "https://fusion.dev.screamingface.ai"
    client.close()
    monkeypatch.setattr(_default_client, "_client", None)


def test_default_client_can_be_reconfigured_and_closed() -> None:
    _default_client.close()
    first = sf.configure(
        engine_url="https://first.example",
        scoreboard_url="https://first-scoreboard.example",
    )

    second = sf.configure(
        engine_url="https://second.example",
        scoreboard_url="https://second-scoreboard.example",
    )

    assert first.closed is True
    assert second is _default_client.default_client()
    assert second.engine_url == "https://second.example"
    assert second.scoreboard_url == "https://second-scoreboard.example"

    sf.close()

    assert second.closed is True
    assert _default_client._client is None


def test_operation_info_is_a_constructible_public_report_value() -> None:
    operation = sf.OperationInfo(
        id="op_answer",
        kind="model",
        label="answer",
        depends_on=(),
    )

    assert operation.depends_on == ()
    assert not hasattr(sf, "Operation")


def test_the_notebook_extra_stays_lean_enough_for_a_hosted_notebook() -> None:
    """INVARIANT: `screamingface[notebook]` is safe to install inside Colab.

    WHY: the connection panel's ImportError tells users to install this extra, and
    `sf.connect()` is the documented entrypoint. An extra that drags in JupyterLab also
    upgrades ipywidgets out from under Colab's own widget manager, which stops the panel
    rendering at all. Notebook-authoring tooling belongs in the dev dependency group.
    """

    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    extras = tomllib.loads(pyproject.read_text())["project"]["optional-dependencies"]
    names = [
        requirement.split(">=")[0].split("==")[0].strip() for requirement in extras["notebook"]
    ]

    assert names == ["ipywidgets"], names
