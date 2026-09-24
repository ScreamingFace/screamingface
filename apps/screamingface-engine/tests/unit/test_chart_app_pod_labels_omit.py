"""FX-93 — the App pod template drops chart-owned keys from `podLabels`, like the node's does.

# WHY this file exists. The App renders `podLabels` and then its own
# `app.kubernetes.io/component: control-plane`. An operator's `podLabels` copy of a chart-owned
# key was still written first, so the pod template had the SAME mapping key twice: a strict
# parser refuses it, a lenient one keeps either value, and the node's NetworkPolicy admits the
# App by exactly that label. The test reads the RAW render, because PyYAML silently keeps the
# last duplicate and would hide the defect.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

_CHART = pathlib.Path(__file__).resolve().parents[2] / "deploy/helm"


def _app_deployment(*extra: str) -> str:
    args = [
        "helm",
        "template",
        "r",
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
        "--show-only",
        "templates/deployment.yaml",
        *extra,
    ]
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def _pod_label_lines(rendered: str) -> list[str]:
    """The raw lines of `spec.template.metadata.labels`, duplicates kept."""
    lines = rendered.splitlines()
    start = lines.index("  template:")
    assert lines[start + 1] == "    metadata:" and lines[start + 2] == "      labels:", lines[
        start : start + 3
    ]
    out: list[str] = []
    for line in lines[start + 3 :]:
        if not line.startswith("        "):
            break
        if not line.lstrip().startswith("#"):
            out.append(line.strip())
    return out


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("key", "chart_value"),
    [
        ("app.kubernetes.io/component", "control-plane"),
        ("app.kubernetes.io/name", "url4-cloud"),
        ("app.kubernetes.io/instance", "r"),
    ],
)
def test_a_pod_label_override_of_a_chart_owned_key_renders_it_once(
    key: str, chart_value: str
) -> None:
    escaped = key.replace(".", r"\.")
    rendered = _app_deployment("--set-string", f"podLabels.{escaped}=operator-value")

    labels = _pod_label_lines(rendered)
    matching = [line for line in labels if line.split(":", 1)[0] == key]
    # INVARIANT: one copy, and it is the chart's — the NetworkPolicy peer and the selector read it.
    assert matching == [f"{key}: {chart_value}"], labels


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_an_unrelated_pod_label_still_renders() -> None:
    rendered = _app_deployment("--set-string", "podLabels.team=search")

    assert "team: search" in _pod_label_lines(rendered)
    pod = yaml.safe_load(rendered)["spec"]["template"]["metadata"]["labels"]
    assert pod["app.kubernetes.io/component"] == "control-plane"
