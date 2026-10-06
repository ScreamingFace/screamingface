"""The chart ships the OTLP env to the App Deployment too, not only to the runner pool.

FEATURE: the control-plane `url4.accept` span (`OME-1218`). The App builds its span sink from its
own process env (`app.control_plane_span_sink(os.environ)`), which is ``None`` unless an OTLP
endpoint is set. Before this file the chart set `OTEL_*` on the pool alone, so on dev the App
exported nothing, opened no accept span, and forwarded the caller's traceparent — whose parent
span id `url4.run` then adopted and SigNoz never received. Every gate was green; the only symptom
was 0 `url4.accept` spans and a dangling `url4.run` parent.

WHY render rather than read the template text, and WHY the OTel variable names are literals:
see `test_chart_render_tracing.py`, which this follows.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "deploy" / "helm"
_RELEASE = "url4-cloud"
_FULLNAME = f"{_RELEASE}-{_RELEASE}"

_NATS = "config.natsUrl=nats://nats.example:4222"
_ENDPOINT = "tracing.endpoint=http://collector:4318"

ENDPOINT_VAR = "OTEL_EXPORTER_OTLP_ENDPOINT"
HEADERS_VAR = "OTEL_EXPORTER_OTLP_HEADERS"
SERVICE_VAR = "OTEL_SERVICE_NAME"
ATTRIBUTES_VAR = "OTEL_RESOURCE_ATTRIBUTES"
_OTEL_VARS = (ENDPOINT_VAR, HEADERS_VAR, SERVICE_VAR, ATTRIBUTES_VAR)

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _render(*settings: str) -> list[dict]:
    """Render the chart with extra `--set` pairs. Raises if helm refuses."""
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string", _NATS]
    for setting in settings:
        args += ["--set", setting]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _find(docs: list[dict], kind: str, name: str) -> dict:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind}/{name} in the rendered chart")


def _app_env(docs: list[dict]) -> dict:
    return _find(docs, "ConfigMap", _FULLNAME)["data"]


def _runner_env(docs: list[dict]) -> dict:
    return _find(docs, "ConfigMap", f"{_FULLNAME}-runner-env")["data"]


def _app_container(docs: list[dict]) -> dict:
    containers = _find(docs, "Deployment", _FULLNAME)["spec"]["template"]["spec"]["containers"]
    return next(c for c in containers if c["name"] == "screamingface-engine")


def _app_env_from(docs: list[dict]) -> list[dict]:
    return _app_container(docs)["envFrom"]


def _otel(data: dict) -> dict:
    return {k: v for k, v in data.items() if k.startswith("OTEL_")}


# --- enabled -------------------------------------------------------------------------------


def test_the_app_configmap_carries_the_otlp_endpoint_by_default() -> None:
    """The regression itself: tracing is ON by default (`OME-1190`), so the default render must
    give the App an endpoint, or `load_span_sink` returns None and no accept span exists."""
    data = _app_env(_render())

    assert data[ENDPOINT_VAR] == "http://signoz-otel-collector.signoz.svc.cluster.local:4318"


def test_the_app_container_reads_the_configmap_that_carries_the_endpoint() -> None:
    """An endpoint in a ConfigMap the App does not read is the same bug one hop later."""
    docs = _render("tracing.enabled=true", _ENDPOINT)

    assert {"configMapRef": {"name": _FULLNAME}} in _app_env_from(docs)
    assert _app_env(docs)[ENDPOINT_VAR] == "http://collector:4318"


def test_app_and_pool_get_the_SAME_otlp_keys() -> None:
    """INVARIANT: one source, two renderings. Both halves of a run's trace (`url4.accept` on the
    App, `url4.run` on the pool) must post to one collector under one Resource, or the parent
    the run names lands somewhere the child does not."""
    docs = _render(
        "tracing.enabled=true",
        _ENDPOINT,
        "tracing.serviceName=sf-engine",
        "tracing.resourceAttributes=deployment.environment=dev",
    )

    app = _otel(_app_env(docs))
    assert app == _otel(_runner_env(docs))
    assert app[SERVICE_VAR] == "sf-engine"
    assert app[ATTRIBUTES_VAR] == "deployment.environment=dev"


def test_the_app_gets_the_chart_created_credential_by_secret_reference() -> None:
    secret = "signoz-access-token=super-secret-token"
    docs = _render("tracing.enabled=true", _ENDPOINT, f"tracing.headers={secret}")

    assert {"secretRef": {"name": f"{_FULLNAME}-tracing"}} in _app_env_from(docs)
    app_deployment = _find(docs, "Deployment", _FULLNAME)
    assert "super-secret-token" not in yaml.safe_dump(app_deployment)
    assert "super-secret-token" not in yaml.safe_dump(_app_env(docs)), (
        "the OTLP credential must never reach a ConfigMap — it is world-readable with `get`"
    )


def test_the_app_references_an_existing_secret_by_its_own_name() -> None:
    docs = _render("tracing.enabled=true", _ENDPOINT, "tracing.existingSecret=otlp-creds")

    assert {"secretRef": {"name": "otlp-creds"}} in _app_env_from(docs)


def test_no_credential_means_no_tracing_secret_reference_on_the_app() -> None:
    """INVARIANT (`secret-tracing.yaml`): never name a Secret that will not exist — an
    unresolvable `envFrom` stops the App from starting."""
    docs = _render("tracing.enabled=true", _ENDPOINT)

    assert {"secretRef": {"name": f"{_FULLNAME}-tracing"}} not in _app_env_from(docs)


# --- disabled ------------------------------------------------------------------------------


def test_disabled_tracing_gives_the_app_no_otlp_env_and_no_secret_reference() -> None:
    """Even with a credential configured: the off switch must switch the App off too."""
    docs = _render(
        "tracing.enabled=false",
        _ENDPOINT,
        "tracing.headers=k=v",
        "tracing.existingSecret=otlp-creds",
    )

    data = _app_env(docs)
    for name in _OTEL_VARS:
        assert name not in data, f"{name} reached the App with tracing disabled"
    refs = [ref for ref in _app_env_from(docs) if "secretRef" in ref]
    assert {"secretRef": {"name": "otlp-creds"}} not in refs
    assert {"secretRef": {"name": f"{_FULLNAME}-tracing"}} not in refs
