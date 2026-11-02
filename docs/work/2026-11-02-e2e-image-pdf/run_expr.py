"""Run one url4 expression on a local engine (`serve --local`) and save every WS frame.

Token → WS attach → GET /?q= (sync) → frames until terminated. Frames are written as JSON lines
with any base64 data URI elided (the run log must not carry one; the elision is counted so a
leak is still visible).

Usage: python run_expr.py <expression_file> <frames.jsonl>
"""

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx
import websockets

BASE = "http://127.0.0.1:9108"
B64 = re.compile(r"data:[a-z0-9.+/-]+;base64,[A-Za-z0-9+/=]{16,}")


async def main(expr: str, out: Path) -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=1900) as client:
        token = (await client.post("/token")).json()["token"]
        frames: list[dict] = []
        async with websockets.connect(
            f"ws://127.0.0.1:9108/ws?ticket={token}", max_size=None
        ) as ws:
            attach = {
                "specversion": "1.0",
                "id": "attach-1",
                "source": "/e2e",
                "type": "ai.url4.attach",
                "data": {},
            }
            await ws.send(json.dumps(attach))
            await asyncio.sleep(0.5)
            get = asyncio.create_task(
                client.get("/", params={"q": expr}, headers={"URL4-Capability": token})
            )

            async def pump() -> None:
                async for raw in ws:
                    frame = json.loads(raw)
                    frames.append(frame)
                    if "terminated" in str(frame.get("type")):
                        return

            pumping = asyncio.create_task(pump())
            resp = await get
            try:
                await asyncio.wait_for(pumping, timeout=30)
            except asyncio.TimeoutError:
                print("no terminated frame within 30s of the HTTP answer")
        leaks = 0
        with out.open("w") as f:
            for frame in frames:
                text = json.dumps(frame)
                leaks += len(B64.findall(text))
                f.write(B64.sub("data:<elided>", text) + "\n")
        print("HTTP", resp.status_code, resp.headers.get("content-type"))
        print("BODY", resp.text[:3000])
        print("TYPES", sorted({str(f.get("type")) for f in frames}))
        print("FRAMES", len(frames), "BASE64_DATA_URIS_IN_FRAMES", leaks)
        for frame in frames:
            if any(
                k in str(frame.get("type")) for k in ("cost", "terminated", "error")
            ):
                print(frame["type"], json.dumps(frame.get("data"))[:900])


asyncio.run(main(Path(sys.argv[1]).read_text().strip(), Path(sys.argv[2])))
