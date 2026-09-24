"""The node tier renders as a Deployment/Service/NetworkPolicy/PDB with App-only ingress.

FEATURE (unit 3, prd/03 §2.1, contracts.md C2): `screamingface-engine node` is the deployed
sync surface — the world built once, served over url4's admission and timeout guards. This is
the deployment half of that tier.

WHY render the chart and not only read the template text: `helm lint` reports success for a
chart that cannot render, and the properties that matter here (which pods a NetworkPolicy
selects, which peers its ingress admits, which Secret a pod actually references) are
STRUCTURAL — a text match cannot tell an ANDed selector pair from two ORed ones. That
distinction is the entire security value of the policy: contracts.md §10 says that without it
ANY pod in the cluster can set `X-User-Email` freely. So the assertions are against the
RENDERED manifest, the same precedent `test_chart_render_runner_pool.py` set.

WHAT IS NOT HERE: AC5's live check — from a pod that is not the App, assert the node Service
refuses the connection — is a deployment smoke check (test-plan §3, T15). This file proves the
POLICY IS CORRECTLY SHAPED; only a running cluster proves the CNI enforces it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "deploy" / "helm"
_RELEASE = "url4-cloud"

# The rendered object names derive from `<release>-<nameOverride>-...` because the chart pins
# `nameOverride: url4-cloud` (OME-876). Not a typo; see test_chart_identity.py.
_NODE_NAME = f"{_RELEASE}-{_RELEASE}-node"

# values-cloud.yaml deliberately leaves the chart-unknowable edge values empty (a Gateway name,
# a Cloudflare team/application). Placeholders, not deployment values — nothing is installed.
_CLOUD_ARGS = (
    "--values",
    str(_CHART / "values-cloud.yaml"),
    "--set",
    "gateway.parentRef.name=ci-placeholder-gateway",
    "--set",
    "gateway.cloudflareAccess.teamDomain=ci-placeholder.cloudflareaccess.com",
    "--set",
    "gateway.cloudflareAccess.audience=ci-placeholder-aud",
)


def _render(*extra: str) -> list[dict[str, Any]]:
    """Render the chart and return its documents. Raises if helm refuses.

    FX-86: `node.enabled` defaults to FALSE (the chart refuses it paired with any
    `artifactStorage.backend` other than `s3`, OME-929), so this helper turns the tier on AND
    supplies the s3 backend it requires — every test in this file is ABOUT the node tier, so
    that is the shape almost every one of them needs. A test of the OFF default overrides
    `node.enabled=false` explicitly; a test of the refusal itself calls `_render_raw`.
    """
    args = [
        "helm",
        "template",
        _RELEASE,
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
        "--set",
        "node.enabled=true",
        "--set",
        "artifactStorage.backend=s3",
        "--set-string",
        "artifactStorage.s3.endpointUrl=http://garage:3900",
    ]
    args += extra
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _render_raw(*extra: str) -> subprocess.CompletedProcess[str]:
    """Render with NO node/artifact defaults injected — for the off-switch and refusal tests,
    which are about what the chart does BEFORE anything opts the tier in. Does not raise; the
    caller reads `.returncode` and `.stderr` itself."""
    args = [
        "helm",
        "template",
        _RELEASE,
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
    ]
    args += extra
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _values() -> dict[str, Any]:
    return yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))


def _find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind} named {name!r} in the rendered chart")


def _app_pod(docs: list[dict[str, Any]]) -> dict[str, Any]:
    app = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}")
    return app["spec"]["template"]


def _node_pod(docs: list[dict[str, Any]]) -> dict[str, Any]:
    node = _find(docs, "Deployment", _NODE_NAME)
    return node["spec"]["template"]


def _node_container(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return _node_pod(docs)["spec"]["containers"][0]


def _app_container(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return _app_pod(docs)["spec"]["containers"][0]


# --- the Deployment --------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_node_deployment_runs_the_node_mode() -> None:
    """The container command is the `node` entry point (prd/03 §2.1). Pinned beside the
    Deployment that uses it: the entrypoint belongs to the image, and a values override could
    only name a mode the image does not have."""
    docs = _render()
    container = _node_container(docs)

    assert container["command"] == ["screamingface-engine", "node"]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_node_pod_is_hardened_and_needs_no_cluster_api() -> None:
    """The same hardening the App and runner pods carry: non-root 1000, read-only rootfs, all
    capabilities dropped, RuntimeDefault seccomp, /tmp emptyDir, no service-link env injection.
    The node talks to aigateway and S3, never the Kubernetes API, so no token is mounted."""
    docs = _render()
    pod = _node_pod(docs)["spec"]

    assert pod["automountServiceAccountToken"] is False
    assert pod["enableServiceLinks"] is False
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert {"name": "tmp", "emptyDir": {}} in pod["volumes"]

    container = _node_container(docs)
    sec = container["securityContext"]
    assert sec["allowPrivilegeEscalation"] is False
    assert sec["capabilities"] == {"drop": ["ALL"]}
    assert sec["runAsNonRoot"] is True
    assert sec["runAsUser"] == 1000
    assert sec["readOnlyRootFilesystem"] is True
    assert {"name": "tmp", "mountPath": "/tmp"} in container["volumeMounts"]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_readiness_gates_on_the_world_and_liveness_does_not_gate_on_a_downstream() -> None:
    """AC18: readiness reflects world built + collision guard — the node exposes that as
    `/readyz`, returning 503 while unready and on a failed guard. Liveness points at `/livez`,
    which answers unconditionally: PROBING A DOWNSTREAM FROM LIVENESS would restart a healthy
    pod whenever aigateway blinks, turning one outage into two (the risk AC19 exists to avoid)."""
    docs = _render()
    container = _node_container(docs)

    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert container["readinessProbe"]["httpGet"]["port"] == "http"
    assert container["livenessProbe"]["httpGet"]["path"] == "/livez"
    assert container["livenessProbe"]["httpGet"]["port"] == "http"
    assert container["livenessProbe"]["httpGet"]["path"] != "/readyz", (
        "liveness must not gate on readiness: a downstream outage would then restart every "
        "healthy node pod and make it worse"
    )


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_metrics_port_is_separate_from_http() -> None:
    """FX-82/RD2: `/metrics` moved OFF the request port, so a scrape can never compete with a
    sync call for the same listener, and a NetworkPolicy rule can admit a scraper to metrics
    ONLY. Both are still named so the Service can target `http` and a ServiceMonitor-style scrape
    can target `metrics`, but the two container ports are now DISTINCT numbers."""
    docs = _render()
    container = _node_container(docs)
    ports = {p["name"]: p["containerPort"] for p in container["ports"]}
    values = _values()["node"]

    assert ports["http"] == values["port"]
    assert ports["metrics"] == values["metrics"]["port"]
    assert ports["metrics"] != ports["http"]


# --- the Service and its selectors -----------------------------------------------------------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_node_service_routes_only_to_node_pods() -> None:
    """The node shares the App's `app.kubernetes.io/name` (so aigateway's ingress admits its
    calls) but adds `component: node`, and the Service selector carries that component — without
    it the Service would also front the App's pods."""
    docs = _render()
    service = _find(docs, "Service", _NODE_NAME)
    selector = service["spec"]["selector"]

    assert (
        selector["app.kubernetes.io/name"]
        == _node_pod(docs)["metadata"]["labels"]["app.kubernetes.io/name"]
    )
    assert selector["app.kubernetes.io/component"] == "node"
    port = service["spec"]["ports"][0]
    assert port["targetPort"] == "http"
    assert port["port"] == _values()["node"]["service"]["port"]


