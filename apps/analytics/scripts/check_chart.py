# /// script
# dependencies = ["pyyaml"]
# ///
"""Render and check deployment wiring; never contact a cluster."""

import subprocess
from pathlib import Path

import yaml

chart = Path(__file__).resolve().parents[1] / "charts" / "analytics"
base = ["helm", "template", "check", str(chart), "--set", "image.tag=ci"]
for enabled in (False, True):
    command = base.copy()
    if enabled:
        command.extend(
            [
                "--set",
                "analytics.enabled=true,analytics.existingSecret=test-secret",
                "--set",
                "analytics.posthogHost=https://posthog.example",
                "--set",
                "analytics.allowedHosts=posthog.example",
                "--set",
                "ingress.enabled=true,ingress.className=test,ingress.host=analytics.example",
                "--set",
                "ingress.tlsSecretName=test-tls",
            ]
        )
    docs = list(yaml.safe_load_all(subprocess.check_output(command, text=True)))
    objects = {item["kind"]: item for item in docs if item}
    deploy, service = objects["Deployment"], objects["Service"]
    pod = deploy["spec"]["template"]
    assert service["spec"]["selector"] == pod["metadata"]["labels"]
    container = pod["spec"]["containers"][0]
    assert container["ports"][0]["containerPort"] == 9110
    assert service["spec"]["ports"][0]["targetPort"] == "http"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    # INVARIANT: link variables never reach an ANALYTICS_-prefixed, extra-forbidding Settings.
    assert pod["spec"]["enableServiceLinks"] is False
    assert "nodeSelector" not in pod["spec"] and "tolerations" not in pod["spec"]
    env = {value["name"]: value for value in container["env"]}
    assert env["ANALYTICS_ENABLED"]["value"] == str(enabled).lower()
    if enabled:
        token = env["ANALYTICS_POSTHOG_PROJECT_TOKEN"]
        assert token["valueFrom"]["secretKeyRef"]["name"] == "test-secret"
        route = objects["Ingress"]["spec"]["rules"][0]["http"]["paths"][0]
        assert route["path"] == "/v1/events" and route["pathType"] == "Exact"
        assert route["backend"]["service"]["name"] == service["metadata"]["name"]
    else:
        assert "ANALYTICS_POSTHOG_PROJECT_TOKEN" not in env and "Ingress" not in objects
placed = subprocess.check_output(
    base + ["--set", "nodeSelector.pool=tenant", "--set", "tolerations[0].key=workload"], text=True
)
spec = next(
    item["spec"]["template"]["spec"]
    for item in yaml.safe_load_all(placed)
    if item and item["kind"] == "Deployment"
)
assert spec["nodeSelector"] == {"pool": "tenant"}
assert spec["tolerations"] == [{"key": "workload"}]
print("PASS: chart wiring, secret references, ingress route, service links and placement")

# FEATURE: bridge routes and settings are opt-in alongside existing intake.
bridge_command = base + [
    "--set",
    "analytics.bridge.enabled=true",
    "--set",
    "analytics.bridge.origin=https://analytics.example",
    "--set",
    "analytics.bridge.parentOrigins=https://output.example",
    "--set",
    "analytics.bridge.ancestorOrigins=https://notebook.example",
    "--set",
    "ingress.enabled=true,ingress.className=test,ingress.host=analytics.example",
    "--set",
    "ingress.tlsSecretName=test-tls",
]
bridge_objects = {
    doc["kind"]: doc
    for doc in yaml.safe_load_all(subprocess.check_output(bridge_command, text=True))
    if doc
}
bridge_env = {
    e["name"]: e["value"]
    for e in bridge_objects["Deployment"]["spec"]["template"]["spec"]["containers"][0]["env"]
}
assert bridge_env["ANALYTICS_BRIDGE_ENABLED"] == "true"
assert bridge_env["ANALYTICS_BRIDGE_ORIGIN"] == "https://analytics.example"
assert bridge_env["ANALYTICS_BRIDGE_PARENT_ORIGINS"] == "https://output.example"
assert bridge_env["ANALYTICS_BRIDGE_ANCESTOR_ORIGINS"] == "https://notebook.example"
assert bridge_env["ANALYTICS_BRIDGE_COOKIE_MAX_AGE"] == "15552000"
paths = bridge_objects["Ingress"]["spec"]["rules"][0]["http"]["paths"]
assert {(p["path"], p["pathType"]) for p in paths} == {
    ("/v1/events", "Exact"),
    ("/bridge", "Prefix"),
}
print("PASS: optional bridge configuration and ingress")

colab_rendered = list(
    yaml.safe_load_all(
        subprocess.check_output(base + ["--set", "analytics.bridge.colabEnabled=true"], text=True)
    )
)
colab_deployment = next(item for item in colab_rendered if item and item["kind"] == "Deployment")
colab_env = {
    item["name"]: item["value"]
    for item in colab_deployment["spec"]["template"]["spec"]["containers"][0]["env"]
}
assert colab_env["ANALYTICS_BRIDGE_COLAB_ENABLED"] == "true"
assert colab_env["ANALYTICS_BRIDGE_ENABLED"] == "false"
print("PASS: Colab profile is explicit and does not enable the bridge by itself")
