"""Queue configuration must reach the running Gateway, not just Helm values."""

import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import yaml
from fastapi import HTTPException, Request

from aigateway.config import Settings
from aigateway.core.admission import dispatch_with_budgets
from aigateway.core.concurrency import provider_slot


def chart_settings(monkeypatch, queue=None):
    chart = Path(__file__).resolve().parents[2] / "charts" / "aigateway"
    args = [
        "helm",
        "template",
        "aigw",
        str(chart),
        "--set",
        "database.existingSecret=db-secret",
        "--set",
        "auth.existingSecret=auth-secret",
    ]
    if queue is not None:
        args += ["--set", f"config.providerQueueTimeoutS={queue}"]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    docs = list(yaml.safe_load_all(result.stdout))
    config = next(d for d in docs if d and d["kind"] == "ConfigMap")
    deployment = next(d for d in docs if d and d["kind"] == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert {"configMapRef": {"name": config["metadata"]["name"]}} in container["envFrom"]
    monkeypatch.delenv("AIGW_PROVIDER_QUEUE_TIMEOUT_S", raising=False)
    for key, value in config["data"].items():
        monkeypatch.setenv(key, value)
    return config["data"], Settings()


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_unset_chart_queue_timeout_preserves_execution_allowance(monkeypatch):
    config, settings = chart_settings(monkeypatch)
    assert "AIGW_PROVIDER_QUEUE_TIMEOUT_S" not in config
    assert settings.provider_queue_timeout_s is None


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.asyncio
async def test_chart_queue_timeout_returns_503_before_caller_budget(monkeypatch):
    config, settings = chart_settings(monkeypatch, queue=0.01)
    assert config["AIGW_PROVIDER_QUEUE_TIMEOUT_S"] == "0.01"
    assert settings.provider_queue_timeout_s == 0.01

    async def receive():
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    request = Request({"type": "http", "app": app, "headers": []}, receive)

    async def provider():
        pytest.fail("a queued timeout must not dispatch")

    async with provider_slot(app, "fake", settings.provider_max_concurrency):
        # Saturate all slots, mirroring an existing client's longer transport timer.
        from contextlib import AsyncExitStack

        async with AsyncExitStack() as slots:
            for _ in range(settings.provider_max_concurrency - 1):
                await slots.enter_async_context(
                    provider_slot(app, "fake", settings.provider_max_concurrency)
                )
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(dispatch_with_budgets(request, "fake", provider), 1)
    assert error.value.status_code == 503
    detail = cast(dict[str, str], error.value.detail)
    assert detail["code"] == "provider_queue_timeout"
    assert error.value.headers == {"Retry-After": "1"}
