"""The worker ⇄ warm-child hand-off protocol (uniform executor PRD 03, contracts.md C5).

A warm child starts BEFORE its run is known: it does the per-process work (Python start-up, the
imports, the broker connection, the world config), tells the worker it is READY, and then reads
exactly one run from stdin. The worker writes that run as one RUN_SPEC line, and the child ACKs
it before it runs any of the run's code.

    child → worker, control pipe:  READY {"pid": <int>, "world": "ok" | "error"}\\n
    worker → child, stdin:         {"spec_version": "2", "env": {...}, "io_concurrency": <int>}\\n
    child → worker, control pipe:  ACK\\n

WHY a control pipe and not stdout: stdout and stderr keep their role as the run's log lines,
which the worker forwards; a protocol line mixed into them would be one stray `print` away from
a hung hand-off. The pipe's fd number travels in `CONTROL_FD_ENV`, a per-PROCESS value.

INVARIANT: stdlib only. Both halves import this module — the worker (which must not import the
run path) and the run child (which must not import the serving half) — so it is the one place
the line format lives, and it may pull neither half in.
"""

import json
from dataclasses import dataclass

SPEC_VERSION = "2"
"""The RUN_SPEC major version (erd.md §3). A child refuses any other."""
MAX_SPEC_BYTES = 1024 * 1024
"""The largest RUN_SPEC line a child reads (erd.md §3). A queue message is far smaller."""
CONTROL_FD_ENV = "URL4_CLOUD_CONTROL_FD"
"""The env var naming the control pipe's write end in the child (inherited through the exec)."""
ACK = b"ACK\n"
_READY = b"READY "
_REFUSED = b"REFUSED "


class ProtocolError(ValueError):
    """A control-pipe line that is not part of the protocol."""


class SpecError(ValueError):
    """A RUN_SPEC the child refuses. `code` names why, for the worker's terminal frame."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Ready:
    pid: int
    world_ok: bool


@dataclass(frozen=True)
class RunSpec:
    env: dict[str, str]
    io_concurrency: int


def encode_ready(*, pid: int, world_ok: bool) -> bytes:
    body = json.dumps({"pid": pid, "world": "ok" if world_ok else "error"})
    return _READY + body.encode() + b"\n"


def decode_ready(line: bytes) -> Ready:
    if not line.startswith(_READY):
        raise ProtocolError(f"expected a READY line, got {line[:40]!r}")
    try:
        body = json.loads(line[len(_READY) :])
        pid, world = body["pid"], body["world"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ProtocolError(f"malformed READY line {line[:80]!r}") from exc
    if not isinstance(pid, int) or world not in ("ok", "error"):
        raise ProtocolError(f"malformed READY line {line[:80]!r}")
    return Ready(pid=pid, world_ok=world == "ok")


def encode_refused(code: str) -> bytes:
    """The child's answer to a RUN_SPEC it will not run. `code` is `SpecError.code`.

    WHY a line and not only the exit status: the worker must tell a refusal (the same spec
    would be refused again — no retry, and the frame names the reason) from a crash before the
    ACK (a fresh child may succeed — one retry).
    """
    return _REFUSED + code.encode() + b"\n"


def refused_code(line: bytes) -> str | None:
    """The refusal code of a REFUSED line, or None for any other line."""
    if not line.startswith(_REFUSED):
        return None
    return line[len(_REFUSED) :].strip().decode(errors="replace") or "spec_malformed"


def encode_spec(env: dict[str, str], *, io_concurrency: int) -> bytes:
    body = {"spec_version": SPEC_VERSION, "env": env, "io_concurrency": io_concurrency}
    # `ensure_ascii=False`: `\uXXXX` escapes would grow a spec past the limit that its
    # decoded size fits.
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def decode_spec(line: bytes) -> RunSpec:
    """Parse one RUN_SPEC line, refusing an oversized, malformed or unknown-version one."""
    if len(line) > MAX_SPEC_BYTES:
        raise SpecError("spec_too_large", f"RUN_SPEC is {len(line)} bytes, max {MAX_SPEC_BYTES}")
    try:
        body = json.loads(line)
    except ValueError as exc:
        raise SpecError("spec_malformed", "RUN_SPEC is not JSON") from exc
    if not isinstance(body, dict):
        raise SpecError("spec_malformed", "RUN_SPEC is not a JSON object")
    version = str(body.get("spec_version", ""))
    if version.split(".")[0] != SPEC_VERSION:
        raise SpecError("unsupported_spec_version", f"RUN_SPEC version {version!r} unsupported")
    env, io = body.get("env"), body.get("io_concurrency")
    if not isinstance(env, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in env.items()
    ):
        raise SpecError("spec_malformed", "RUN_SPEC env must map strings to strings")
    if not isinstance(io, int) or isinstance(io, bool) or io < 1:
        raise SpecError("spec_malformed", "RUN_SPEC io_concurrency must be a positive integer")
    return RunSpec(env=env, io_concurrency=io)


__all__ = [
    "ACK",
    "CONTROL_FD_ENV",
    "MAX_SPEC_BYTES",
    "SPEC_VERSION",
    "ProtocolError",
    "Ready",
    "RunSpec",
    "SpecError",
    "decode_ready",
    "decode_spec",
    "encode_ready",
    "encode_refused",
    "encode_spec",
    "refused_code",
]
