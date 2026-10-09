"""Check that a running sidecar serves every bundled benchmark dataset.

Run by verify-sidecar.sh with the build venv's Python while the frozen sidecar is up. It needs
no provider: each 1-case run's model call fails, so the run still ends `succeeded` with a null
score. What it proves is that the Engine found and loaded each bundle's cases (spec D10).
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import websockets

ENGINE = "http://127.0.0.1:9108"
EXPECTED_BENCHMARKS = 8
# The first benchmark of each prepared bundle, except DRACO (plan T-D2.3).
BUNDLE_BENCHMARKS = {
    "ifeval": "ifeval",
    "healthbench": "healthbench-professional",
    "gdpval": "gdpval-text",
    "medxpert": "medxpert",
    "contracteval": "contracteval",
}
# Any syntactically valid one-model candidate. No provider is connected, so it never answers.
CANDIDATE = "(m:0.0:/anthropic/claude-opus-5)!'$m'"
RUN_TIMEOUT_S = 120


def linked_expression(benchmark_url4: str) -> str:
    escaped = CANDIDATE.replace("\\", "\\\\").replace("'", "\\'")
    return f"(candidate:0.0:'{escaped}', {benchmark_url4})!''"


def command(kind: str, data: dict[str, object]) -> str:
    return json.dumps(
        {
            "specversion": "1.0",
            "id": uuid.uuid4().hex,
            "source": "/screamingface-studio/verify-sidecar",
            "type": kind,
            "datacontenttype": "application/json",
            "data": data,
        }
    )


async def run_one_case(http: httpx.AsyncClient, benchmark_id: str) -> None:
    detail = await http.get(f"/v1/benchmarks/{benchmark_id}", params={"limit": 1})
    detail.raise_for_status()
    token = (await http.post("/token")).raise_for_status().json()["token"]
    ws_url = f"{ENGINE.replace('http', 'ws', 1)}/ws?ticket={token}"
    case_loading_completed = False
    score: object = "missing"
    async with websockets.connect(ws_url, subprotocols=["cloudevents.json"]) as socket:
        # `from_sequence: null` attaches from the start; 0 is an invalid frame (1-based).
        await socket.send(command("ai.url4.attach", {"from_sequence": None}))
        started = await http.get(
            "/",
            params={"q": linked_expression(detail.json()["url4"])},
            headers={"URL4-Capability": token, "Prefer": "respond-async"},
        )
        if started.status_code != 202:
            raise SystemExit(
                f"{benchmark_id}: start returned {started.status_code}: {started.text}"
            )
        while True:
            frame = json.loads(await asyncio.wait_for(socket.recv(), RUN_TIMEOUT_S))
            data = frame.get("data") or {}
            if frame["type"] == "ai.url4.log":
                attributes = data.get("attributes") or {}
                if (
                    attributes.get("sf.activity.kind") == "case_loading"
                    and attributes.get("sf.activity.state") == "completed"
                ):
                    case_loading_completed = True
            elif frame["type"] == "ai.url4.result":
                score = json.loads(data["body"]).get("score", "missing")
            elif frame["type"] == "ai.url4.error":
                raise SystemExit(f"{benchmark_id}: engine rejected a frame: {data}")
            elif frame["type"] == "ai.url4.terminated":
                status = data.get("status")
                break
    if not case_loading_completed:
        raise SystemExit(
            f"{benchmark_id}: case loading never completed (status {status})"
        )
    if status != "succeeded" or score is not None:
        raise SystemExit(
            f"{benchmark_id}: expected succeeded with a null score, got {status} {score!r}"
        )
    print(
        f"SCREAMINGFACE_BENCHMARK_OK {benchmark_id} case_loading=completed status={status}"
    )


async def main() -> None:
    async with httpx.AsyncClient(base_url=ENGINE, timeout=60) as http:
        catalog = (await http.get("/v1/benchmarks")).raise_for_status().json()["data"]
        if len(catalog) != EXPECTED_BENCHMARKS:
            raise SystemExit(
                f"expected {EXPECTED_BENCHMARKS} benchmarks, the Engine lists {len(catalog)}"
            )
        print(f"SCREAMINGFACE_BENCHMARKS_LISTED count={len(catalog)}")
        for benchmark_id in BUNDLE_BENCHMARKS.values():
            await run_one_case(http, benchmark_id)


if __name__ == "__main__":
    asyncio.run(main())
