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

import contextlib
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from functools import cache
from importlib.resources import files
from pathlib import Path

from screamingface._runtime.engine_lock import (
    ENGINE_APP,
    REQUIREMENTS_NAME,
    export_engine_requirements,
)
from screamingface._runtime.source import MODE_CHECKOUT, RuntimeSource

# INVARIANT: one spelling of the variable — `_config` reads it, `up` prints it, docs name it.
ENGINE_PYTHON_ENV = "SCREAMINGFACE_ENGINE_PYTHON"

# WHY this path: it is where `uv sync` in the Engine app puts its interpreter, and the venv
# `just local-stack-notebooks` has always served the full Engine from.
_CHECKOUT_ENGINE_APP = Path("apps") / "screamingface-engine"
# The interpreter inside any venv folder, and inside the Engine app's `.venv` in particular.
_INTERPRETER_IN_VENV = (
    Path("Scripts") / "python.exe" if sys.platform == "win32" else Path("bin") / "python"
)
_VENV_PYTHON = Path(".venv") / _INTERPRETER_IN_VENV

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
    explicit: Path | None,
    environment: Mapping[str, str],
    source: RuntimeSource,
    *,
    data_dir: Path | None = None,
) -> Path | None:
    """Stage 1 — the interpreter to start the Engine from, or None for the in-process Engine.

    Precedence: the flag, then `SCREAMINGFACE_ENGINE_PYTHON`, then a checkout's Engine venv,
    then an environment `up` built earlier under `data_dir` (`ensure_engine_environment`).
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
    chosen: Path | None = None
    default: Path | None = checkout_engine_venv(source)
    if default is not None and default.is_file():
        chosen = default
    if chosen is None and data_dir is not None:
        editable_root = source.root if source.mode == MODE_CHECKOUT else None
        chosen = existing_engine_environment(data_dir, editable_root=editable_root)
    return chosen


def checkout_engine_venv(source: RuntimeSource) -> Path | None:
    """The Engine app's own venv interpreter in this checkout, whether or not it exists.

    One function so the test suite can hide the developer's REAL Engine venv (conftest) the
    way it hides their real data dir: a unit test must not depend on, or spawn, it.
    """

    if source.mode != MODE_CHECKOUT or source.root is None:
        return None
    return (source.root / _CHECKOUT_ENGINE_APP / _VENV_PYTHON).absolute()


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


# --- building the environment (pip users; OME-1620) ---------------------------------------------

#: Under the data dir: `engine-env/<key>/` holds one built environment; other keys are removed.
ENGINE_ENV_DIRNAME = "engine-env"
#: Written LAST into a built environment, naming its key. No marker, no environment.
READY_MARKER = ".ready"
# WHY 16 hex chars: enough to never collide across the handful of worlds one machine sees.
_KEY_LENGTH = 16
# WHY the figure: the Engine venv with the benchmarks extra measured 658 MB (2026-11-04).
_ENVIRONMENT_SIZE_HINT = "about 700 MB"
#: Under `engine-env/`: held while one `up` builds, so a second `up` waits and then reuses.
_BUILD_LOCK = ".build.lock"
# The three installer steps, in order, as the progress lines name them.
_STEP_LABELS = (
    "creating the venv",
    "installing the pinned packages",
    "installing url4 and the Engine",
)
# WHY 30 min: a cold pip install of the pinned world on a slow link; uv finishes in under a
# minute. A hung installer must not hang `up` forever.
_INSTALL_TIMEOUT_SECONDS = 1800.0


def _vendored_requirements() -> Path | None:
    """The pins a release wheel carries (exported from the Engine's lock at build), or None."""

    shipped = Path(str(files("screamingface._runtime.resources") / REQUIREMENTS_NAME))
    return shipped if shipped.is_file() else None


@cache
def _exported_requirements(engine_app: Path) -> str:
    """The pins exported from a checkout's live Engine lock, once per process."""

    return export_engine_requirements(engine_app)


def _requirements_text() -> str:
    """The Engine's pinned `benchmarks` world: the wheel's copy, else the checkout's lock.

    INVARIANT: both come from `apps/screamingface-engine/uv.lock`, the lock the deployed Engine
    image is built from, so there is no committed copy that could go stale.
    """

    shipped: Path | None = _vendored_requirements()
    if shipped is not None:
        return shipped.read_text(encoding="utf-8")
    checkout_engine_app: Path = Path(__file__).resolve().parents[5] / ENGINE_APP
    if not (checkout_engine_app / "uv.lock").is_file():
        raise FileNotFoundError(
            "the Engine's pinned packages were not found: neither this install's "
            f"{REQUIREMENTS_NAME} nor a checkout's {ENGINE_APP / 'uv.lock'}"
        )
    return _exported_requirements(checkout_engine_app)


# WHY a checkout fallback, like `config.bundled_runner_config`: an editable install ships no
# `engine_dist/` (the project files would be frozen copies), so the key and the assembly read
# the live files of the surrounding checkout instead. Same depth as config.py: this file is
# <root>/packages/screamingface/src/screamingface/_runtime/engine_env.py.
_CHECKOUT_PROJECT_DIRS: dict[str, Path] = {
    "screamingface-engine": Path("apps") / "screamingface-engine",
    "url4": Path("packages") / "url4",
}


def _project_file(project: str, name: str) -> Path:
    """One project file the wheel carries under `engine_dist/<project>/`, or the checkout's."""

    vendored = Path(str(files("screamingface._runtime") / "engine_dist" / project / name))
    if vendored.is_file():
        return vendored
    checkout = Path(__file__).resolve().parents[5] / _CHECKOUT_PROJECT_DIRS[project] / name
    if checkout.is_file():
        return checkout
    raise FileNotFoundError(f"project file not found for {project}: {name}")


def _vendored_package(name: str) -> Path:
    """Where the installed SDK carries package `name`'s sources (its top-level vendored copy)."""

    spec = importlib.util.find_spec(name)
    locations = list(spec.submodule_search_locations or ()) if spec is not None else []
    if not locations:
        raise RuntimeError(f"the installed screamingface carries no copy of {name}")
    return Path(locations[0])


def environment_key(*, editable_root: Path | None = None) -> str:
    """The identity of the environment `up` would build now: its pins, project files, Python,
    and — for a checkout — the root whose live code it installs editable.

    INVARIANT: any change to what goes into the environment changes the key — an environment
    built on other pins would serve boards whose revision no longer matches the deployed
    Engine's, and must never be started. Two checkouts never share one either.
    """

    digest = hashlib.sha256()
    digest.update(_requirements_text().encode("utf-8"))
    for project in ("screamingface-engine", "url4"):
        digest.update(_project_file(project, "pyproject.toml").read_bytes())
    digest.update(f"python{sys.version_info.major}.{sys.version_info.minor}".encode())
    if editable_root is not None:
        digest.update(f"editable:{editable_root.resolve()}".encode())
    return digest.hexdigest()[:_KEY_LENGTH]


def existing_engine_environment(
    data_dir: Path, *, editable_root: Path | None = None
) -> Path | None:
    """The interpreter of an environment `up` already built for the current key, or None.

    INVARIANT: never raises. This LOOKUP runs on every `up`, `status` and `doctor`; an install
    with nothing to compute a key from (a frozen Studio sidecar, or one with neither
    `engine_dist/` nor a checkout) has no built environment, and must say so rather than crash
    at config time. Only a BUILD may raise.
    """

    key: str | None = None
    if not getattr(sys, "frozen", False):
        with contextlib.suppress(OSError, RuntimeError):
            key = environment_key(editable_root=editable_root)
    if key is None:
        return None
    target: Path = data_dir / ENGINE_ENV_DIRNAME / key
    python: Path = target / _INTERPRETER_IN_VENV
    ready: bool = (target / READY_MARKER).is_file() and python.is_file()
    return python if ready else None


def ensure_engine_environment(
    data_dir: Path,
    *,
    environ: Mapping[str, str],
    run: RunCommand | None = None,
    which: Callable[[str], str | None] = shutil.which,
    progress: Callable[[str], None] = print,
    editable_root: Path | None = None,
) -> Path:
    """Build the Engine environment under `data_dir` unless a ready one exists; return its python.

    With `editable_root` (a checkout), stage 3 is skipped and stage 4 installs the checkout's
    live `packages/url4` and `apps/screamingface-engine` EDITABLE instead of the wheel's
    copies: edits are served without a rebuild, and the dev's own venv is never touched.

    Think of it as stocking the Engine's own kitchen once. Stages, in order:

    1. A ready environment for the current key → return it, run nothing.
    2. Remove every other key's folder (a pin bump must not leave the old 700 MB behind) and
       any half-built folder for this key (no marker means it was never finished).
    3. Assemble the Engine and url4 projects in a temporary folder from the sources the wheel
       carries, so pip/uv can build them — entry points included, which is what makes the
       Engine find its inspect plugin.
    4. Create the venv on THIS interpreter, install the pinned world, then the two projects
       with no dependency resolution of their own: every version comes from the pins. uv when
       it is on PATH (seconds), else `python -m venv` and pip (minutes).
    5. Write the ready marker LAST, naming the key.

    A failing step raises with its command and the last lines it printed, and leaves no folder
    behind, so the next `up` starts clean.
    """

    existing: Path | None = existing_engine_environment(data_dir, editable_root=editable_root)
    if existing is not None:
        return existing
    run_command: RunCommand = run if run is not None else subprocess.run
    root: Path = data_dir / ENGINE_ENV_DIRNAME
    key: str = environment_key(editable_root=editable_root)
    root.mkdir(parents=True, exist_ok=True)
    with _build_lock(root):
        # Stage 1 again, under the lock: a second `up` that waited here reuses what the
        # first one built instead of deleting it and starting over.
        existing = existing_engine_environment(data_dir, editable_root=editable_root)
        if existing is not None:
            return existing
        return _build(
            root,
            key,
            environ=environ,
            run=run_command,
            which=which,
            progress=progress,
            editable_root=editable_root,
        )


@contextlib.contextmanager
def _build_lock(root: Path) -> Iterator[None]:
    """Hold an exclusive lock on `root/.build.lock` for one build (no-op where fcntl is absent)."""

    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows: one `up` at a time, documented
        yield
        return
    with (root / _BUILD_LOCK).open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _build(
    root: Path,
    key: str,
    *,
    environ: Mapping[str, str],
    run: RunCommand,
    which: Callable[[str], str | None],
    progress: Callable[[str], None],
    editable_root: Path | None,
) -> Path:
    """Stages 2-5 of `ensure_engine_environment`, run under the build lock."""

    run_command: RunCommand = run
    # Stage 2 — one environment per data dir: other keys and half-built folders go.
    for folder in root.iterdir():
        if folder.is_dir():
            shutil.rmtree(folder)
    target: Path = root / key
    python: Path = target / _INTERPRETER_IN_VENV
    uv: str | None = which("uv")
    progress(
        f"building the Engine environment in {root} ({_ENVIRONMENT_SIZE_HINT}; "
        f"{'under a minute with uv' if uv else 'a few minutes with pip'}"
        f"{'; live code from ' + str(editable_root) if editable_root else ''})"
    )
    with tempfile.TemporaryDirectory(prefix="screamingface-engine-") as scratch:
        # Stage 3 — the projects to install (the wheel's copies, or the checkout's live
        # trees) and the pins.
        if editable_root is None:
            projects: tuple[Path, ...] = _assemble_projects(Path(scratch))
        else:
            projects = (
                editable_root / _CHECKOUT_PROJECT_DIRS["url4"],
                editable_root / _CHECKOUT_PROJECT_DIRS["screamingface-engine"],
            )
        requirements: Path = Path(scratch) / REQUIREMENTS_NAME
        requirements.write_text(_requirements_text(), encoding="utf-8")
        # Stage 4 — the installer sequence; a failed step removes the target and raises.
        commands = _install_commands(
            target,
            python,
            uv=uv,
            requirements=requirements,
            projects=projects,
            editable=editable_root is not None,
        )
        _run_installer(commands, target, environ=environ, run=run_command, progress=progress)
    # Stage 5 — the marker, last. (The venv step created `target`; `mkdir` only keeps an
    # installer that is replaced in tests from failing here.)
    target.mkdir(parents=True, exist_ok=True)
    (target / READY_MARKER).write_text(key, encoding="utf-8")
    return python


def _run_installer(
    commands: list[list[str]],
    target: Path,
    *,
    environ: Mapping[str, str],
    run: RunCommand,
    progress: Callable[[str], None],
) -> None:
    """Run the installer commands in order, saying which step it is on; on any failure remove
    `target` and raise, naming the command and its last lines, so the next `up` starts clean."""

    for step, (label, command) in enumerate(zip(_STEP_LABELS, commands, strict=True), 1):
        progress(f"  {step}/{len(commands)} {label}")
        try:
            completed = run(
                command,
                env=dict(environ),
                capture_output=True,
                text=True,
                check=False,
                timeout=_INSTALL_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            shutil.rmtree(target, ignore_errors=True)
            raise RuntimeError(
                f"building the Engine environment failed at `{' '.join(command)}`: {exc}"
            ) from None
        if completed.returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
            tail: str = "\n".join(
                (completed.stderr or completed.stdout)
                .strip()
                .splitlines()[-_CHILD_ERROR_TAIL_LINES:]
            )
            raise RuntimeError(
                f"building the Engine environment failed at `{' '.join(command)}` "
                f"(exit {completed.returncode}):\n{tail}"
            )


def _install_commands(
    target: Path,
    python: Path,
    *,
    uv: str | None,
    requirements: Path,
    projects: tuple[Path, ...],
    editable: bool = False,
) -> list[list[str]]:
    """The three installer commands, for uv or for venv+pip; identical in what they install."""

    project_args: list[str] = []
    for project in projects:
        if editable:
            project_args.append("-e")
        project_args.append(str(project))
    if uv is not None:
        return [
            # WHY `--python sys.executable`: the same interpreter the SDK runs on, never a
            # different one uv happens to prefer.
            [uv, "venv", "--python", sys.executable, str(target)],
            [uv, "pip", "install", "--python", str(python), "-r", str(requirements)],
            [uv, "pip", "install", "--python", str(python), "--no-deps", *project_args],
        ]
    return [
        [sys.executable, "-m", "venv", str(target)],
        [str(python), "-m", "pip", "install", "-r", str(requirements)],
        [str(python), "-m", "pip", "install", "--no-deps", *project_args],
    ]


def _assemble_projects(scratch: Path) -> tuple[Path, Path]:
    """Lay out url4 and the Engine as installable projects from the wheel's copies.

    Each gets its project file beside a `src/<package>` tree, which is the layout both
    `pyproject.toml`s declare — so hatchling builds them exactly as from the monorepo.
    """

    url4_project: Path = scratch / "url4"
    url4_project.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(_project_file("url4", name), url4_project / name)
    _copy_package("url4", url4_project / "src" / "url4")
    engine_project: Path = scratch / "screamingface-engine"
    engine_project.mkdir()
    shutil.copy2(
        _project_file("screamingface-engine", "pyproject.toml"), engine_project / "pyproject.toml"
    )
    for name in ("screamingface_engine", "screamingface_engine_inspect"):
        _copy_package(name, engine_project / "src" / name)
    return url4_project, engine_project


def _copy_package(name: str, destination: Path) -> None:
    shutil.copytree(
        _vendored_package(name), destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )


def environment_for(
    data_dir: Path, source: RuntimeSource, environ: Mapping[str, str]
) -> Path | None:
    """Build (or reuse) the Engine environment this install needs; None where that is not the job.

    A pip install builds from the wheel's copies; a checkout builds with its live code
    installed editable (nothing to run by hand, the dev's venv untouched). A frozen app
    (Studio's sidecar) cannot create a venv at all and keeps the in-process Engine — its own
    Engine environment is a later ticket, through `SCREAMINGFACE_ENGINE_PYTHON`.
    """

    if getattr(sys, "frozen", False):
        return None
    editable_root: Path | None = source.root if source.mode == MODE_CHECKOUT else None
    return ensure_engine_environment(data_dir, environ=environ, editable_root=editable_root)


def describe(python: Path | None) -> str:
    """One line for the boot log and the ready banner."""

    return "in-process" if python is None else str(python)


__all__ = [
    "ENGINE_ENV_DIRNAME",
    "ENGINE_PYTHON_ENV",
    "READY_MARKER",
    "bundle_status",
    "checkout_engine_venv",
    "describe",
    "engine_bundle_ids",
    "ensure_engine_environment",
    "environment_for",
    "environment_key",
    "existing_engine_environment",
    "prepare_command",
    "require_full_engine",
    "resolve_engine_python",
    "serve_command",
]