# --- the NetworkPolicy: the correctness requirement (AC5) ------------------------------------


def _admitted_node_peers(policy: dict[str, Any]) -> list[dict[str, Any]]:
    """The ingress peers of the node policy, keeping each `from` element whole.

    A `from` element carrying a `podSelector` WITHOUT a `namespaceSelector` matches that label
    in every namespace, and one carrying only a `namespaceSelector` matches every pod in the
    namespace. Both are wider than "the App", so this returns the raw elements and the test
    asserts the pairing explicitly — which a grep could not.
    """
    return [element for rule in policy["spec"]["ingress"] for element in rule.get("from", [])]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize("prod_like", [False, True])
def test_the_network_policy_selects_node_pods_and_admits_only_the_app(
    prod_like: bool,
) -> None:
    """AC5 + contracts.md §10: without this policy any pod in the cluster can set
    `X-User-Email` freely and impersonate a caller, so it is a correctness requirement.

    Asserted for the default values AND the cloud posture, because the cloud file is what
    actually deploys and an override must not quietly widen the peer set.
    """
    docs = _render(*_CLOUD_ARGS) if prod_like else _render()
    policy = _find(docs, "NetworkPolicy", _NODE_NAME)
    node_labels = _node_pod(docs)["metadata"]["labels"]

    # The policy targets the NODE pods only (component: node), never the App or runner.
    selector = policy["spec"]["podSelector"]["matchLabels"]
    assert selector == {
        "app.kubernetes.io/name": node_labels["app.kubernetes.io/name"],
        "app.kubernetes.io/instance": node_labels["app.kubernetes.io/instance"],
        "app.kubernetes.io/component": "node",
    }
    assert policy["spec"]["policyTypes"] == ["Ingress"], (
        "the node dials aigateway and S3 on unrestricted egress; only ingress needs narrowing"
    )

    peers = _admitted_node_peers(policy)
    assert peers, "a policy with no `from:` admits every source — the opposite of the point"

    app_labels = _app_pod(docs)["metadata"]["labels"]
    for element in peers:
        pod = element.get("podSelector", {}).get("matchLabels", {})
        ns = element.get("namespaceSelector", {}).get("matchLabels", {})
        assert ns.get("kubernetes.io/metadata.name"), (
            "each peer must pair its namespaceSelector with its podSelector: two elements are "
            "ORed, so splitting them would admit every pod in the namespace"
        )
        # The peer's labels must be a subset of the labels the App pods ACTUALLY carry.
        assert pod and all(app_labels.get(key) == value for key, value in pod.items()), (
            f"the admitted peer {pod!r} is not a label set the App pods carry {app_labels!r}"
        )
        # And it must NOT be shaped like a runner pod — the pool must not be admitted.
        assert pod.get("app.kubernetes.io/component") != "runner"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_node_network_policy_excludes_the_runner_pool() -> None:
    """The runner pool carries its OWN `app.kubernetes.io/name: url4-runner`. If the peer matched
    only the namespace, or the node pods were selected by name alone, the pool would be admitted
    too — an in-cluster workload that sets `X-User-Email` as freely as anything else."""
    docs = _render()
    policy = _find(docs, "NetworkPolicy", _NODE_NAME)
    runner_labels = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")["spec"]["template"][
        "metadata"
    ]["labels"]

    for element in _admitted_node_peers(policy):
        pod = element.get("podSelector", {}).get("matchLabels", {})
        for key, value in runner_labels.items():
            assert not (pod.get(key) == value and key == "app.kubernetes.io/name"), (
                f"the node policy admits the runner pool via {key}={value}"
            )


