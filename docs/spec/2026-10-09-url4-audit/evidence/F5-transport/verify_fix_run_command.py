"""Verify the proposed _run_command fix in scratch (monkeypatched; the repo is untouched).

Fix: reap the child on EVERY exit path (TimeoutError, CancelledError, any exception)."""
import asyncio, gc, os, subprocess, sys
import httpx
import url4.cli._serve as serve
from url4.core.errors import ResolutionError


async def _run_command_fixed(command, stdin_text, timeout):
    try:
        proc = await asyncio.create_subprocess_exec(
            *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
    except OSError as exc:
        raise ResolutionError(f"command {command[0]!r} failed to start: {exc}") from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin_text.encode()), timeout)
    except TimeoutError:
        raise ResolutionError(f"command {command[0]!r} timed out after {timeout}s") from None
    finally:
        if proc.returncode is None:
            proc.kill()
            # shield: the reap must finish even while the task is being cancelled
            await asyncio.shield(proc.wait())
    if proc.returncode != 0:
        raise ResolutionError(f"command {command[0]!r} exited {proc.returncode}")
    return out.decode(errors="replace")


async def main():
    serve._run_command = _run_command_fixed
    tag = f"url4fix{os.getpid()}"
    marker = f"/private/tmp/claude-501/{tag}.marker"
    cfg = serve.ServeConfig(timeout=0.3, max_inflight=1, commands={
        "/yes": ("sh", "-c", f"exec yes {tag}"),
        "/slow": ("sh", "-c", f"sleep 1; touch {marker}; : {tag}")})
    app = serve.build_asgi_app(serve.build_node(cfg), cfg)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://n") as c:
        codes = [(await c.get(u)).status_code for u in ["/yes?q=()!go"] * 3 + ["/slow?q=()!go"]]
    await asyncio.sleep(1.5); gc.collect()
    live = subprocess.run(["pgrep", "-f", tag], capture_output=True, text=True).stdout.split()
    landed = os.path.exists(marker)
    print("statuses", codes, "| live children", len(live), "| late side effect", landed)
    return 1 if live or landed else 0
sys.exit(asyncio.run(main()))
