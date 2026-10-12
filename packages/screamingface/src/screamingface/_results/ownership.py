"""Coordinate optional lifecycle metadata shared by local notebook processes."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

_STATES = {"running", "exporting", "rendering"}


def owner_alive(pid: int) -> bool:
    if pid == os.getpid() or os.name != "posix":
        return True  # WHY: Windows os.kill(pid, 0) can terminate the owner.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError):
        pass  # WHY: inaccessible owners are conservatively treated as live.
    return True


@contextmanager
def _coordinated(path: Path) -> Iterator[None]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = path.with_suffix(".json.lock")
    if lock_path.is_symlink():
        raise OSError("Lifecycle lock must not follow a symlink")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(lock_path, flags, 0o600), "r+") as lock:
        if os.name == "posix":
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(lock, fcntl.LOCK_UN)


def _entries(value: dict, name: str) -> list[dict]:
    entries = value.get(name, [])
    if not isinstance(entries, list):
        return []
    return [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("pid"), int)
        and not isinstance(entry["pid"], bool)
        and entry["pid"] > 0
        and isinstance(entry.get("state"), str)
        and entry["state"] in _STATES
    ]


def recorded_owners(value: dict) -> list[tuple[int, str]]:
    return [
        (entry["pid"], entry["state"])
        for name in ("lifecycle_operations", "lifecycle_interruptions")
        for entry in _entries(value, name)
    ]


def _outstanding(value: dict, *, claim_legacy: bool) -> tuple[list[dict], list[dict]]:
    operations = _entries(value, "lifecycle_operations")
    interruptions = _entries(value, "lifecycle_interruptions")
    pid = value.get("owner_pid")
    if (
        "lifecycle_operations" not in value
        and isinstance(pid, int)
        and not isinstance(pid, bool)
        and pid > 0
        and isinstance(value.get("state"), str)
        and value["state"] in _STATES
        and (owner_alive(pid) or not claim_legacy)
    ):
        # WHY: presentation preserves older dead owners. New prepared/recovery work
        # can claim an exited owner, while live owners always remain outstanding.
        operations.append({"pid": pid, "state": value["state"]})
    return operations, interruptions


def update_marker(
    path: Path,
    bootstrap: dict,
    state: str,
    operations: dict[object, str],
    interruption: str | None,
    resolve_interruption: bool,
    write: Callable[[Path, dict], None],
) -> bool:
    # INVARIANT: the lock covers reread, merge and atomic replacement, not just writing.
    with _coordinated(path):
        value = json.loads(path.read_text()) if path.exists() else dict(bootstrap)
        if not isinstance(value, dict) or "owner_pid" not in value:
            return False
        pending, interrupted = _outstanding(
            value, claim_legacy=state == "ready" or "running" in operations.values()
        )
        pid = os.getpid()
        pending = [entry for entry in pending if entry["pid"] != pid]
        if resolve_interruption:
            pending = [entry for entry in pending if owner_alive(entry["pid"])]
            interrupted = []  # WHY: cancelled work has ended, even if its owner is still alive.
        pending.extend({"pid": pid, "state": selected} for selected in operations.values())
        if interruption is not None:
            interrupted = [entry for entry in interrupted if entry["pid"] != pid]
            interrupted.append({"pid": pid, "state": interruption})
        selected = next(reversed(pending or interrupted), {"pid": pid, "state": state})
        value.update(
            state=selected["state"],
            owner_pid=selected["pid"],
            lifecycle_operations=pending,
            lifecycle_interruptions=interrupted,
        )
        write(path, value)
        return True