# --- the PodDisruptionBudget -----------------------------------------------------------------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_pod_disruption_budget_selects_node_pods() -> None:
    """`maxUnavailable: 1` SERIALIZES voluntary disruptions, the same rationale as the runner
    pool's budget: a PDB cannot see request occupancy, so 0 is a placebo at one replica and a
    permanent eviction deadlock at any other. The node is stateless, so one-at-a-time is safe."""
    docs = _render()
    pdb = _find(docs, "PodDisruptionBudget", _NODE_NAME)
    labels = _node_pod(docs)["metadata"]["labels"]

    assert pdb["spec"]["maxUnavailable"] == 1
    assert pdb["spec"]["selector"]["matchLabels"] == {
        "app.kubernetes.io/name": labels["app.kubernetes.io/name"],
        "app.kubernetes.io/instance": labels["app.kubernetes.io/instance"],
        "app.kubernetes.io/component": "node",
    }


# --- the env, the ladder, and the secrets ----------------------------------------------------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_node_env_carries_the_ladder_and_reuses_the_shared_deploy_time_config() -> None:
    """Every ladder number is rendered from the chart into the tier's own `URL4_CLOUD_NODE_*`
    env, so an operator can tune a budget without a rebuild. The aigateway address and artifact
    settings arrive from the SAME `-runner-env` ConfigMap the worker pool reads, so the two
    halves cannot be pointed at different aigateway or store by a one-sided edit."""
    docs = _render()
    values = _values()["node"]
    container = _node_container(docs)
    env = {entry["name"]: entry["value"] for entry in container["env"]}

    assert env["URL4_CLOUD_NODE_REQUEST_TIMEOUT_S"] == str(values["requestTimeoutS"])
    assert env["URL4_CLOUD_NODE_AIGATEWAY_TIMEOUT_S"] == str(values["aigatewayTimeoutS"])
    assert env["URL4_CLOUD_NODE_SPILL_TIMEOUT_S"] == str(values["spillTimeoutS"])
    assert env["URL4_CLOUD_NODE_MAX_INFLIGHT_PER_WORKER"] == str(values["maxInflightPerWorker"])
    assert env["URL4_CLOUD_NODE_WORKERS"] == str(values["workers"])
    assert env["URL4_CLOUD_NODE_RETRY_AFTER_S"] == str(values["retryAfterS"])
    assert env["URL4_CLOUD_NODE_ARTIFACT_URL_TTL_S"] == str(values["artifactUrlTtlS"])
    assert env["URL4_CLOUD_NODE_PORT"] == str(values["port"])
    assert env["URL4_CLOUD_NODE_METRICS_PORT"] == str(values["metrics"]["port"])
    # FX-85: rendered as a PLAIN integer string. Helm decodes values.yaml through JSON, so a
    # large whole number arrives as float64, and a bare `quote` would emit scientific notation
    # (`6.7108864e+07`) that no Settings byte-size field can parse.
    assert env["URL4_CLOUD_RESULT_HARD_CAP_BYTES"] == str(values["resultHardCapBytes"])
    assert "e+" not in env["URL4_CLOUD_RESULT_HARD_CAP_BYTES"]

    assert {"configMapRef": {"name": f"{_RELEASE}-{_RELEASE}-runner-env"}} in container["envFrom"]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_app_forward_timeout_is_derived_from_the_nodes_own_ladder() -> None:
    """FX-83/§2.2: `URL4_CLOUD_NODE_FORWARD_TIMEOUT_S` is `requestTimeoutS + spillTimeoutS + 1`,
    rendered from the node's OWN values rather than carrying a second literal that could drift
    from the ladder the node tier actually enforces."""
    docs = _render()
    values = _values()["node"]
    configmap = _find(docs, "ConfigMap", f"{_RELEASE}-{_RELEASE}")

    expected = values["requestTimeoutS"] + values["spillTimeoutS"] + 1
    assert configmap["data"]["URL4_CLOUD_NODE_FORWARD_TIMEOUT_S"] == str(expected)


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_startup_probe_covers_the_world_build() -> None:
    """FX-88: `/livez` on `http`, with `periodSeconds x failureThreshold >= 120s` so a large
    declared world has room to build before EITHER steady-state probe starts counting failures."""
    docs = _render()
    container = _node_container(docs)
    probe = container["startupProbe"]

    assert probe["httpGet"]["path"] == "/livez"
    assert probe["httpGet"]["port"] == "http"
    assert probe["periodSeconds"] * probe["failureThreshold"] >= 120


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_app_rolls_when_the_signing_secret_rotates_only_with_the_node_on() -> None:
    """FX-81: the App VERIFIES the node's signed 303 with this Secret (OQ-3.2), so a rotated key
    must roll the App too. With the node off there is no signer, so there is nothing to roll
    for, and the annotation must not appear at all."""
    with_node = _find(_render(), "Deployment", f"{_RELEASE}-{_RELEASE}")
    assert "checksum/artifact-signing" in with_node["spec"]["template"]["metadata"]["annotations"]

    without_node = _find(
        _render("--set", "node.enabled=false"), "Deployment", f"{_RELEASE}-{_RELEASE}"
    )
    assert (
        "checksum/artifact-signing"
        not in without_node["spec"]["template"]["metadata"]["annotations"]
    )


