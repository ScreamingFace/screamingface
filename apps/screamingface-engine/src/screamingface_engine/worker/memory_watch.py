"""A run's RESIDENT memory, read from ``/proc`` (OME-1607).

WHY resident memory and not the address-space cap alone: the exec wrapper's ``RLIMIT_AS``
bounds VIRTUAL address space, and native libraries reserve address space they never touch —
pyarrow's default pool (mimalloc) reserves a 1 GiB arena on its first allocation, OpenBLAS a
buffer per node CPU. Measured on a `draco-3pass` replay: the child reached its 2 GiB cap with
459 MiB resident. What the pod's cgroup limit counts — and what the chart sizes per slot — is
resident memory, so that is what the worker holds each run to.

WHY the whole process TREE: a run may start processes of its own (a tool, a sandbox); their
memory is the run's, and the cgroup charges it to the pod all the same.

Linux only. Where ``/proc`` is absent (macOS) or the run has already exited, a reading is
``None`` — unknown, never "over budget".
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

PROC = Path("/proc")

#: How often the supervisor reads a run's resident memory. Two seconds is far below the time a
#: run takes to grow by a slot's worth of memory (measured: about 4 MiB/s at the worst), and a
#: tree walk of a runner pod's handful of processes costs well under a millisecond.
MEMORY_POLL_S = 2.0


def _parent_of(stat: bytes) -> int | None:
    """The parent pid in a ``/proc/<pid>/stat`` line.

    WHY bytes, and WHY split at the LAST ``)``: field 2 is the command name in parentheses — it
    may hold spaces and parentheses, and the kernel cuts it at 15 BYTES, which can split a
    multi-byte character, so the line is not always valid UTF-8. Every field after it is plain.
    """
    try:
        return int(stat[stat.rindex(b")") + 2 :].split()[1])
    except (ValueError, IndexError):
        return None


def _rss_bytes(status: Path) -> int | None:
    try:
        for line in status.read_bytes().splitlines():
            if line.startswith(b"VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return 0  # a kernel thread / zombie has no VmRSS line: it holds no user memory


def process_tree_rss_bytes(root_pid: int, proc: Path = PROC) -> int | None:
    """Resident bytes of ``root_pid`` and every process below it, or ``None`` when unknown."""
    root_rss = _rss_bytes(proc / str(root_pid) / "status")
    if root_rss is None:
        return None
    children: dict[int, list[int]] = {}
    try:
        entries = list(proc.iterdir())
    except OSError:
        return None  # an unreadable /proc (too many open files): unknown, never "over"
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            parent = _parent_of((entry / "stat").read_bytes())
        except OSError:
            continue  # exited between the listing and the read
        if parent is not None:
            children.setdefault(parent, []).append(int(entry.name))
    total, pending = root_rss, list(children.get(root_pid, ()))
    while pending:
        pid = pending.pop()
        total += _rss_bytes(proc / str(pid) / "status") or 0
        pending.extend(children.get(pid, ()))
    return total


async def first_reading_over(
    pid: int,
    budget_bytes: int,
    *,
    read: Callable[[int], int | None],
    poll_s: float,
) -> int:
    """Return the first reading of ``pid``'s tree above ``budget_bytes``; never return otherwise.

    An unknown reading — ``None``, or a reader that RAISES — is skipped, not counted as a
    breach: the worker never stops a run on a measurement it could not make.
    """
    while True:
        try:
            reading = await asyncio.to_thread(read, pid)
        except Exception as exc:  # noqa: BLE001 — WHY broad: any failure is "unknown", never "kill"
            logger.debug("resident memory of pid %s unreadable: %s", pid, type(exc).__name__)
            reading = None
        if reading is not None and reading > budget_bytes:
            return reading
        await asyncio.sleep(poll_s)


class RunMemoryGuard:
    """The worker's per-run memory rules (OME-1607): what is watched, and how a breach is named.

    One per worker. It keeps a little state per topic for the life of one supervision — the
    reading that broke the resident budget, and whether the child said `MemoryError` — and the
    supervisor `forget`s the topic when the run ends.
    """

    def __init__(
        self,
        *,
        resident_budget_bytes: int | None,
        address_space_bytes: int,
        read: Callable[[int], int | None] = process_tree_rss_bytes,
        poll_s: float = MEMORY_POLL_S,
    ) -> None:
        self.resident_budget_bytes = resident_budget_bytes
        self.address_space_bytes = address_space_bytes
        self.read = read  # a test seam: read through the attribute at call time
        self.poll_s = poll_s
        self._breaches: dict[str, int] = {}
        self._memory_errors: set[str] = set()

    def watch(self, pid: int | None) -> asyncio.Task[int] | None:
        """A task that ends with the first reading over budget; ``None`` when nothing is watched."""
        if self.resident_budget_bytes is None:
            return None
        if pid is None:
            logger.debug("a child with no pid: its resident memory is not watched")
            return None
        return asyncio.create_task(
            first_reading_over(
                pid,
                self.resident_budget_bytes,
                read=lambda child_pid: self.read(child_pid),
                poll_s=self.poll_s,
            )
        )

    def record_breach(self, topic: str, reading: int) -> None:
        self._breaches[topic] = reading

    def note_stderr(self, topic: str, line: bytes) -> None:
        """Remember that the run's child DIED of `MemoryError` (its address-space cap fired).

        Only the traceback's last line — the exception itself, ``MemoryError`` or
        ``MemoryError: …`` — counts; a log line that merely mentions one is not the run dying.
        """
        stripped = line.strip()
        if stripped == b"MemoryError" or stripped.startswith(b"MemoryError:"):
            self._memory_errors.add(topic)

    def breach_message(self, topic: str) -> str:
        used = self._breaches.get(topic, 0)
        return (
            f"the run used {used} bytes ({used // 2**20} MiB) of resident memory, over its "
            f"per-run budget of {self.resident_budget_bytes} bytes; the budget is "
            "`runnerPool.perRunCharge.memoryLimitMi` (URL4_CLOUD_WORKER_RESIDENT_BUDGET_BYTES)"
        )

    def exit_note(self, topic: str) -> str:
        """What to add to a non-zero exit's message: the address-space cause, when it was one."""
        if topic not in self._memory_errors:
            return ""
        return (
            "; it raised MemoryError at its address-space limit of "
            f"{self.address_space_bytes} bytes (URL4_CLOUD_WORKER_MEMORY_BUDGET_BYTES)"
        )

    def forget(self, topic: str) -> None:
        self._breaches.pop(topic, None)
        self._memory_errors.discard(topic)
