"""FX-92 — the node tier's `/healthz` reports the same `config_digest` the App reports.

# WHY this file exists. erd.md §2 and contracts.md C2 put `config_digest` on BOTH tiers' health
# endpoints: during a rolling deploy the App and the node can briefly read different configs, and
# the App would forward a mount the node no longer serves. Only the App reported it, so the two
# could not be compared. The tier's world is injected (`config=`) so the digest provably comes
# from the FILE at `URL4_RUNNER_CONFIG`, not from the parsed object.
"""

from __future__ import annotations

import pathlib

import httpx
import pytest

from screamingface_engine import job_env
from screamingface_engine.rest.forwarder import derive_forward_contract
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.node_tier import NodeTier, build_node_tier
from url4.streaming.protocol.signals import ResultArtifact

_MODEL = "anthropic/claude-haiku-4-5"
_KEY = "fx-92-test-artifact-signing-key-0123456789abcdef"
_FIXTURE = b"# fx-92 digest fixture\n"
# WHY a literal: `sha256sum` of `_FIXTURE`, computed once outside the code under test.
_FIXTURE_SHA256 = "fecce872b72c69d11c113be685942cb3119e2be66e825d3e38a37af49922701c"


class _NeverSpills:
    def write_bytes(self, encoded: bytes) -> ResultArtifact:
        raise AssertionError("a health probe never spills")

    def write_text(self, body: str) -> ResultArtifact:
        raise AssertionError("a health probe never spills")


def _config() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_MODEL,
            models=(ModelSpec(id=_MODEL),),
        )
    )


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"a health probe makes no outbound call: {request.url}")


async def _tier(env: dict[str, str], client: httpx.AsyncClient) -> NodeTier:
    return await build_node_tier(
        env=env,
        config=_config(),
        client=client,
        artifact_store=_NeverSpills(),
        artifact_signing_key=_KEY,
    )


async def _health(env: dict[str, str]) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_unreachable)) as client:
        tier = await _tier(env, client)
        try:
            transport = httpx.ASGITransport(app=tier)
            async with httpx.AsyncClient(transport=transport, base_url="http://node.test") as node:
                return await node.get("/healthz")
        finally:
            await tier.aclose()


@pytest.mark.asyncio
async def test_the_node_healthz_reports_the_config_file_digest(tmp_path: pathlib.Path) -> None:
    config = tmp_path / "url4.toml"
    config.write_bytes(_FIXTURE)

    response = await _health({job_env.RUNNER_CONFIG: str(config)})

    assert response.status_code == 200
    assert response.json() == {"status": "live", "config_digest": _FIXTURE_SHA256}


@pytest.mark.asyncio
async def test_an_unreadable_config_file_omits_the_digest(tmp_path: pathlib.Path) -> None:
    response = await _health({job_env.RUNNER_CONFIG: str(tmp_path / "absent.toml")})

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


@pytest.mark.asyncio
async def test_the_app_and_the_node_report_one_digest_for_one_file(tmp_path: pathlib.Path) -> None:
    """INVARIANT: the two tiers hash the same file the same way, or the drift check is noise."""
    config = tmp_path / "url4.toml"
    config.write_bytes(_FIXTURE)
    env = {job_env.RUNNER_CONFIG: str(config)}

    node_digest = (await _health(env)).json()["config_digest"]
    contract = await derive_forward_contract(env=env, engine_routes=("/healthz",), config=_config())

    assert contract.config_digest == node_digest == _FIXTURE_SHA256
