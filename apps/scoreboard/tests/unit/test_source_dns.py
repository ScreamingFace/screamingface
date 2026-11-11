"""Check whole-command shutdown, not just the time a timeout result is returned."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from scoreboard import source_dns
from scoreboard.source_probe import PublicSourceTransport, probe_source

APP = Path(__file__).resolve().parents[2]


def test_stalled_dns_does_not_hold_command_open(tmp_path):
    # The old implementation takes five seconds after returning False in 200 ms.
    # Patch both the original thread resolver and the new subprocess worker script.
    driver = r"""
import asyncio, json, os, socket, time
from pathlib import Path
import httpx
from scoreboard.source_probe import PublicSourceTransport, probe_source, resolve_public_host
pid_file = Path(__import__('sys').argv[1])
def stalled(*args, **kwargs):
    time.sleep(5)
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
socket.getaddrinfo = stalled
resolve_public_host.__globals__['_LOOKUP_SCRIPT'] = (
    'import os, time; from pathlib import Path; '
    + 'Path(' + repr(str(pid_file)) + ').write_text(str(os.getpid())); time.sleep(5)'
)
async def run():
    def forbidden(request):
        raise AssertionError('timeout must not make an HTTP request')
    transport = PublicSourceTransport(transport=httpx.MockTransport(forbidden))
    async with httpx.AsyncClient(transport=transport) as client:
        return await probe_source('https://source.example/', client, deadline=0.2)
started = time.monotonic()
result = asyncio.run(run())
elapsed = time.monotonic() - started
alive = False
if pid_file.exists():
    try:
        os.kill(int(pid_file.read_text()), 0)
        alive = True
    except ProcessLookupError:
        pass
print(json.dumps({'result': result, 'elapsed': elapsed, 'worker_alive': alive}))
"""
    command = subprocess.run(
        [sys.executable, "-c", driver, str(tmp_path / "resolver.pid")],
        cwd=APP,
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    outcome = json.loads(command.stdout)
    assert outcome["result"] is False
    assert outcome["elapsed"] < 2, outcome
    assert outcome["worker_alive"] is False, outcome


@pytest.mark.asyncio
async def test_system_resolver_returns_localhost_addresses_without_external_network():
    addresses = await source_dns.resolve_public_host("localhost", 443)
    assert addresses
    assert all(ipaddress.ip_address(address).is_loopback for address in addresses)


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["93.184.216.34", "2606:4700:4700::1111"])
async def test_numeric_addresses_need_no_resolver_process(monkeypatch, host):
    async def forbidden(*args, **kwargs):
        pytest.fail("numeric address spawned a DNS process")

    monkeypatch.setattr(source_dns.asyncio, "create_subprocess_exec", forbidden)
    assert await source_dns.resolve_public_host(host, 443) == [host]


@pytest.mark.asyncio
@pytest.mark.parametrize("fill_pipe", [False, True])
async def test_explicit_cancellation_reaps_worker(tmp_path, monkeypatch, fill_pipe):
    pid_file = tmp_path / "cancelled-resolver.pid"
    script = (
        "import os, sys, time; from pathlib import Path; "
        + "Path("
        + repr(str(pid_file))
        + ").write_text(str(os.getpid())); "
        + ('sys.stdout.write("x" * 1000000); sys.stdout.flush(); ' if fill_pipe else "")
        + "time.sleep(10)"
    )
    monkeypatch.setattr(source_dns, "_LOOKUP_SCRIPT", script)
    task = asyncio.create_task(source_dns.resolve_public_host("source.example", 443))
    try:
        async with asyncio.timeout(3):
            while not pid_file.exists() or not pid_file.read_text():
                await asyncio.sleep(0.01)
        pid = int(pid_file.read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        # A reaped worker is neither running nor a zombie.
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script",
    [
        'import sys; print("private resolver diagnostic", file=sys.stderr); sys.exit(1)',
        'print("not json")',
        'print("{}")',
        'print("[1]")',
        'print("[]")',
    ],
)
async def test_worker_errors_are_unchecked_without_http_request(monkeypatch, script):
    monkeypatch.setattr(source_dns, "_LOOKUP_SCRIPT", script)

    def forbidden(request):
        pytest.fail("failed DNS made an HTTP request")

    async with httpx.AsyncClient(
        transport=PublicSourceTransport(transport=httpx.MockTransport(forbidden))
    ) as client:
        assert await probe_source("https://source.example/", client) is False
