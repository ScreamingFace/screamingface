"""Repro F1: under `url4 serve`, a command that overruns --timeout is NOT killed.

The wrapper's asyncio.timeout(config.timeout) (_serve.py:297) is armed at request
start; the command's wait_for(…, timeout) (_serve.py:153) is armed later with the
SAME duration. So the outer deadline always fires first, cancels the handler with
CancelledError, and `except TimeoutError` at _serve.py:154 never runs -> no kill.

Two command shapes:
  * `sleep N; touch MARKER`   -> the side effect lands AFTER the 504 was sent
  * `yes`                     -> infinite stdout; the cancelled communicate()
                                 leaves a paused pipe, the child blocks on write
                                 and NEVER exits (leaked process + fds)
Control: the same command through node.fetch() without the wrapper (inner
timeout path) IS killed.

Run: .venv/bin/python repro_subprocess_orphan.py
"""

from __future__ import annotations

import asyncio
import gc
import os
import subprocess
import sys
import tempfile

import httpx

from url4.cli._serve import ServeConfig, build_asgi_app, build_node


def alive(pattern: str) -> list[str]:
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout
    return out.split()


async def main() -> int:
    tmp = tempfile.mkdtemp()
    marker = os.path.join(tmp, "side_effect_landed")
    tag = f"url4orphan{os.getpid()}"
    cfg = ServeConfig(
        timeout=0.5,
        max_inflight=4,
        commands={
            "/slow": ("sh", "-c", f"sleep 1.5; touch {marker}; : {tag}slow"),
            "/yes": ("sh", "-c", f"exec yes {tag}yes"),
        },
    )
    node = build_node(cfg)
    app = build_asgi_app(node, cfg)
    transport = httpx.ASGITransport(app=app)
    failures = 0
    async with httpx.AsyncClient(transport=transport, base_url="http://node") as client:
        # --- case A: slow command with a side effect ---
        r = await client.get("/slow?q=()!go")
        print("A status", r.status_code, r.text[:90])
        print("A children right after 504:", alive(f"{tag}slow"))
        await asyncio.sleep(2.0)
        gc.collect()
        landed = os.path.exists(marker)
        print("A side effect landed after the 504:", landed)
        failures += landed

        # --- case B: infinite-output command ---
        r = await client.get("/yes?q=()!go")
        print("B status", r.status_code)
        await asyncio.sleep(1.0)
        gc.collect()
        await asyncio.sleep(0.5)
        pids = alive(f"{tag}yes")
        print("B `yes` children still alive 1.5s after the 504:", pids)
        failures += bool(pids)
        for pid in pids:
            os.kill(int(pid), 9)

    # --- control: same commands, node.fetch only (inner timeout kills) ---
    os.path.exists(marker) and os.remove(marker)
    cfg2 = ServeConfig(timeout=0.5, commands={
        "/slow": ("sh", "-c", f"sleep 1.5; touch {marker}; : {tag}ctl")})
    node2 = build_node(cfg2)
    try:
        await node2.fetch("/slow?q=()!go", relative=True)
    except Exception as exc:  # noqa: BLE001
        print("C (no wrapper) raised", type(exc).__name__, exc)
    await asyncio.sleep(2.0)
    print("C side effect landed without wrapper:", os.path.exists(marker))
    print("C children:", alive(f"{tag}ctl"))
    print("RESULT", "ORPHAN REPRODUCED" if failures else "no orphan")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