# --- FX-80/FX-90: every selector matches exactly its own Deployment's pod template -----------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize("prod_like", [False, True])
def test_every_selector_matches_exactly_its_own_deployment(prod_like: bool) -> None:
    """The bug this closes: the node used to share the App's {name, instance} pair, so the App's
    OWN Service and Deployment selectors — a plain {name, instance}, no component — were a
    SUPERSET match for the node's pods too, silently routing public traffic (and eviction churn)
    to a tier that was never meant to receive either."""
    docs = _render(*_CLOUD_ARGS) if prod_like else _render()
    pods = {
        doc["metadata"]["name"]: doc["spec"]["template"]["metadata"]["labels"]
        for doc in docs
        if doc.get("kind") == "Deployment"
    }
    app_name = f"{_RELEASE}-{_RELEASE}"
    runner_name = f"{_RELEASE}-{_RELEASE}-runner"
    owners = {
        ("Service", app_name): app_name,
        ("Service", _NODE_NAME): _NODE_NAME,
        ("Deployment", app_name): app_name,
        ("Deployment", runner_name): runner_name,
        ("Deployment", _NODE_NAME): _NODE_NAME,
        ("PodDisruptionBudget", _NODE_NAME): _NODE_NAME,
        ("NetworkPolicy", _NODE_NAME): _NODE_NAME,
    }

    for (kind, name), owner in owners.items():
        doc = _find(docs, kind, name)
        if kind == "Service":
            selector = doc["spec"]["selector"]
        elif kind == "NetworkPolicy":
            selector = doc["spec"]["podSelector"]["matchLabels"]
        else:
            selector = doc["spec"]["selector"]["matchLabels"]
        for deployment_name, pod_labels in pods.items():
            matches = all(pod_labels.get(k) == v for k, v in selector.items())
            if deployment_name == owner:
                assert matches, f"{kind}/{name} does not even match its own pods {pod_labels!r}"
            else:
                assert not matches, (
                    f"{kind}/{name} ALSO matches {deployment_name}'s pods {pod_labels!r} — a "
                    "stray selector"
                )


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_node_instance_label_differs_from_the_apps() -> None:
    """FX-80/§2.5 directly: the node keeps `name: url4-cloud` (aigateway admits by that name) but
    uses `instance: <release>-node`, never the App's own `<release>`."""
    docs = _render()
    node_labels = _node_pod(docs)["metadata"]["labels"]
    app_labels = _app_pod(docs)["metadata"]["labels"]

    assert node_labels["app.kubernetes.io/name"] == app_labels["app.kubernetes.io/name"]
    assert node_labels["app.kubernetes.io/instance"] == f"{_RELEASE}-node"
    assert node_labels["app.kubernetes.io/instance"] != app_labels["app.kubernetes.io/instance"]


