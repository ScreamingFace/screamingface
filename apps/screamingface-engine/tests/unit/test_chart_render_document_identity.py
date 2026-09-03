"""Every rendered chart document declares its own identity (OME-1092).

This exists because of a defect that reached a live cluster. The runner-pool template's
drain-timing guard ended with `{{- end -}}`; the trailing `-}}` trims the newline after `end`,
which glued `apiVersion: apps/v1` onto the end of the preceding YAML COMMENT line:

    # ... not as an outage.apiVersion: apps/v1
    kind: Deployment

The Deployment silently lost its `apiVersion`, and `helm upgrade --install` refused the whole
release with "error validating data: apiVersion not set".

WHY the existing suite could not catch it: `helm lint` and `helm template` both SUCCEED on this
chart — neither validates a manifest — and `test_chart_render_runner_pool.py` parses with
`yaml.safe_load_all` and looks documents up by `kind` + `metadata.name`. A document missing
only its `apiVersion` still parses, still carries its `kind` and name, and is still found. The
one field that vanished was the one field nothing asserted.

INVARIANT: so this file asserts the property for EVERY rendered document rather than for the
one template that happened to break. A whitespace-trim mistake in any future template — the
same one-character slip, anywhere — fails here instead of at `helm upgrade` time.
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

# Self-contained rather than imported from a sibling test module: each cycle brings its own
# fixtures, so a later edit here cannot break a prior file.
_REQUIRED_NATS_URL = "config.natsUrl=nats://nats.example:4222"


def _render(*set_values: str) -> list[dict[str, Any]]:
    """Render the chart and return its documents. Raises if helm refuses to render.

    WHY `--set` and not `--set-string` for the overrides: `values.schema.json` types the
    numeric knobs as numbers, and `--set-string` would hand them the string "45", which the
    schema rejects before any template runs. Only the NATS URL is genuinely a string.
    """
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string", _REQUIRED_NATS_URL]
    for value in set_values:
        args += ["--set", value]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _identify(doc: dict[str, Any]) -> str:
    return f"{doc.get('kind', '<no kind>')}/{doc.get('metadata', {}).get('name', '<no name>')}"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_every_rendered_document_declares_an_api_version() -> None:
    """The regression itself: a document whose `apiVersion` was absorbed by a comment parses
    cleanly and keeps its `kind`, so only an explicit check sees it."""
    missing = [_identify(doc) for doc in _render() if not doc.get("apiVersion")]
    assert not missing, f"rendered documents without an apiVersion: {missing}"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_every_rendered_document_declares_a_kind_and_a_name() -> None:
    """The sibling properties, for the same reason: the identity triple is what the API server
    dispatches on, and a template that can lose one can lose another."""
    anonymous = [
        _identify(doc)
        for doc in _render()
        if not doc.get("kind") or not doc.get("metadata", {}).get("name")
    ]
    assert not anonymous, f"rendered documents without a kind or name: {anonymous}"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_runner_pool_deployment_declares_the_workload_api_version() -> None:
    """The specific document that broke, pinned by name — the generic sweep above would also
    pass if the pool stopped rendering at all."""
    pools = [
        doc
        for doc in _render()
        if doc.get("kind") == "Deployment"
        and str(doc.get("metadata", {}).get("name", "")).endswith("-runner")
    ]
    assert len(pools) == 1, f"expected exactly one runner-pool Deployment, got {len(pools)}"
    assert pools[0]["apiVersion"] == "apps/v1"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_identity_check_survives_a_non_default_drain_configuration() -> None:
    """The guard block whose `end` caused the defect is CONDITIONAL on the drain values, so the
    rendering path differs with them. Re-render against a legal non-default pair — the template
    fails the render outright if the relation is violated, so these must stay consistent."""
    docs = _render("runnerPool.drainGraceS=45", "runnerPool.terminationGracePeriodSeconds=90")
    missing = [_identify(doc) for doc in docs if not doc.get("apiVersion")]
    assert not missing, f"rendered documents without an apiVersion: {missing}"
