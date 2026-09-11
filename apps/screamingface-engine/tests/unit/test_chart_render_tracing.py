"""The chart ships the OTLP endpoint and credential to the runner pool (OME-1131).

`OME-1130` built the exporter and deliberately left it inert — off unless an OTLP endpoint is
configured. This is the half that can turn it on, so the failure mode this file guards is
specific: **a chart that sets a variable the code does not read is silently inert.** Everything
renders, every gate passes, nothing is exported, and the only symptom is an empty trace view.

WHY render rather than read the template text: `helm lint` reports "0 chart(s) failed" for a
chart that cannot render at all. Every chart test in this repo asserts against the RENDERED
manifest for that reason, and this follows `test_chart_render_runner_pool.py`.

WHY the variable names are hardcoded here rather than imported from the code: they are
OpenTelemetry's own specified names, not ours. The chart and `screamingface_engine.tracing`
conform to the same external spec independently, so the literal belongs on both sides — this
is conformance, not a duplicated constant.
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

ENDPOINT_VAR = "OTEL_EXPORTER_OTLP_ENDPOINT"
HEADERS_VAR = "OTEL_EXPORTER_OTLP_HEADERS"
SERVICE_VAR = "OTEL_SERVICE_NAME"
ATTRIBUTES_VAR = "OTEL_RESOURCE_ATTRIBUTES"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _render(*settings: str) -> list[dict]:
    """Render the chart with extra `--set` pairs. Raises if helm refuses."""
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string", _NATS]
    for setting in settings:
        args += ["--set", setting]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _render_ns(namespace: str, *settings: str) -> list[dict]:
    """Render into a specific namespace — `OME-1190`'s attribute default is derived from it."""
    args = ["helm", "template", _RELEASE, str(_CHART), "-n", namespace, "--set-string", _NATS]
    for setting in settings:
        args += ["--set", setting]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _render_error(*settings: str) -> str:
    """Render expecting REFUSAL, and return what helm said. Fails loudly if it succeeded."""
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string", _NATS]
    for setting in settings:
        args += ["--set", setting]
    result = subprocess.run(args, capture_output=True, text=True)
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


def _runner_env(docs: list[dict]) -> dict:
    return _find(docs, "ConfigMap", f"{_FULLNAME}-runner-env")["data"]


def _pool(docs: list[dict]) -> dict:
    return _find(docs, "Deployment", f"{_FULLNAME}-runner")


# --- off by default ---------------------------------------------------------------------------


def test_tracing_is_ON_by_default_and_points_at_the_in_cluster_collector() -> None:
    """INVERTED by `OME-1190`, deliberately. This used to assert off-by-default.

    ArgoCD merges chart defaults UNDER the deployment's values file, which lives in a repo this
    project's agent cannot reach — so defaulting here is what actually ships tracing. Defensible
    ONLY while the chart is unpublished; see the sunset note on `tracing.enabled` in values.yaml.
    """
    data = _runner_env(_render())

    assert data[ENDPOINT_VAR] == "http://signoz-otel-collector.signoz.svc.cluster.local:4318"


def test_the_default_values_state_tracing_is_enabled() -> None:
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))

    assert values["tracing"]["enabled"] is True


def test_the_off_switch_still_works() -> None:
    """Defaulting ON must not remove the ability to turn it OFF — an operator, or a cluster with
    no collector, has to be able to render a chart that exports nothing."""
    rendered = yaml.safe_dump_all(_render("tracing.enabled=false"))

    for name in (ENDPOINT_VAR, HEADERS_VAR, SERVICE_VAR, ATTRIBUTES_VAR):
        assert name not in rendered, f"{name} renders with tracing explicitly disabled"


def test_the_default_endpoint_is_never_the_signoz_UI_hostname() -> None:
    """The verified footgun, pinned now that the chart ships a default: the UI host answers
    200 text/html for /v1/traces, OTel treats any 2xx as success, and every span would be
    discarded while the exporter reported healthy."""
    assert "signoz.pulse.dev.openmined.org" not in yaml.safe_dump_all(_render())


# --- turning it on ------------------------------------------------------------------------