# --- FX-82: /metrics on its own port, admitted by an independent, opt-in ingress rule ---------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_no_metrics_scrape_peer_by_default() -> None:
    """`node.metrics.scrapeFrom` defaults to `[]`, which must render NO second ingress rule at
    all — metrics is then reachable from nowhere else in the cluster, the safe default for a
    port nothing scrapes yet."""
    docs = _render()
    policy = _find(docs, "NetworkPolicy", _NODE_NAME)

    assert len(policy["spec"]["ingress"]) == 1


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_a_configured_metrics_scrape_peer_is_admitted_to_the_metrics_port_only() -> None:
    docs = _render(
        "--set-string",
        r"node.metrics.scrapeFrom[0].namespaceSelector.matchLabels.kubernetes\.io/metadata\.name=monitoring",
        "--set-string",
        r"node.metrics.scrapeFrom[0].podSelector.matchLabels.app\.kubernetes\.io/name=prometheus",
    )
    policy = _find(docs, "NetworkPolicy", _NODE_NAME)
    values = _values()["node"]

    assert len(policy["spec"]["ingress"]) == 2
    scrape_rule = next(
        rule
        for rule in policy["spec"]["ingress"]
        if any(p["port"] == values["metrics"]["port"] for p in rule["ports"])
    )
    assert all(p["port"] == values["metrics"]["port"] for p in scrape_rule["ports"])
    peer = scrape_rule["from"][0]
    assert peer["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "monitoring"
    assert peer["podSelector"]["matchLabels"]["app.kubernetes.io/name"] == "prometheus"


# --- FX-86: the chart refuses node.enabled without an s3 artifact backend ---------------------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_node_is_disabled_by_default() -> None:
    """FX-86: the default posture needs no `--set` at all to prove it — a bare render (no s3, no
    node.enabled) must not even ATTEMPT to render the node objects."""
    result = _render_raw()
    assert result.returncode == 0, result.stderr
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    names = {doc.get("metadata", {}).get("name") for doc in docs}
    assert _NODE_NAME not in names


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_node_enabled_without_s3_backend_is_refused() -> None:
    """FX-86/OME-929: the spill path writes an over-cap sync result to the SAME store the App
    reads it back from across pods, so any backend other than `s3` leaves it unservable — the
    chart refuses at render time rather than deploying a tier that fails on its first spill."""
    result = _render_raw("--set", "node.enabled=true")

    assert result.returncode != 0
    assert "OME-929" in result.stderr


# --- FX-83: the chart refuses an unsafe timeout ladder or an unsafe grace period ---------------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_node_refuses_an_aigateway_timeout_at_or_above_the_request_timeout() -> None:
    result = _render_raw(
        "--set",
        "node.enabled=true",
        "--set",
        "artifactStorage.backend=s3",
        "--set-string",
        "artifactStorage.s3.endpointUrl=http://garage:3900",
        "--set",
        "node.aigatewayTimeoutS=30",
    )
    assert result.returncode != 0
    assert "node.requestTimeoutS" in result.stderr


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_node_refuses_a_termination_grace_period_too_small_for_the_ladder() -> None:
    result = _render_raw(
        "--set",
        "node.enabled=true",
        "--set",
        "artifactStorage.backend=s3",
        "--set-string",
        "artifactStorage.s3.endpointUrl=http://garage:3900",
        "--set",
        "node.terminationGracePeriodSeconds=38",
    )
    assert result.returncode != 0
    assert "node.spillTimeoutS" in result.stderr


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_node_refuses_a_metrics_port_equal_to_the_request_port() -> None:
    """Review round #8: the node itself does not validate this at startup, so the chart is the
    ONLY place that can catch it — a collision would silently defeat FX-82's whole point (a
    scrape competing with request traffic on one listener, and a NetworkPolicy rule that cannot
    distinguish the two)."""
    result = _render_raw(
        "--set",
        "node.enabled=true",
        "--set",
        "artifactStorage.backend=s3",
        "--set-string",
        "artifactStorage.s3.endpointUrl=http://garage:3900",
        "--set",
        "node.metrics.port=9109",
    )
    assert result.returncode != 0
    assert "node.metrics.port" in result.stderr


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_node_refuses_a_hard_cap_below_the_inline_cap() -> None:
    """Review round #8: the node refuses this at STARTUP (world/node_tier's own validation);
    failing at render time means a misconfigured value never reaches a running pod at all."""
    result = _render_raw(
        "--set",
        "node.enabled=true",
        "--set",
        "artifactStorage.backend=s3",
        "--set-string",
        "artifactStorage.s3.endpointUrl=http://garage:3900",
        "--set",
        "node.resultHardCapBytes=1000",
    )
    assert result.returncode != 0
    assert "node.resultHardCapBytes" in result.stderr


# --- FX-87: no duplicated app.kubernetes.io/component key on any node object -------------------


class _StrictDuplicateKeyLoader(yaml.SafeLoader):
    """A SafeLoader that RAISES on a duplicate mapping key instead of silently keeping the last
    occurrence — the default `yaml.safe_load` behavior, and exactly the behavior that let a
    genuine duplicate `app.kubernetes.io/component` key through unnoticed (FX-87). Sourced
    inline rather than adding a `ruamel.yaml` dependency for one test."""


def _no_duplicate_keys(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None, f"found duplicate key {key!r}", node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_StrictDuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "template_path",
    [
        "deployment-node.yaml",
        "service-node.yaml",
        "networkpolicy-node.yaml",
        "poddisruptionbudget-node.yaml",
        "secret-artifact-signing.yaml",
    ],
)
def test_node_object_labels_have_no_duplicate_component_key(template_path: str) -> None:
    """`screamingface-engine.labels` already resolves `component: control-plane`; every node
    template used to append `component: node` right after it, a genuine YAML duplicate mapping
    key. Most parsers silently keep the LAST occurrence (which happened to be correct here), but
    that is luck, not a contract — a strict loader that REJECTS a duplicate is the only check
    that would have caught it, and the only one immune to a future reorder swapping it back."""
    result = _render_raw(
        "--set",
        "node.enabled=true",
        "--set",
        "artifactStorage.backend=s3",
        "--set-string",
        "artifactStorage.s3.endpointUrl=http://garage:3900",
        "--show-only",
        f"templates/{template_path}",
    )
    assert result.returncode == 0, result.stderr
    try:
        list(yaml.load_all(result.stdout, Loader=_StrictDuplicateKeyLoader))
    except yaml.constructor.ConstructorError as exc:
        pytest.fail(f"{template_path}: duplicate mapping key in rendered YAML: {exc}")


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_app_is_pointed_at_the_node_service_so_the_forwarder_arms() -> None:
    """D6: the App forwards known mounts to the node Service. `URL4_CLOUD_NODE_BASE_URL` is the
    one switch that arms the forwarder; unset, the App would answer every mount itself and the
    node tier would receive no traffic."""
    docs = _render()
    configmap = _find(docs, "ConfigMap", f"{_RELEASE}-{_RELEASE}")
    values = _values()["node"]

    assert configmap["data"]["URL4_CLOUD_NODE_BASE_URL"] == (
        f"http://{_NODE_NAME}:{values['service']['port']}"
    )


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_both_secrets_are_referenced_by_the_node_pod_and_the_signing_key_is_shared() -> None:
    """The spill path needs the S3 credential pair, and OQ-3.2 needs one HMAC key BOTH tiers
    read — the node signs the 303, the App verifies. A Secret that reaches only one tier means
    every redirect is unfetchable (verify fails) or every spill is refused (no signer)."""
    docs = _render()
    node_container = _node_container(docs)
    app_container = _app_container(docs)

    signing_secret = _find(docs, "Secret", f"{_RELEASE}-{_RELEASE}-artifact-signing")
    assert "URL4_CLOUD_ARTIFACT_SIGNING_KEY" in signing_secret["stringData"]

    expected = [
        {"secretRef": {"name": f"{_RELEASE}-{_RELEASE}-artifact-storage"}},
        {"secretRef": {"name": f"{_RELEASE}-{_RELEASE}-artifact-signing"}},
    ]
    for ref in expected:
        assert ref in node_container["envFrom"], f"the node pod never references {ref}"
    assert {"secretRef": {"name": f"{_RELEASE}-{_RELEASE}-artifact-signing"}} in (
        app_container["envFrom"]
    ), "the App must receive the SAME signing key to verify the node's 303 redirect"

    # The signing key is authorization material: it must never be a literal in a workload.
    assert "URL4_CLOUD_ARTIFACT_SIGNING_KEY" not in yaml.safe_dump(node_container["env"])
    assert "URL4_CLOUD_ARTIFACT_SIGNING_KEY" not in yaml.safe_dump(app_container["env"])


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_an_existing_signing_secret_is_used_verbatim() -> None:
    """The prod shape: an operator (or an External Secrets flow) owns the Secret, so the chart
    references it by name and renders none of its own — and BOTH tiers still get it."""
    docs = _render(
        "--set-string",
        "artifactSigning.existingSecret=my-signing-secret",
    )

    assert not any(
        doc.get("kind") == "Secret"
        and doc.get("metadata", {}).get("name") == f"{_RELEASE}-{_RELEASE}-artifact-signing"
        for doc in docs
    ), "existingSecret means the chart does not own the object"
    for container in (_node_container(docs), _app_container(docs)):
        assert {"secretRef": {"name": "my-signing-secret"}} in container["envFrom"]


# --- the off switch --------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_component_label_the_policy_depends_on_cannot_be_overridden_away() -> None:
    """INVARIANT: the App's `component: control-plane` is CHART-OWNED, because the node's
    NetworkPolicy peer is the only thing standing between the cluster and an impersonated
    caller. A platform that sets `podLabels` — a real, observed cause of a zero-endpoint
    outage in the aigateway chart — must not be able to render a pod whose label no longer
    matches the peer, which would silently lock the App out of the node."""
    docs = _render(
        "--set-string",
        "podLabels.app\\.kubernetes\\.io/component=something-else",
    )
    app_labels = _app_pod(docs)["metadata"]["labels"]

    assert app_labels["app.kubernetes.io/component"] == "control-plane"
    policy = _find(docs, "NetworkPolicy", _NODE_NAME)
    node_peer = next(
        element["podSelector"]["matchLabels"]
        for element in _admitted_node_peers(policy)
        if element.get("podSelector")
    )
    assert all(app_labels.get(key) == value for key, value in node_peer.items())


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_node_tier_can_be_disabled_and_then_the_app_has_no_forwarder() -> None:
    """A deliberate off switch: with the tier disabled, none of its objects render and the App
    is left with no node base URL, so the forwarder is never mounted (config.py gates on it)."""
    docs = _render("--set", "node.enabled=false")
    names = {doc.get("metadata", {}).get("name") for doc in docs}

    assert _NODE_NAME not in names
    configmap = _find(docs, "ConfigMap", f"{_RELEASE}-{_RELEASE}")
    assert "URL4_CLOUD_NODE_BASE_URL" not in configmap["data"]


# --- review round #1: the documented enable command actually renders -------------------------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_documented_enable_command_renders() -> None:
    """The README and NOTES.txt both tell an operator to run
    `--set node.enabled=true --set artifactStorage.backend=s3 --set garage.enabled=true`.
    `artifactStorage.backend=s3` alone does not render (the chart also needs to know WHERE the
    store is), so this pins the EXACT documented command against a regression the other tests
    would not catch — they all supply an explicit `artifactStorage.s3.endpointUrl` instead."""
    result = _render_raw(
        "--set",
        "node.enabled=true",
        "--set",
        "artifactStorage.backend=s3",
        "--set",
        "garage.enabled=true",
    )
    assert result.returncode == 0, result.stderr
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    assert _find(docs, "Deployment", _NODE_NAME)


# --- review round #2: the signing checksum is keyed on the key's SOURCE, not the rendered Secret


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_signing_checksum_is_stable_across_independent_renders() -> None:
    """With neither `signingKey` nor `existingSecret` set, `secret-artifact-signing.yaml`'s
    `lookup` is empty under `helm template` (no live cluster), so it falls back to
    `randAlphaNum` — a NEW value on every render. Hashing THAT (the original, wrong, approach)
    would roll the App and the node on every offline/GitOps render even though nothing about the
    key changed. The checksum must be identical across two INDEPENDENT render invocations."""
    first = _find(_render(), "Deployment", f"{_RELEASE}-{_RELEASE}")
    second = _find(_render(), "Deployment", f"{_RELEASE}-{_RELEASE}")

    checksum_1 = first["spec"]["template"]["metadata"]["annotations"]["checksum/artifact-signing"]
    checksum_2 = second["spec"]["template"]["metadata"]["annotations"]["checksum/artifact-signing"]
    assert checksum_1 == checksum_2


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_signing_checksum_matches_between_app_and_node() -> None:
    """Both tiers must roll TOGETHER on a real rotation — a checksum that diverges between them
    would either miss a roll on one side or force one on a render where nothing changed."""
    docs = _render()
    app = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}")
    node = _find(docs, "Deployment", _NODE_NAME)

    app_checksum = app["spec"]["template"]["metadata"]["annotations"]["checksum/artifact-signing"]
    node_checksum = node["spec"]["template"]["metadata"]["annotations"]["checksum/artifact-signing"]
    assert app_checksum == node_checksum


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_signing_checksum_changes_when_the_pinned_key_changes() -> None:
    """A REAL rotation — an operator changing `signingKey` (or `existingSecret`) — must still
    roll both tiers; only the chart-generated/no-cluster case is deliberately insensitive to a
    per-render difference."""
    docs = _find(_render(), "Deployment", f"{_RELEASE}-{_RELEASE}")
    baseline = docs["spec"]["template"]["metadata"]["annotations"]["checksum/artifact-signing"]

    pinned_a = _find(
        _render("--set-string", "artifactSigning.signingKey=key-a"),
        "Deployment",
        f"{_RELEASE}-{_RELEASE}",
    )["spec"]["template"]["metadata"]["annotations"]["checksum/artifact-signing"]
    pinned_b = _find(
        _render("--set-string", "artifactSigning.signingKey=key-b"),
        "Deployment",
        f"{_RELEASE}-{_RELEASE}",
    )["spec"]["template"]["metadata"]["annotations"]["checksum/artifact-signing"]

    assert pinned_a != baseline
    assert pinned_a != pinned_b
    # Pinning the SAME key across independent renders must still be stable.
    pinned_a_again = _find(
        _render("--set-string", "artifactSigning.signingKey=key-a"),
        "Deployment",
        f"{_RELEASE}-{_RELEASE}",
    )["spec"]["template"]["metadata"]["annotations"]["checksum/artifact-signing"]
    assert pinned_a == pinned_a_again


