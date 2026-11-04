"""The Engine environment `screamingface up` starts the Engine from (OME-1620 / OME-1626).

Think of the local stack as three servers that used to share one kitchen. The Engine's 87
imported boards need an ingredient — `inspect-ai` — that cannot sit on the same shelf as the
Gateway's `litellm` pin, so a `pip install screamingface[runtime]` Engine served medxpert alone.
This module gives the Engine its own kitchen: an interpreter the supervisor is pointed at and
starts as a CHILD PROCESS, with the datasets prepared by that interpreter too. Four decisions,
each one function:

1. **Which interpreter** — `resolve_engine_python`: the `--engine-python` flag, else
   `SCREAMINGFACE_ENGINE_PYTHON`, else (in a checkout) the Engine app's own `.venv`, else None,
   which means "no Engine environment: run the Engine in-process as before".
2. **What it can serve** — `engine_bundle_ids` asks the Engine's own preparer
   (`-m screamingface_engine.benchmarks.prepare --list-bundles`); the supervisor keeps no board
   list of its own any more.
3. **Is it full** — `require_full_engine` refuses a medxpert-only environment with the exact
   command that fixes it, because a half-stocked Engine that boots healthy and refuses every
   imported board at run time is the silent failure this stack exists to end.
4. **How to run it** — `serve_command` / `prepare_command` are the argv the Engine documents;
   `bundle_status` reads the Engine's completion marker (cases.json, written LAST by every
   preparer since OME-1790).

Worked example: a dev runs `screamingface up` from the monorepo after `uv sync --extra
benchmarks` in `apps/screamingface-engine`. Stage 1 finds that `.venv`; stage 2 lists 88
bundles; stage 3 passes; the supervisor starts `…/.venv/bin/python -m screamingface_engine.cli
serve --local --port 9108` as a child and `screamingface prepare ifeval` runs that same
interpreter's preparer with `--root ~/.screamingface/benchmark-assets --bundle ifeval`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from screamingface._runtime.source import MODE_CHECKOUT, RuntimeSource

# INVARIANT: one spelling of the variable — `_config` reads it, `up` prints it, docs name it.
ENGINE_PYTHON_ENV = "SCREAMINGFACE_ENGINE_PYTHON"

# WHY this path: it is where `uv sync` in the Engine app puts its interpreter, and the venv
# `just local-stack-notebooks` has always served the full Engine from.
_CHECKOUT_ENGINE_APP = Path("apps") / "screamingface-engine"
_VENV_PYTHON = (
    Path(".venv") / "Scripts" / "python.exe"
    if sys.platform == "win32"
    else Path(".venv") / "bin" / "python"
)

# WHY: the Engine's single hand-built board. An environment whose preparer lists nothing beyond
# it has the Engine but not the inspect plugin's dependencies — the one thing worth refusing.
_HAND_BUILT_BUNDLES = frozenset({"medxpert"})

# WHY 15: enough stderr to carry the failing import and its traceback into the error.
_CHILD_ERROR_TAIL_LINES = 15
# WHY 120 s: listing bundles imports the inspect plugin (87 boards); measured well under a
# minute, and a hung interpreter must not hang `up` forever.
_LIST_TIMEOUT_SECONDS = 120.0

type RunCommand = Callable[..., subprocess.CompletedProcess[str]]


def resolve_engine_python(
    explicit: Path | None, environment: Mapping[str, str], source: RuntimeSource
) -> Path | None:
    """Stage 1 — the interpreter to start the Engine from, or None for the in-process Engine.

    Precedence: the flag, then `SCREAMINGFACE_ENGINE_PYTHON`, then a checkout's Engine venv.
    A path that was NAMED (flag or variable) but is not a file is refused by name: silently
    falling back to the in-process Engine would serve one board behind a setting that promised
    all of them.
    """

    named: Path | None = explicit
    if named is None:
        exported = environment.get(ENGINE_PYTHON_ENV, "").strip()
        named = Path(exported) if exported else None
    if named is not None:
        # INVARIANT: never `resolve()` an interpreter path. A venv's `bin/python` is a symlink
        # to the base interpreter, and following it lands OUTSIDE the venv — an interpreter
        # with none of the Engine's packages (found by the first real boot, 2026-11-04).
        candidate = named.expanduser().absolute()
        if not candidate.is_file():
            raise RuntimeError(
                f"Engine interpreter not found: {candidate} "
                f"(named by --engine-python or {ENGINE_PYTHON_ENV})"
            )
        return candidate
    if source.mode == MODE_CHECKOUT and source.root is not None:
        default = (source.root / _CHECKOUT_ENGINE_APP / _VENV_PYTHON).absolute()
        if default.is_file():
            return default
    return None


def engine_bundle_ids(
    python: Path, environment: Mapping[str, str], *, run: RunCommand | None = None
) -> tuple[str, ...]:
    """Stage 2 — every asset bundle the Engine at `python` can prepare and serve, in its order.

    Asks the Engine's own preparer, so this list is exactly what `/v1/benchmarks` will publish
    once the child is up. A non-zero exit becomes one error carrying the interpreter, the last
    stderr lines and the fix, because the usual cause is an environment missing a package.
    """

    # WHY resolved at call time: a test may replace `subprocess.run` on this module.
    run_command: RunCommand = run if run is not None else subprocess.run
    command: list[str] = [
        str(python),
        "-m",
        "screamingface_engine.benchmarks.prepare",
        "--list-bundles",
    ]
    try:
        completed = run_command(
            command,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            timeout=_LIST_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"could not run the Engine at {python}: {exc}") from None
    if completed.returncode != 0:
        tail: str = "\n".join(completed.stderr.strip().splitlines()[-_CHILD_ERROR_TAIL_LINES:])
        raise RuntimeError(
            f"the Engine at {python} could not list its benchmarks (exit {completed.returncode}):\n"
            f"{tail}\nInstall the Engine with its benchmarks extra into that environment."
        )
    ids: tuple[str, ...] = tuple(
        line.strip() for line in completed.stdout.splitlines() if line.strip()
    )
    if not ids:
        raise RuntimeError(f"the Engine at {python} lists no benchmarks")
    return ids


def require_full_engine(python: Path, bundle_ids: tuple[str, ...], source: RuntimeSource) -> None:
    """Stage 3 — refuse an Engine environment that serves only the hand-built board.

    INVARIANT: an Engine env without the inspect extra fails `up`, never serves medxpert alone.
    The message carries the one command that fixes it for where the env came from.
    """

    if set(bundle_ids) - _HAND_BUILT_BUNDLES:
        return
    if source.mode == MODE_CHECKOUT:
        fix = (
            f"run `uv sync --extra benchmarks` in {_CHECKOUT_ENGINE_APP} (the Engine's "
            "benchmarks extra carries the inspect plugin's dependencies)"
        )
    else:
        fix = "install `screamingface-engine[benchmarks]` into it"
    raise RuntimeError(
        f"the Engine environment at {python} serves only {', '.join(sorted(bundle_ids))}: it lacks "
        f"the inspect extra; {fix}"
    )


# WHY `-c` and not `-m screamingface_engine.cli`: that module has no `__main__` guard (its
# entry is the `screamingface-engine` console script), so `-m` imports it and exits 0 at once —
# found by the first real boot, 2026-11-04. `-c` leaves `serve --local …` in sys.argv[1:] for
# argparse, and needs no console script on PATH.
_ENGINE_CLI_ENTRY = "from screamingface_engine.cli import main; main()"


def serve_command(python: Path, port: int) -> list[str]:
    """Stage 4 — the argv that starts the Engine's local mode on the stack's Engine port."""

    return [str(python), "-c", _ENGINE_CLI_ENTRY, "serve", "--local", "--port", str(port)]


def prepare_command(python: Path, assets_root: Path, bundle: str) -> list[str]:
    """Stage 4 — the argv that prepares one bundle into the stack's datasets folder."""

    return [
        str(python),
        "-m",
        "screamingface_engine.benchmarks.prepare",
        "--root",
        str(assets_root),
        "--bundle",
        bundle,
    ]


def bundle_status(assets_root: Path, bundle: str) -> str:
    """`prepared` when the bundle's cases.json parses to a non-empty list; else `incomplete`
    for a folder that exists, `missing` for none.

    WHY cases.json alone (OME-1790): every Engine preparer writes it LAST, so a parseable,
    non-empty one means the bundle finished; anything else is debris from a run that died, and
    the preparer refuses to write over it — `prepare --force` clears it first.
    """

    folder: Path = assets_root / bundle
    if not folder.exists():
        return "missing"
    try:
        cases: object = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cases = None
    finished: bool = isinstance(cases, list) and bool(cases)
    return "prepared" if finished else "incomplete"


def describe(python: Path | None) -> str:
    """One line for the boot log and the ready banner."""

    return "in-process" if python is None else str(python)


__all__ = [
    "ENGINE_PYTHON_ENV",
    "bundle_status",
    "describe",
    "engine_bundle_ids",
    "prepare_command",
    "require_full_engine",
    "resolve_engine_python",
    "serve_command",
]
