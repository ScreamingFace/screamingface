"""DEC-2 / DEC-9 (uniform executor PRD 05): the node tier is gone, and a leftover `node:` block
in a values file is a clear render-time failure rather than silently ignored or an opaque
`additionalProperties` schema error.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm"
_README = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "README.md"

# Only the tests that actually shell out to `helm template` need it — the README test below is a
# plain text check and must still run (and catch a stale README) on a runner with no helm CLI.
_needs_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="needs the helm CLI")

_REMOVED_NODE_METRICS = (
    "screamingface_engine_node_sync_request_duration_seconds",
    "screamingface_engine_node_sync_inflight",
    "screamingface_engine_node_sync_shed_total",
    "screamingface_engine_node_sync_budget_exhausted_total",
)


def _render_raw(*sets: str, files: tuple[Path, ...] = ()) -> subprocess.CompletedProcess[str]:
    args = [
        "helm",
        "template",
        "url4-cloud",
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
    ]
    for values_file in files:
        args += ["-f", str(values_file)]
    for value in sets:
        args += ["--set", value]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _render(*sets: str) -> list[dict[str, Any]]:
    result = _render_raw(*sets)
    result.check_returncode()
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


@_needs_helm
@pytest.mark.parametrize("node_set", ["node.enabled=true", "node.replicas=2"])
def test_chart_rejects_node_block_with_clear_message(node_set: str) -> None:
    result = _render_raw(node_set)

    assert result.returncode != 0
    assert "the node tier was removed" in result.stderr
    assert "prd/05-node-tier-decommission.md" in result.stderr


@_needs_helm
def test_chart_rejects_a_node_block_in_a_values_file(tmp_path: Path) -> None:
    """DC-D1's own wording: "a values file with a `node:` block", not only `--set`."""
    values_file = tmp_path / "values.yaml"
    values_file.write_text("node: {}\n")

    result = _render_raw(files=(values_file,))

    assert result.returncode != 0
    assert "the node tier was removed" in result.stderr
    assert "prd/05-node-tier-decommission.md" in result.stderr


@_needs_helm
def test_default_render_has_no_node_objects() -> None:
    docs = _render()

    assert not [d for d in docs if d.get("metadata", {}).get("name", "").endswith("-node")]
    configmaps = [d for d in docs if d.get("kind") == "ConfigMap"]
    assert all("URL4_CLOUD_NODE_BASE_URL" not in cm.get("data", {}) for cm in configmaps)


def test_chart_readme_lists_removed_node_metrics_and_replacements() -> None:
    readme = _README.read_text(encoding="utf-8")
    rows = [line for line in readme.splitlines() if line.strip().startswith("|")]

    for metric in _REMOVED_NODE_METRICS:
        row = next((r for r in rows if metric in r), None)
        assert row is not None, f"{metric} is not listed in deploy/helm/README.md"
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        replacement_cell = cells[-1]
        assert "screamingface_engine_" in replacement_cell
        assert "node_sync" not in replacement_cell
