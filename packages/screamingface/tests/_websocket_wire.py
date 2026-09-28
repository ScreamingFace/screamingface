"""RFC 6455 frame helpers and a CloudEvent builder for hand-rolled stub engines in tests.

AIDEV-NOTE: stub engines speak raw WebSocket frames over `BaseHTTPRequestHandler` so that
each test controls the exact close code and timing. New stubs import these helpers.
`test_run_resume_reconnect.py` still holds its own older copy: the append-only test gate
protects helper bodies in prior test files, so moving it there is an owner decision.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from typing import Any


def cloudevent(
    kind: str, data: dict[str, object], sequence: int, *, subject: str
) -> dict[str, object]:
    """One sequenced Engine frame, as the Engine's bridge sends it."""
    return {
        "specversion": "1.0",
        "id": f"event_{sequence}",
        "source": f"/trace/{subject}/node/root",
        "subject": subject,
        "time": datetime.now(UTC).isoformat(),
        "type": kind,
        "datacontenttype": "application/json",
        "sequence": str(sequence),
        "sequencetype": "Integer",
        "data": data,
    }


def read_client_text_frame(stream: Any) -> str:
    """Read one (masked) client text frame."""
    header = stream.read(2)
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", stream.read(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", stream.read(8))[0]
    mask = stream.read(4) if header[1] & 0x80 else b""
    payload = stream.read(length)
    if mask:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return payload.decode()


def send_server_text_frame(stream: Any, value: str) -> None:
    """Write one unmasked server text frame (FIN + opcode 1)."""
    payload = value.encode()
    if len(payload) < 126:
        header = bytes((0x81, len(payload)))
    elif len(payload) < 65536:
        header = bytes((0x81, 126)) + struct.pack("!H", len(payload))
    else:
        header = bytes((0x81, 127)) + struct.pack("!Q", len(payload))
    stream.write(header + payload)
    stream.flush()


def send_server_close(stream: Any, code: int) -> None:
    """Write a close frame (FIN + opcode 8) with a two-byte status; server frames are unmasked."""
    payload = struct.pack("!H", code)
    stream.write(bytes((0x88, len(payload))) + payload)
    stream.flush()