# --- review round #3: `instance: <release>-node` is scoped to selectors, never object metadata -


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("kind", "name"),
    [
        ("Deployment", _NODE_NAME),
        ("Service", _NODE_NAME),
        ("NetworkPolicy", _NODE_NAME),
        ("PodDisruptionBudget", _NODE_NAME),
    ],
)
def test_node_object_metadata_uses_the_release_instance(kind: str, name: str) -> None:
    """§2.5's `instance: <release>-node` fix is a SELECTOR concern — the App's own Service and
    Deployment select on a bare {name, instance}. Object `metadata.labels` is not a selector, so
    it keeps the RELEASE's own instance: `kubectl get -l app.kubernetes.io/instance=<release>`
    must still find the node's own Service/PDB/NetworkPolicy/Deployment, not only the App."""
    doc = _find(_render(), kind, name)

    assert doc["metadata"]["labels"]["app.kubernetes.io/instance"] == _RELEASE
    assert doc["metadata"]["labels"]["app.kubernetes.io/component"] == "node"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_shared_signing_secret_is_not_tagged_as_the_nodes() -> None:
    """The signing Secret is SHARED — the node signs with it, the App verifies with it — so it
    belongs to neither tier alone. Tagging it `component: node` would be a lie the same way
    `component: control-plane` would be; it gets the release's own instance and no node-only
    component."""
    secret = _find(_render(), "Secret", f"{_RELEASE}-{_RELEASE}-artifact-signing")

    assert secret["metadata"]["labels"]["app.kubernetes.io/instance"] == _RELEASE
    assert secret["metadata"]["labels"]["app.kubernetes.io/component"] != "node"


