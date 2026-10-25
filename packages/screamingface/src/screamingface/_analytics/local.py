"""Atomic per-user consent storage, independent of runtime data directories."""

import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from screamingface._analytics.ports import Choice, Consent


def config_path() -> Path:
    value = os.environ.get("SCREAMINGFACE_ANALYTICS_CONFIG")
    return Path(value).expanduser() if value else Path.home() / ".screamingface/analytics.json"


def _decode(value: object) -> Consent:
    if not isinstance(value, dict) or type(value.get("version")) is not int:
        return Consent()
    if value["version"] != 1:
        return Consent()
    return _decode_choice(value)


def _decode_choice(value: dict) -> Consent:
    if value.get("consent_version") != "1":
        raise ValueError("Unsupported consent version")
    choice = value.get("choice")
    if choice == "declined":
        return Consent("declined")
    identifier = value.get("installation_id")
    if choice != "accepted" or not isinstance(identifier, str):
        return Consent()
    if str(UUID(identifier, version=4)) != identifier:
        raise ValueError("Invalid analytics identifier")
    return Consent("accepted", identifier)


class LocalConsentStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> Consent:
        # INVARIANT: readers see the old or new complete document, never a partial write.
        try:
            if self.path.is_symlink():
                return Consent()
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            with os.fdopen(os.open(self.path, flags), "rb") as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
                    raise ValueError("Invalid analytics preference file")
                return _decode(json.loads(stream.read(4097)))
        except (OSError, ValueError, UnicodeError):
            return Consent()

    def change(self, choice: Choice, *, rotate: bool = False) -> Consent:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._lock():
            previous = self.read()
            if rotate and previous.choice != "accepted":
                return previous
            identifier = None
            if choice == "accepted":
                identifier = str(uuid4()) if rotate else previous.installation_id or str(uuid4())
            state = Consent(choice, identifier)
            self._write(state)
            return state

    @contextmanager
    def _lock(self):
        # Keep the inode stable: unlinking a locked file lets another writer lock
        # a different inode. The OS releases ownership even after a killed writer.
        path = self.path.with_suffix(self.path.suffix + ".lock")
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            deadline = time.monotonic() + 0.25
            while True:
                try:
                    _file_lock(descriptor, acquire=True)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise OSError("Analytics preferences are busy; try again") from None
                    time.sleep(0.01)
            try:
                yield
            finally:
                _file_lock(descriptor, acquire=False)
        finally:
            os.close(descriptor)

    def _write(self, state: Consent) -> None:
        value = {"version": 1, "consent_version": "1", "choice": state.choice}
        if state.installation_id:
            value["installation_id"] = state.installation_id
        descriptor, name = tempfile.mkstemp(dir=self.path.parent, prefix=".analytics-")
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)


def _file_lock(descriptor: int, *, acquire: bool) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1)
        except OSError as error:
            if acquire and error.errno in {13, 36}:
                raise BlockingIOError() from error
            raise
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB if acquire else fcntl.LOCK_UN)
