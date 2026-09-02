#!/usr/bin/env python3
"""LAYERING gate for apps/screamingface-engine.

One image ships two modes, and the whole point of that shape is a rule about what may reach what:

    url4.streaming              packages/url4   CONCEPTS ONLY — the wire protocol and the abstract
        ^          ^                            classes over it. No broker, no framework.
        |          |
    control plane   run mode                    Every concrete implementation, in the half that
    (serve)         (run)                       runs it — and the two halves stay disjoint.
        ^
        |
    worker (OME-1089)                           The third mode: claims runs from the queue and
                                                forks the run as a child process. It may import
                                                the serving half and `runner_queue`; it must
                                                import NOTHING from the run half.

  Control plane: app · rest · ws · auth · catalog · connections · config · metrics · ops · reaper
                 schemas · adapters.k8s · adapters.factory  (FastAPI, uvicorn, the k8s client)
  Run mode:      runner.executor (the url4 engine) · runner.connector · runner.main
  Worker:        worker (the claim loop, the supervisor, the exec wrapper)

  Shared leaves, importable by BOTH: job_env · subjects · adapters.jetstream · world_config

WHY this rule outlived the package split it was born in: it used to be proved structurally — the
two halves were separate distributions with separate images, so a cross-import could not even be
installed. They are one distribution now, one venv, one image. Nothing at runtime stops the run
mode from importing FastAPI or the kubernetes client, and an accidental import type-checks, tests
green, and erodes the design silently. This gate is what replaces the structure that used to
prove it.

What it buys concretely: a Kubernetes Job's cold start stays the engine + httpx + nats-py, which
is what the separate slim runner image used to guarantee by construction. The serving half
likewise never gains the ability to evaluate an expression in-process.

SCOPE NOTE: the wire contract lives inside the url4 engine distribution (`url4.streaming`), so
importing it loads the engine as well. That much is unenforceable by construction; what is
enforced is the split between the two halves of `screamingface_engine`.

Run:  python3 .claude/scripts/check_layering.py
Exit: 0 clean · 1 a rule was violated · 2 structural error (the source tree is missing).
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "apps/screamingface-engine/src/screamingface_engine"

# Submodules of `screamingface_engine` that belong to each half. Anything not named in either — `job_env`,
# `subjects`, `adapters.jetstream`, `testing` — is a shared leaf both halves may import.
CONTROL_PLANE = {
    "app",
    "auth",
    "catalog",
    "cli",
    "connections",
    "config",
    "local",
    "metrics",
    "ops",
    # WHY named here rather than left unlisted (OME-890): an unlisted top-level module is a
    # SHARED LEAF by this gate's own definition, importable by both halves — which would let a
    # Runner Job import the control plane's orphan reaper. It watches WS subscriber counts and
    # calls the job runner from the serving process; it belongs to the control plane.
    "reaper",
    "rest",
    "schemas",
    "ws",
    "adapters.k8s",
    "adapters.factory",
}
RUN_MODE = {"runner"}
WORKER_MODE = {"worker"}

# (subtree under screamingface_engine/, forbidden screamingface_engine submodules, why)
RULES: list[tuple[str, set[str], str]] = [
    (
        "runner",
        CONTROL_PLANE,
        "the run mode is the data plane; a Job must not load the serving half (FastAPI, uvicorn, "
        "the kubernetes client) it will never call",
    ),
    (
        "",  # every control-plane module, listed below
        RUN_MODE,
        "the control plane schedules runs and reads their log over NATS; it never evaluates an "
        "expression in-process, so it must not reach into the engine-bearing half",
    ),
    (
        "",  # every control-plane module, listed below
        WORKER_MODE,
        "the control plane never spawns runs itself — only the worker does, so it must not "
        "reach into the worker's subprocess-spawning/RLIMIT_AS-bearing half; the dependency "
        "arrow is one-way (worker → serving half), and this rule checks the direction the "
        "other three forgot",
    ),
    (
        "worker",
        RUN_MODE,
        "the worker spawns the run as a child process; it never imports it — the run half stays "
        "a separate crash domain, and the worker's import graph stays the serving half's plus "
        "the queue",
    ),
]

_EXEMPT = {
    # WHY: `cli` is the composition root for BOTH modes — dispatching to them is its entire job.
    # It imports each lazily, inside the branch that runs it, so neither mode pays for the other.
    "cli.py",
    # WHY: `local` FUSES both modes on purpose — one process that serves the control plane AND
    # executes runs on it (`screamingface-engine serve --local`). It is the single declared exception to the
    # disjointness rule, and it is listed in CONTROL_PLANE above so that being exempt is a visible
    # decision rather than an accident of not being scanned. It too imports the run mode lazily,
    # inside `create_local_app`, so a deployed App never pays for the engine.
    "local.py",
}


def _package_of(path: pathlib.Path) -> list[str]:
    """The dotted package a module lives in, as parts: `rest/routes.py` -> [screamingface_engine, rest]."""
    return ["screamingface_engine", *path.relative_to(SRC).parent.parts]


def imported_screamingface_engine_submodules(path: pathlib.Path) -> set[str]:
    """`screamingface_engine.X` / `screamingface_engine.X.Y` names imported by ``path``, as {"X", "X.Y"}.

    Includes function-local imports, which are exactly how a boundary violation likes to hide,
    TYPE_CHECKING-only ones, which are erased at runtime but still describe the boundary, and
    RELATIVE imports, which resolve to the same modules and were previously skipped outright —
    appending `from ..runner.executor import Url4Executor` to a control-plane module passed this
    check cleanly.

    Out of reach by construction: `importlib.import_module(name)` and `__import__` with a computed
    name. A determined violation can still hide there; every ordinary one is caught.
    """
    found: set[str] = set()

    def record(module: str | None) -> None:
        if not module or not module.startswith("screamingface_engine"):
            return
        parts = module.split(".")[1:]  # drop the "screamingface_engine" root
        if parts:
            found.add(parts[0])
            if len(parts) > 1:
                found.add(f"{parts[0]}.{parts[1]}")

    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                record(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                record(node.module)
                # `from screamingface_engine import job_env` — the submodule is the imported NAME, not the
                # module path, so it would otherwise read as a bare `screamingface_engine` import.
                if node.module == "screamingface_engine":
                    for alias in node.names:
                        record(f"screamingface_engine.{alias.name}")
                continue
            # Relative: level 1 is this module's own package, each extra level walks up one.
            package = _package_of(path)
            base = package[: len(package) - (node.level - 1)]
            if not base or base[0] != "screamingface_engine":
                continue
            if node.module:
                record(".".join([*base, node.module]))
            else:
                # `from . import runner` — the submodule is the imported name.
                for alias in node.names:
                    record(".".join([*base, alias.name]))
    return found


def python_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def files_for(subtree: str) -> list[pathlib.Path]:
    """The files a rule applies to: one subtree, or every control-plane module when unnamed."""
    if subtree:
        return python_files(SRC / subtree)
    paths: list[pathlib.Path] = []
    for name in sorted(CONTROL_PLANE):
        target = SRC / name.replace(".", "/")
        if target.is_dir():
            paths.extend(python_files(target))
        elif target.with_suffix(".py").is_file():
            paths.append(target.with_suffix(".py"))
    return paths


def _half_of(path: pathlib.Path) -> str | None:
    """Which half a module belongs to: "control-plane", "run-mode", "worker-mode", or None for a
    shared leaf."""
    parts = path.relative_to(SRC).with_suffix("").parts
    if not parts:
        return None
    top, two = parts[0], ".".join(parts[:2])
    if top in RUN_MODE:
        return "run-mode"
    if top in WORKER_MODE:
        return "worker-mode"
    if top in CONTROL_PLANE or two in CONTROL_PLANE:
        return "control-plane"
    return None


def shared_leaf_files() -> list[pathlib.Path]:
    """Every module belonging to NEITHER half — `job_env`, `subjects`, `adapters.jetstream`,
    `adapters.memory`, `adapters.inprocess`, `testing`.

    These were scanned by no rule at all: rule 1 walks `runner/` and rule 2 walks the named
    control-plane modules, so a cross-half import added to `adapters/memory.py` passed cleanly —
    and because `local` and `testing` import that module, it would have dragged the engine into
    the serving half through a file the gate never opened.
    """
    return [p for p in python_files(SRC) if _half_of(p) is None]


def check_layers() -> list[str]:
    if not SRC.is_dir():
        print(f"ERROR: source tree missing: {SRC}", file=sys.stderr)
        sys.exit(2)
    offenders: list[str] = []
    for subtree, forbidden, why in RULES:
        for path in files_for(subtree):
            if path.name in _EXEMPT:
                continue
            for module in sorted(
                imported_screamingface_engine_submodules(path) & forbidden
            ):
                offenders.append(
                    f"  {path.relative_to(ROOT)}: imports screamingface_engine.{module}\n      {why}"
                )
    # A shared leaf is shared precisely BECAUSE it depends on neither half; one that reaches into
    # either stops being a leaf and silently couples every importer to that half.
    shared_why = (
        "a shared leaf is importable by BOTH halves, so importing either one couples every "
        "module that depends on it to that half — move it into the half that needs it, or lift "
        "what both need into url4.streaming"
    )
    for path in shared_leaf_files():
        if path.name in _EXEMPT:
            continue
        for module in sorted(
            imported_screamingface_engine_submodules(path) & (CONTROL_PLANE | RUN_MODE)
        ):
            offenders.append(
                f"  {path.relative_to(ROOT)}: imports screamingface_engine.{module}\n      {shared_why}"
            )
    return offenders


def main() -> int:
    offenders = check_layers()
    if offenders:
        print("LAYERING VIOLATIONS:")
        print("\n".join(offenders))
        print(
            "\nMoving the code is the fix — never the gate. If it is a concept (a protocol, an "
            "abstract class, or pure logic over them) it belongs in url4.streaming; if BOTH modes "
            "need it and it names this app's own vocabulary, it is a shared leaf beside job_env "
            "and subjects; otherwise it belongs in the half that runs it."
        )
        return 1
    print(
        "LAYERING OK: screamingface_engine.runner, the worker, and the control plane stay "
        "disjoint."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