# --- review round #5: podLabels can neither hijack an identity label nor duplicate a key -------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "hijacked_key",
    ["app.kubernetes.io/component", "app.kubernetes.io/instance", "app.kubernetes.io/name"],
)
def test_node_pod_labels_cannot_hijack_an_identity_label(hijacked_key: str) -> None:
    """`podLabels` is OMITTED of every chart-owned identity key before it is merged in (not
    merely rendered after it) — an operator's own copy of one of these keys must neither win NOR
    survive as a duplicate mapping key alongside the chart's own value."""
    escaped = hijacked_key.replace(".", r"\.").replace("/", r"\/")
    docs = _render("--set-string", f"podLabels.{escaped}=hijacked")
    pod_labels = _node_pod(docs)["metadata"]["labels"]

    assert pod_labels[hijacked_key] != "hijacked"
    # And the pod must still match its own Deployment selector and Service selector.
    deployment = _find(docs, "Deployment", _NODE_NAME)
    assert all(
        pod_labels.get(k) == v for k, v in deployment["spec"]["selector"]["matchLabels"].items()
    )
    service = _find(docs, "Service", _NODE_NAME)
    assert all(pod_labels.get(k) == v for k, v in service["spec"]["selector"].items())


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "hijacked_key",
    ["app.kubernetes.io/component", "app.kubernetes.io/instance"],
)
def test_node_pod_labels_hijack_attempt_renders_no_duplicate_key(hijacked_key: str) -> None:
    """The `omit` is what stops a hijack attempt from becoming a genuine YAML duplicate mapping
    key (the same class FX-87 fixed) — checked with the strict, duplicate-key-rejecting loader
    rather than trusting `yaml.safe_load`'s silent last-value-wins behavior."""
    escaped = hijacked_key.replace(".", r"\.").replace("/", r"\/")
    result = _render_raw(
        "--set",
        "node.enabled=true",
        "--set",
        "artifactStorage.backend=s3",
        "--set-string",
        "artifactStorage.s3.endpointUrl=http://garage:3900",
        "--set-string",
        f"podLabels.{escaped}=hijacked",
        "--show-only",
        "templates/deployment-node.yaml",
    )
    assert result.returncode == 0, result.stderr
    try:
        list(yaml.load_all(result.stdout, Loader=_StrictDuplicateKeyLoader))
    except yaml.constructor.ConstructorError as exc:
        pytest.fail(f"duplicate mapping key with podLabels.{hijacked_key} set: {exc}")


