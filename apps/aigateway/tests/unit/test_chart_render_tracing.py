"""The chart ships the OTLP endpoint and credential to aigateway (OME-1184).

`OME-1132` made the gateway emit spans and left it inert — nothing set
`OTEL_EXPORTER_OTLP_ENDPOINT`, and the chart had no way to. This is what turns it on, so the
failure this file guards is specific: **a chart that sets a variable the code does not read is
silently inert.** Everything renders, every gate passes, nothing is exported, and the only
symptom is an empty trace view.

WHY render rather than read the template text: `helm lint` reports "0 chart(s) failed" for a
chart that cannot render at all. This follows `screamingface-engine`'s
`test_chart_render_tracing.py`, deliberately — two charts configuring one feature two different
ways is a tax paid at every future edit.

WHY the variable names are hardcoded rather than imported from `aigateway.tracing`: they are
OpenTelemetry's own specified names. The chart and the code conform to the same external spec
independently, so the literal belongs on both sides — that is conformance, not duplication.

AIDEV-NOTE: these tests need `helm` on PATH and carry a `skipif` for laptops without it.
GitHub's `ubuntu-latest` image ships helm, so they DO run on the merge gate — verified in the
run log, not assumed from the workflow file. That is a dependency on the runner image rather
than on anything this repo pins: if a future image drops helm, these tests would start skipping
SILENTLY and still report green. If you ever see them reported as skipped in CI, that is a
broken gate, not a tolerable environment difference.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "charts" / "aigateway"
_RELEASE = "aigw"
_FULLNAME = f"{_RELEASE}-aigateway"

# Required by the chart regardless of what this unit touches.
_BASE = (
    "database.existingSecret=db-secret",
    "auth.existingSecret=auth-secret",
)

ENDPOINT_VAR = "OTEL_EXPORTER_OTLP_ENDPOINT"
HEADERS_VAR = "OTEL_EXPORTER_OTLP_HEADERS"
SERVICE_VAR = "OTEL_SERVICE_NAME"
ATTRIBUTES_VAR = "OTEL_RESOURCE_ATTRIBUTES"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _args(*settings: str) -> list[str]:
    args = ["helm", "template", _RELEASE, str(_CHART)]
    for setting in (*_BASE, *settings):
        args += ["--set", setting]
    return args


def _render(*settings: str) -> list[dict]:
    result = subprocess.run(_args(*settings), capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _render_error(*settings: str) -> str:
    result = subprocess.run(_args(*settings), capture_output=True, text=True)
    assert result.returncode != 0, "the chart rendered when it should have refused"
    return result.stderr


def _find(docs: list[dict], kind: str, name: str) -> dict:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind}/{name} in the rendered chart")


def _maybe(docs: list[dict], kind: str, name: str) -> dict | None:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    return None


def _config(docs: list[dict]) -> dict:
    return _find(docs, "ConfigMap", _FULLNAME)["data"]


def _env_from(docs: list[dict]) -> list[dict]:
    deployment = _find(docs, "Deployment", _FULLNAME)
    return deployment["spec"]["template"]["spec"]["containers"][0]["envFrom"]


# --- off by default ---------------------------------------------------------------------------


def test_tracing_is_off_by_default_and_renders_no_otlp_variables() -> None:
    """`aigateway.tracing` treats an absent endpoint as off, so the default chart must leave it
    absent. Asserted across the WHOLE manifest: one stray OTLP name anywhere would turn export
    on for some deployment, and off-by-default is what keeps every existing install unaffected.
    """
    rendered = yaml.safe_dump_all(_render())

    for name in (ENDPOINT_VAR, HEADERS_VAR, SERVICE_VAR, ATTRIBUTES_VAR):
        assert name not in rendered, f"{name} renders by default — tracing must be opt-in"


def test_the_default_values_state_tracing_is_disabled() -> None:
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))

    assert values["tracing"]["enabled"] is False


# --- turning it on ------------------------------------------------------------------------


def test_an_endpoint_reaches_the_config_map() -> None:
    docs = _render("tracing.enabled=true", "tracing.endpoint=http://collector:4318")

    assert _config(docs)[ENDPOINT_VAR] == "http://collector:4318"


def test_the_pod_inherits_the_config_map() -> None:
    """The endpoint is useless in a ConfigMap the pod does not read."""
    docs = _render("tracing.enabled=true", "tracing.endpoint=http://collector:4318")

    assert {"configMapRef": {"name": _FULLNAME}} in _env_from(docs)


def test_enabling_tracing_without_an_endpoint_fails_the_render() -> None:
    """The LOUD half of fail-open-but-loud, at the loudest moment available.

    A deployment that believes it is exporting and is not is invisible at runtime — there is no
    error, just an empty trace view. Refusing at `helm template` makes that state
    unrepresentable rather than merely discouraged.

    NOTE this chart has NO `values.schema.json`, unlike the engine's. The template `fail` is
    therefore the ONLY guard, not a backstop behind a schema rule — which is exactly why it has
    a test of its own.
    """
    stderr = _render_error("tracing.enabled=true")

    assert "tracing.endpoint" in stderr, f"the refusal must name the missing value: {stderr}"


# --- the credential ------------------------------------------------------------------------


def test_headers_travel_by_secret_reference_and_never_as_a_literal() -> None:
    """A manifest is readable by anything with `get` on it and is echoed by `kubectl describe`
    and `helm get manifest`."""
    secret = "signoz-access-token=super-secret-token"
    docs = _render(
        "tracing.enabled=true",
        "tracing.endpoint=http://collector:4318",
        f"tracing.headers={secret}",
    )

    assert {"secretRef": {"name": f"{_FULLNAME}-tracing"}} in _env_from(docs)
    assert "super-secret-token" not in yaml.safe_dump(_find(docs, "Deployment", _FULLNAME)), (
        "the OTLP credential must never be a literal in the pod's env"
    )
    assert "super-secret-token" not in yaml.safe_dump(_config(docs)), (
        "the OTLP credential must never reach a ConfigMap — it is world-readable with `get`"
    )


def test_the_credential_is_keyed_by_its_own_variable_name() -> None:
    """`envFrom.secretRef` injects keys under their OWN names and cannot rename, so the key must
    literally be the variable the exporter reads."""
    docs = _render(
        "tracing.enabled=true",
        "tracing.endpoint=http://collector:4318",
        "tracing.headers=k=v",
    )

    assert HEADERS_VAR in _find(docs, "Secret", f"{_FULLNAME}-tracing")["stringData"]


def test_headers_are_optional_so_an_in_cluster_collector_needs_no_credential() -> None:
    """The actual production shape: SigNoz runs in the same cluster
    (`signoz-otel-collector.signoz.svc.cluster.local:4318`) and needs no credential at all.
    Demanding one would block the deployment we really have."""
    docs = _render("tracing.enabled=true", "tracing.endpoint=http://collector.signoz:4318")

    assert _maybe(docs, "Secret", f"{_FULLNAME}-tracing") is None
    assert {"secretRef": {"name": f"{_FULLNAME}-tracing"}} not in _env_from(docs), (
        "an envFrom naming a Secret that is never created stops the pod from starting"
    )


def test_an_existing_secret_suppresses_the_chart_created_one() -> None:
    docs = _render(
        "tracing.enabled=true",
        "tracing.endpoint=http://collector:4318",
        "tracing.existingSecret=otlp-creds",
    )

    assert _maybe(docs, "Secret", f"{_FULLNAME}-tracing") is None
    assert {"secretRef": {"name": "otlp-creds"}} in _env_from(docs)


# --- the optional descriptive values ---------------------------------------------------------


def test_the_service_name_and_resource_attributes_reach_the_config_map() -> None:
    docs = _render(
        "tracing.enabled=true",
        "tracing.endpoint=http://collector:4318",
        "tracing.serviceName=aigateway",
        "tracing.resourceAttributes=deployment.environment=dev",
    )

    data = _config(docs)
    assert data[SERVICE_VAR] == "aigateway"
    assert data[ATTRIBUTES_VAR] == "deployment.environment=dev"


def test_unset_descriptive_values_are_ABSENT_rather_than_empty() -> None:
    """Rendering `""` OVERRIDES the code's own default with an empty string rather than leaving
    it unset. Here that reports every gateway span under a blank service name, which in a
    tracing backend is indistinguishable from an unconfigured service."""
    data = _config(_render("tracing.enabled=true", "tracing.endpoint=http://collector:4318"))

    assert SERVICE_VAR not in data
    assert ATTRIBUTES_VAR not in data