def test_an_endpoint_reaches_the_runner_env_configmap() -> None:
    docs = _render("tracing.enabled=true", "tracing.endpoint=http://collector:4318")

    assert _runner_env(docs)[ENDPOINT_VAR] == "http://collector:4318"


def test_the_pool_inherits_the_tracing_configmap() -> None:
    """The endpoint is useless in a ConfigMap the pool does not read — and the pool's children
    inherit their env from the worker, so this one reference carries the whole chain."""
    docs = _render("tracing.enabled=true", "tracing.endpoint=http://collector:4318")

    env_from = _pool(docs)["spec"]["template"]["spec"]["containers"][0]["envFrom"]
    assert {"configMapRef": {"name": f"{_FULLNAME}-runner-env"}} in env_from


def test_enabling_tracing_without_an_endpoint_fails_the_render() -> None:
    """The LOUD half of fail-open-but-loud, at the loudest moment available.

    A deployment that believes it is exporting and is not is the failure this whole unit exists
    to prevent, and it is invisible at runtime — there is no error, just an empty trace view.
    Refusing at `helm template` makes that state unrepresentable rather than merely discouraged.
    """
    stderr = _render_error("tracing.enabled=true", "tracing.endpoint=")

    # helm renders the schema path as `/tracing/endpoint`; the property that matters is that
    # the refusal NAMES the missing value rather than saying "invalid values" and stopping.
    assert "tracing" in stderr and "endpoint" in stderr, (
        f"the refusal must name the missing value, got: {stderr}"
    )


