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


def source_digest(package_dir: Path) -> str:
    """sha256 over every ``.py`` file under the Task's package, ``vendor/`` included.

    INVARIANT: only ``.py`` files count — README prose and compiled ``__pycache__`` are not
    the marking scheme — and they are hashed in sorted relative-path order, so the digest is
    the same on every machine and moves on any one-byte edit to the grading rule.
    """

    digest = hashlib.sha256()
    for path in sorted(package_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(package_dir).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def task_source_pin(task_reference: str) -> tuple[str, ...]:
    """The ``task_source=<digest>`` revision pin for a local-Task row; empty for an import.

    The package hashed is the directory of the module the reference names, so a Task at
    ``local_tasks/musique/musique.py`` pins ``local_tasks/musique/`` whole.

    INVARIANT: this runs at Benchmark assembly, on the Engine's import path, so it must NOT
    execute the Task module — a Task imports inspect_ai, which drags a web stack and OpenTelemetry
    into every run (the plugin keeps every inspect import lazy for that reason;
    ``test_importing_the_run_entrypoint_does_not_load_opentelemetry`` is the tripwire).
    ``find_spec`` locates the file without running it.
    """

    if not task_reference.startswith(LOCAL_TASK_PREFIX):
        return ()
    module_name: str = task_reference.partition(":")[0]
    spec = find_spec(module_name)
    if spec is None or spec.origin is None:
        raise ValueError(f"local Task module {module_name!r} cannot be located to pin its source")
    return (f"task_source={source_digest(Path(spec.origin).parent)}",)


__all__ = ["LOCAL_TASK_PREFIX", "source_digest", "task_source_pin"]
