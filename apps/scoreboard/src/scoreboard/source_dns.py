"""System DNS lookup that can be stopped without retaining executor threads."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import sys
from contextlib import suppress

_LOOKUP_SCRIPT = """
import json, socket, sys
answers = socket.getaddrinfo(sys.argv[1], int(sys.argv[2]), type=socket.SOCK_STREAM)
print(json.dumps(list(dict.fromkeys(str(answer[4][0]) for answer in answers))))
"""


async def _lookup(host: str, port: int) -> list[str]:
    # WHY: OS getaddrinfo has no cancellable API. Isolate it so a probe timeout
    # can stop and reap it, instead of asyncio.run waiting for an executor thread.
    # Host/port are argv data, never shell commands or interpolated Python code.
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-S",
        "-c",
        _LOOKUP_SCRIPT,
        host,
        str(port),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await process.communicate()
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        # Drain pipes even if exit raced cancellation; wait() alone can stall
        # on a full pipe. Normal completion makes this second call a no-op.
        await process.communicate()
    if process.returncode != 0:
        raise OSError("source DNS lookup failed")
    addresses = json.loads(output)
    if not isinstance(addresses, list) or not all(isinstance(item, str) for item in addresses):
        raise ValueError("invalid source DNS response")
    return addresses


async def resolve_public_host(host: str, port: int) -> list[str]:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return await _lookup(host, port)
    # Numeric targets are already resolved. The transport still checks publicness.
    return [str(address)]
