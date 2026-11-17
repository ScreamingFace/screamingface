"""The opt-in runner ServiceAccount and pod identity for pod-deletion-cost (OME-1931, spec D6).

With `runnerPool.deletionCost.enabled` true, the runner pod gets its own ServiceAccount (the
platform binds the pod-patch Role to it, never to the App), mounts its token, and receives the
three env entries the worker needs to write its own `pod-deletion-cost`. Disabled (the default),
the runner pod is rendered as before: the App's ServiceAccount, no token, no new env, and no
runner ServiceAccount.

The default-off invariant is proved on PARSED YAML: the runner Deployment's pod spec fields, its
env names, and the list of ServiceAccount documents.

WHY render and not read the template text: `helm lint` reports success for a chart that cannot
render, so the assertions here are against the RENDERED manifest. The same precedent as
`test_chart_render_runner_pool.py`.
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
_FULL = f"{_RELEASE}-{_RELEASE}"
_RUNNER = f"{_FULL}-runner"
_NEW_ENV = (
    "URL4_CLOUD_WORKER_DELETION_COST_ENABLED",
    "URL4_CLOUD_WORKER_POD_NAME",
    "URL4_CLOUD_WORKER_POD_NAMESPACE",
)
_ON = {"runnerPool.deletionCost.enabled": "true"}

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _helm(**overrides: str) -> subprocess.CompletedProcess[str]:
    args = [
        "helm",
        "template",
        _RELEASE,
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
    ]
    for key, value in overrides.items():
        args += ["--set", f"{key}={value}"]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _render(**overrides: str) -> list[dict[str, Any]]:
    result = _helm(**overrides)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _refusal(**overrides: str) -> str:
    result = _helm(**overrides)
    assert result.returncode != 0, "the render must refuse these values"
    return result.stderr


def _find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind} named {name!r} in the rendered chart")


def _of_kind(docs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [doc for doc in docs if doc.get("kind") == kind]


def _pod(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return _find(docs, "Deployment", _RUNNER)["spec"]["template"]["spec"]


def _env_entries(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    # Never index `e["value"]` blindly: the new pod-identity entries use `valueFrom`.
    return {e["name"]: e for e in _pod(docs)["containers"][0]["env"]}


def _account_names(docs: list[dict[str, Any]]) -> list[str]:
    return sorted(d["metadata"]["name"] for d in _of_kind(docs, "ServiceAccount"))


def test_the_values_default_is_off() -> None:
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))

    assert values["runnerPool"]["deletionCost"] == {"enabled": False}
    assert values["runnerPool"]["serviceAccount"] == {"create": True, "name": "", "annotations": {}}


def test_the_default_render_adds_no_account_no_token_no_env() -> None:
    docs = _render()
    pod = _pod(docs)

    assert _account_names(docs) == [_FULL]
    assert pod["automountServiceAccountToken"] is False
    assert pod["serviceAccountName"] == _FULL
    assert not set(_NEW_ENV) & set(_env_entries(docs))


def test_off_ignores_the_runner_account_values() -> None:
    docs = _render(
        **{"runnerPool.serviceAccount.name": "x", "runnerPool.serviceAccount.create": "false"}
    )

    assert _find(docs, "Deployment", _RUNNER) == _find(_render(), "Deployment", _RUNNER)
    assert _account_names(docs) == [_FULL]


def test_enabled_renders_the_runner_account() -> None:
    docs = _render(**_ON)
    doc = _find(docs, "ServiceAccount", _RUNNER)

    assert doc["apiVersion"] == "v1"
    assert doc["automountServiceAccountToken"] is False
    assert doc["metadata"]["labels"]["app.kubernetes.io/component"] == "runner"
    assert "annotations" not in doc["metadata"]
    assert _account_names(docs) == sorted([_FULL, _RUNNER])


def test_enabled_pod_uses_the_account_and_mounts_the_token() -> None:
    pod = _pod(_render(**_ON))

    assert pod["serviceAccountName"] == _RUNNER
    assert pod["automountServiceAccountToken"] is True


def test_enabled_adds_the_three_env_entries() -> None:
    enabled = _env_entries(_render(**_ON))
    default = _env_entries(_render())

    assert enabled["URL4_CLOUD_WORKER_DELETION_COST_ENABLED"]["value"] == "true"
    assert enabled["URL4_CLOUD_WORKER_POD_NAME"]["valueFrom"] == {
        "fieldRef": {"fieldPath": "metadata.name"}
    }
    assert enabled["URL4_CLOUD_WORKER_POD_NAMESPACE"]["valueFrom"] == {
        "fieldRef": {"fieldPath": "metadata.namespace"}
    }
    others = {k: v for k, v in enabled.items() if k not in _NEW_ENV}
    assert others == default


def test_the_account_name_can_be_overridden() -> None:
    docs = _render(**_ON, **{"runnerPool.serviceAccount.name": "custom-runner"})

    assert _find(docs, "ServiceAccount", "custom-runner")
    assert _RUNNER not in _account_names(docs)
    assert _pod(docs)["serviceAccountName"] == "custom-runner"


def test_annotations_reach_the_account() -> None:
    docs = _render(**_ON, **{"runnerPool.serviceAccount.annotations.team": "platform"})

    assert _find(docs, "ServiceAccount", _RUNNER)["metadata"]["annotations"] == {"team": "platform"}


def test_an_account_made_outside_the_chart_is_used_by_name() -> None:
    docs = _render(
        **_ON,
        **{
            "runnerPool.serviceAccount.create": "false",
            "runnerPool.serviceAccount.name": "platform-runner",
        },
    )
    pod = _pod(docs)

    assert _account_names(docs) == [_FULL]
    assert pod["serviceAccountName"] == "platform-runner"
    assert pod["automountServiceAccountToken"] is True


def test_create_false_without_a_name_is_refused() -> None:
    stderr = _refusal(**_ON, **{"runnerPool.serviceAccount.create": "false"})

    assert "runnerPool.serviceAccount.name" in stderr


def test_the_app_account_is_unchanged_in_both_cases() -> None:
    renders = [_render(), _render(**_ON)]
    app_pods = [_find(docs, "Deployment", _FULL)["spec"]["template"]["spec"] for docs in renders]

    for docs, pod in zip(renders, app_pods, strict=True):
        assert pod["serviceAccountName"] == _FULL
        assert _find(docs, "ServiceAccount", _FULL)
    assert app_pods[0].get("automountServiceAccountToken") == app_pods[1].get(
        "automountServiceAccountToken"
    )


def test_the_feature_does_not_need_autoscaling() -> None:
    docs = _render(**_ON)
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))

    assert values["runnerPool"]["autoscaling"]["enabled"] is False
    assert _find(docs, "ServiceAccount", _RUNNER)


def test_the_schema_refuses_an_unknown_key() -> None:
    assert "bogus" in _refusal(**{"runnerPool.deletionCost.bogus": "true"})
    assert "bogus" in _refusal(**{"runnerPool.serviceAccount.bogus": "true"})