def test_the_template_refuses_too_when_schema_validation_is_skipped() -> None:
    """The schema rejects first, which would leave the template's own `fail` looking like dead
    code. It is not: `--skip-schema-validation` is a real flag, and this is the guard that still
    holds under it. Asserted rather than assumed, so the belt-and-braces is not decorative.
    """
    result = subprocess.run(
        [
            "helm",
            "template",
            _RELEASE,
            str(_CHART),
            "--set-string",
            _NATS,
            "--set",
            "tracing.enabled=true",
            "--set",
            "tracing.endpoint=",
            "--skip-schema-validation",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, "the template rendered an enabled exporter with no endpoint"
    assert "tracing.endpoint" in result.stderr


# --- the credential ------------------------------------------------------------------------


def test_headers_travel_by_secret_reference_and_never_as_a_literal() -> None:
    """The same invariant `test_deploy_time_credentials_travel_by_secret_reference_never_as_
    literals` holds for Tavily and object storage, extended to this credential.

    A manifest is readable by anything with `get` on it and is echoed by `kubectl describe`
    and `helm get manifest`.
    """
    secret = "signoz-access-token=super-secret-token"
    docs = _render(
        "tracing.enabled=true",
        "tracing.endpoint=http://collector:4318",
        f"tracing.headers={secret}",
    )

    env_from = _pool(docs)["spec"]["template"]["spec"]["containers"][0]["envFrom"]
    assert {"secretRef": {"name": f"{_FULLNAME}-tracing"}} in env_from
    assert "super-secret-token" not in yaml.safe_dump(_pool(docs)), (
        "the OTLP credential must never be a literal in the pool's env"
    )
    assert "super-secret-token" not in yaml.safe_dump(_runner_env(docs)), (
        "the OTLP credential must never reach a ConfigMap — it is world-readable with `get`"
    )


def test_the_credential_is_keyed_by_its_own_variable_name() -> None:
    """`envFrom.secretRef` injects keys under their OWN names and cannot rename, so the key
    must literally be the variable the exporter reads. `secret-tavily.yaml` learned this the
    breaking way; this follows the shape it ended at."""
    docs = _render(
        "tracing.enabled=true",
        "tracing.endpoint=http://collector:4318",
        "tracing.headers=k=v",
    )

    secret = _find(docs, "Secret", f"{_FULLNAME}-tracing")
    assert HEADERS_VAR in secret["stringData"]


def test_headers_are_optional_so_an_in_cluster_collector_needs_no_credential() -> None:
    """The likely production shape: SigNoz in the same cluster, reached over internal DNS with
    no credential and no Cloudflare Access at all. Demanding one — as `tavily.enabled` does —
    would block the most probable correct deployment."""
    docs = _render("tracing.enabled=true", "tracing.endpoint=http://collector.signoz:4318")

    assert _maybe(docs, "Secret", f"{_FULLNAME}-tracing") is None
    env_from = _pool(docs)["spec"]["template"]["spec"]["containers"][0]["envFrom"]
    assert {"secretRef": {"name": f"{_FULLNAME}-tracing"}} not in env_from


def test_an_existing_secret_suppresses_the_chart_created_one() -> None:
    """The recommended prod shape — supplied out-of-band or by External Secrets / Sealed
    Secrets, exactly as `tavily.existingSecret` works."""
    docs = _render(
        "tracing.enabled=true",
        "tracing.endpoint=http://collector:4318",
        "tracing.existingSecret=otlp-creds",
    )

    assert _maybe(docs, "Secret", f"{_FULLNAME}-tracing") is None
    env_from = _pool(docs)["spec"]["template"]["spec"]["containers"][0]["envFrom"]
    assert {"secretRef": {"name": "otlp-creds"}} in env_from


# --- the optional descriptive values ---------------------------------------------------------


def test_the_service_name_and_resource_attributes_reach_the_configmap() -> None:
    docs = _render(
        "tracing.enabled=true",
        "tracing.endpoint=http://collector:4318",
        "tracing.serviceName=sf-engine",
        "tracing.resourceAttributes=deployment.environment=dev",
    )

    data = _runner_env(docs)
    assert data[SERVICE_VAR] == "sf-engine"
    assert data[ATTRIBUTES_VAR] == "deployment.environment=dev"


def test_an_unset_service_name_is_ABSENT_rather_than_empty() -> None:
    """Rendering `""` OVERRIDES the code's own default with an empty string rather than leaving
    it unset — the trap `URL4_CLOUD_ARTIFACTS_DIR` documents in this same ConfigMap, where an
    empty path silently became the working directory.

    Here it would report every engine span under a blank service name, which in a tracing
    backend is indistinguishable from an unconfigured service.

    UNCHANGED by `OME-1190`. Its sibling assertion about `resourceAttributes` moved into the
    tests below, because the chart gained a MEANINGFUL default for that one — it knows the
    namespace, which the code cannot. There is no equivalent for the service name: the code
    already has the right default, so the chart's job is to stay out of the way.
    """
    data = _runner_env(_render("tracing.enabled=true", "tracing.endpoint=http://collector:4318"))

    assert SERVICE_VAR not in data


def test_resource_attributes_default_to_the_release_NAMESPACE() -> None:
    """OME-1190. Without this a preview environment's spans are indistinguishable from dev's:
    a direct OTLP export carries the app's OWN Resource, and the k8s collector's namespace
    enrichment applies to the LOGS it scrapes, not to spans an app posts itself."""
    data = _runner_env(_render_ns("sf-fusion"))

    assert data[ATTRIBUTES_VAR] == "deployment.environment=sf-fusion"


def test_the_namespace_attribute_is_DERIVED_not_a_fixed_string() -> None:
    """The assertion above would pass against a hardcoded `deployment.environment=sf-fusion`.
    Two namespaces rendering differently is what proves it is computed.

    It also pins the thing most likely to be got wrong: Helm does NOT template values files, so
    `{{ .Release.Namespace }}` written in values.yaml renders as that literal string.
    """
    dev = _runner_env(_render_ns("sf-fusion"))[ATTRIBUTES_VAR]
    preview = _runner_env(_render_ns("sf-preview-pr-999"))[ATTRIBUTES_VAR]

    assert dev != preview
    assert "{{" not in preview, "the values file was templated by hand and never evaluated"
    assert preview == "deployment.environment=sf-preview-pr-999"


def test_an_explicit_resource_attributes_value_still_wins() -> None:
    """A default an operator cannot override is a hardcode wearing a default's clothes."""
    data = _runner_env(_render_ns("sf-fusion", "tracing.resourceAttributes=team=platform"))

    assert data[ATTRIBUTES_VAR] == "team=platform"
