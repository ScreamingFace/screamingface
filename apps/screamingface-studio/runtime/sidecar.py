"""PyInstaller entry point for the packaged ScreamingFace runtime CLI."""

from __future__ import annotations

import multiprocessing
import sys

from screamingface._runtime.cli import main


def _runtime_arguments(arguments: list[str]) -> list[str]:
    """Translate the frozen Scoreboard child marker into the shared private command."""
    try:
        child_marker = arguments.index("--scoreboard-child")
    except ValueError:
        return arguments
    return [*arguments[:child_marker], "_scoreboard", *arguments[child_marker + 1 :]]


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main(_runtime_arguments(sys.argv[1:]))
