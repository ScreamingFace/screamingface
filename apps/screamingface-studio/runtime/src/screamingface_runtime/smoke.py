"""Deterministic check for the local runtime's public HTTP APIs."""

from __future__ import annotations

import argparse
import asyncio
import httpx


async def smoke(engine_url: str, gateway_url: str, scoreboard_url: str) -> int:
    """Verify all services and the Engine-to-Gateway catalog integration."""

    async with httpx.AsyncClient(timeout=30.0) as http:
        for service, base_url in (
            ("Engine", engine_url),
            ("AI Gateway", gateway_url),
            ("Scoreboard", scoreboard_url),
        ):
            response = await http.get(f"{base_url}/healthz")
            response.raise_for_status()
            if response.json() != {"status": "ok"}:
                raise RuntimeError(f"{service} returned an unexpected health response")

        response = await http.get(f"{engine_url}/v1/models")
        response.raise_for_status()
        models = response.json().get("data", [])
        if not models:
            raise RuntimeError("Engine returned an empty model catalog")
        return len(models)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-url", default="http://127.0.0.1:9108")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:9105")
    parser.add_argument("--scoreboard-url", default="http://127.0.0.1:9106")
    args = parser.parse_args(argv)
    model_count = asyncio.run(
        smoke(args.engine_url, args.gateway_url, args.scoreboard_url)
    )
    print(f"SCREAMINGFACE_RUNTIME_SMOKE_OK models={model_count}", flush=True)


if __name__ == "__main__":
    main()
