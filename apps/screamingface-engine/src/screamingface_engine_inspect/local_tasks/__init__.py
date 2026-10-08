"""Local Tasks — evals WE author in inspect's shape and feed to the same importer (OME-1513).

A local Task is one package under this directory: a dataset loader, a scorer or several, one
``@task``, and (when the paper publishes grading code) a ``vendor/`` copy of it. The importer
turns it into the same two rows an inspect_evals eval gets, and the plugin serves it the same
way. The Benchmark it produces is ours (``origin="screamingface"``).

What is different from an inspect_evals import, and why this module exists: for an import the
marking scheme lives in the pinned ``inspect-evals==<version>`` package, so that pin is part of
the Benchmark revision. For a local Task the marking scheme is OUR source, so its bytes must
be part of the revision too — otherwise the grading rule could change under a published score
(review finding on #1292). :func:`source_digest` is that pin.
"""

from __future__ import annotations

import hashlib
from importlib.util import find_spec
from pathlib import Path

#: The task-reference prefix that marks a row as a local Task.
LOCAL_TASK_PREFIX = "screamingface_engine_inspect.local_tasks."

#: The one task-reference prefix whose source is pinned elsewhere (`inspect-evals==<version>`).
INSPECT_EVALS_PREFIX = "inspect_evals."


def source_digest(package_dir: Path) -> str:
    """sha256 over every ``.py`` file under the Task's package, ``vendor/`` included.

    INVARIANT: only ``.py`` files count — README prose and compiled ``__pycache__`` are not
    the marking scheme — and they are hashed in sorted relative-path order, so the digest is
    the same on every machine and moves on any one-byte edit to the grading rule.
    """

    files: list[Path] = [
        path for path in sorted(package_dir.rglob("*.py")) if "__pycache__" not in path.parts
    ]
    # WHY refuse: sha256 of nothing is a valid-looking digest, so a mislocated package would
    # pin "no source" and the revision would never move when the real source changes.
    if not files:
        raise ValueError(f"no .py files under {package_dir}: nothing to pin as the Task's source")
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(package_dir).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def task_source_pin(task_reference: str) -> tuple[str, ...]:
    """The ``task_source=<digest>`` revision pin for any Task whose source is not inspect_evals'.

    The package hashed is the directory of the module the reference names, so a Task at
    ``local_tasks/musique/musique.py`` pins ``local_tasks/musique/`` whole. Only a reference
    into ``inspect_evals`` gets no pin: that package's version is already a revision input.
    Anything else — a local Task, a Task elsewhere in this plugin, a third-party package — is
    hashed, or refused when it cannot be located (review finding on #1292: an unpinned Task
    could change its grading rule under a published score with no test failing).

    INVARIANT: this runs at Benchmark assembly, on the Engine's import path, so it must NOT
    execute the Task module — a Task imports inspect_ai, which drags a web stack and OpenTelemetry
    into every run (the plugin keeps every inspect import lazy for that reason;
    ``test_importing_the_run_entrypoint_does_not_load_opentelemetry`` is the tripwire).
    ``find_spec`` locates the file without running it.
    """

    if task_reference.startswith(INSPECT_EVALS_PREFIX):
        return ()
    module_name: str = task_reference.partition(":")[0]
    # WHY catch: find_spec raises ModuleNotFoundError when a dotted name's PARENT package is
    # missing and returns None when only the leaf is; both mean "cannot be located".
    try:
        spec = find_spec(module_name)
    except ModuleNotFoundError:
        spec = None
    if spec is None or spec.origin is None:
        raise ValueError(f"Task module {module_name!r} cannot be located to pin its source")
    return (f"task_source={source_digest(Path(spec.origin).parent)}",)


__all__ = ["INSPECT_EVALS_PREFIX", "LOCAL_TASK_PREFIX", "source_digest", "task_source_pin"]