# --- review round #6: pytest equivalents of two verify_chart_wiring.py-only checks -------------


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_network_policy_peer_does_not_match_the_nodes_own_pods() -> None:
    """FX-90: the App-only peer (`component: control-plane`) must not ALSO match the node's own
    pod template — if it did, the node's own pods could reach each other's request port under
    the guise of being "the App", which defeats the point of naming a peer at all."""
    docs = _render()
    policy = _find(docs, "NetworkPolicy", _NODE_NAME)
    node_labels = _node_pod(docs)["metadata"]["labels"]

    peer = next(
        element["podSelector"]["matchLabels"]
        for element in _admitted_node_peers(policy)
        if element.get("podSelector")
    )
    assert not all(node_labels.get(k) == v for k, v in peer.items())


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_node_pod_labels_component_survives_a_podlabels_override() -> None:
    """FX-84, the node's own mirror of the App's identical rule: `podLabels` renders BEFORE the
    chart-owned `component`/`part-of`, so an operator's override can add a label but never
    rewrite which selector the node's own pods match."""
    docs = _render(
        "--set-string",
        "podLabels.app\\.kubernetes\\.io/component=platform-convention",
    )
    node_labels = _node_pod(docs)["metadata"]["labels"]

    assert node_labels["app.kubernetes.io/component"] == "node"
    policy = _find(docs, "NetworkPolicy", _NODE_NAME)
    assert policy["spec"]["podSelector"]["matchLabels"]["app.kubernetes.io/component"] == "node"
    assert all(
        node_labels.get(k) == v for k, v in policy["spec"]["podSelector"]["matchLabels"].items()
    )
