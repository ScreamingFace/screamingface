"""Repro F1b: --max-inflight=1, three sequential requests to an infinite-output
command; each 504 releases the slot while its child keeps running, so 3 live
subprocesses exist under a limit of 1 (the BMC trace of prove_admission_current.py).
Run: .venv/bin/python repro_yes_persist.py   (exit 1 = reproduced)"""
import asyncio, gc, os, subprocess, sys
import httpx
from url4.cli._serve import ServeConfig, build_asgi_app, build_node

def pids(tag):
    return subprocess.run(["pgrep", "-f", tag], capture_output=True, text=True).stdout.split()

async def main():
    tag = f"url4yes{os.getpid()}"
    cfg = ServeConfig(timeout=0.3, max_inflight=1, commands={"/yes": ("sh", "-c", f"exec yes {tag}")})
    app = build_asgi_app(build_node(cfg), cfg)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://n") as c:
        codes = [(await c.get("/yes?q=()!go")).status_code for _ in range(3)]
    print("statuses", codes, "max_inflight", cfg.max_inflight)
    for t in (1, 5):
        await asyncio.sleep(t); gc.collect()
        live = pids(tag)
        states = subprocess.run(["ps", "-o", "stat=", "-p", ",".join(live)], capture_output=True,
                                text=True).stdout.split() if live else []
        print(f"after +{t}s: {len(live)} live children, process states {states}")
    live = pids(tag)
    for p in live: os.kill(int(p), 9)
    return 1 if len(live) > cfg.max_inflight else 0
sys.exit(asyncio.run(main()))
