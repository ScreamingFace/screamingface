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
print("PASS: disabled and enabled chart wiring, secret references and ingress route")
