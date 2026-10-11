"""Run one ``[commands]`` subprocess for ``url4 serve`` (doctrine N4).

The subprocess lifetime is its own reason to change: what a timed-out or cancelled
request leaves behind (processes, pipes, late side effects). :mod:`url4.cli._serve`
decides WHAT runs; this module owns that nothing outlives the request.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from url4.core.errors import ResolutionError


async def run_command(command: list[str], stdin_text: str, timeout: float) -> str:
    """Run one argv to completion and return its stdout (stdout is the result).

    # CONTRACT: a timeout raises a NON-permanent :class:`~url4.core.errors.ResolutionError`,
    # so a `;retry=N` source retries it. On every other exit path (timeout, cancellation,
    # any error) the command and every descendant are killed, its pipes are drained and
    # closed, and the child is reaped before this returns. The engine cannot tell "did not
    # run" from "ran but the answer was lost", so commands MUST be idempotent.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise ResolutionError(f"command {command[0]!r} failed to start: {exc}") from exc
    completed = False
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin_text.encode()), timeout)
        completed = True
    except TimeoutError:
        raise ResolutionError(f"command {command[0]!r} timed out after {timeout}s") from None
    finally:
        # WHY: cancellation (the request deadline) skips the TimeoutError arm, so the
        # cleanup lives here. shield: the drain finishes even while this task is cancelled.
        if not completed:
            _kill_tree(proc)
            await asyncio.shield(proc.communicate())
    if proc.returncode != 0:
        raise ResolutionError(
            f"command {command[0]!r} exited {proc.returncode}: "
            f"{err.decode(errors='replace')[:500].strip()}"
        )
    # errors='replace': a command that emits non-UTF-8 bytes must not escape the
    # handler's ResolutionError contract as a raw UnicodeDecodeError (→ bare 500).
    return out.decode(errors="replace")


def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the command's process group, so the pipe drain can reach end-of-file.

    # WHY the group, not the child: a descendant that inherited stdout (`sh -c 'x & y'`)
    # holds the pipe open and would keep acting after the 504. The command leads its own
    # session (`start_new_session`), so its group is exactly the command's tree. A
    # descendant that calls setsid itself escapes the group; that is the command's choice.
    """
    killpg = getattr(os, "killpg", None)  # POSIX only; elsewhere kill the child alone
    with contextlib.suppress(ProcessLookupError):
        if killpg is None:
            proc.kill()
        else:
            killpg(proc.pid, signal.SIGKILL)
