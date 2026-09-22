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
    """Render the chart and return its documents. Raises if helm refuses."""
    args = [
        "helm",
        "template",
        _RELEASE,
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
    ]
    args += extra
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _render_s3(*extra: str) -> list[dict[str, Any]]:
    """A deployment whose spill path is object storage — the shape the node tier needs.

    `artifactStorage.backend=s3` is what makes the runner and node share an artifact store;
    the S3 secrets only render in this shape, so the Secret wiring is asserted against it.
    """
    return _render(
        "--set",
        "artifactStorage.backend=s3",
        "--set-string",
        "artifactStorage.s3.endpointUrl=http://garage:3900",
        *extra,
    )


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
def test_the_metrics_port_is_exposed_beside_http() -> None:
    """The node serves `/metrics` on its single ASGI app, so the metrics port and the HTTP port
    are the same NUMBER — both are named so a scrape can target `metrics` and the Service can
    target `http`, and the number itself is `node.port` rather than a second source of truth."""
    docs = _render()
    container = _node_container(docs)
    ports = {p["name"]: p["containerPort"] for p in container["ports"]}

    assert ports["http"] == _values()["node"]["port"]
    assert ports["metrics"] == ports["http"]


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
    assert env["URL4_CLOUD_NODE_MAX_INFLIGHT_PER_WORKER"] == str(values["maxInflightPerWorker"])
    assert env["URL4_CLOUD_NODE_WORKERS"] == str(values["workers"])
    assert env["URL4_CLOUD_NODE_RETRY_AFTER_S"] == str(values["retryAfterS"])
    assert env["URL4_CLOUD_NODE_ARTIFACT_URL_TTL_S"] == str(values["artifactUrlTtlS"])
    assert env["URL4_CLOUD_NODE_PORT"] == str(values["port"])

    assert {"configMapRef": {"name": f"{_RELEASE}-{_RELEASE}-runner-env"}} in container["envFrom"]


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
    docs = _render_s3()
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
    docs = _render_s3(
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
