"""FX-91 — the chart warns when the node tier runs on a chart-generated signing key.

# WHY this file exists. With no `artifactSigning.existingSecret` and no `signingKey`, the
# signing Secret is filled from `lookup`, which is empty under an offline render (GitOps). Each
# such render mints a NEW random key, and the `checksum/artifact-signing` annotation is fixed in
# that case, so no pod restarts: pods that start at different times hold different keys and a
# signed `303` from one fails with 401 at another. The owner chose a warning, not a refusal
# (B7), so the render must SAY so. `helm install --dry-run=client` prints NOTES.txt without a
# cluster; `helm template` does not render NOTES at all.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

_CHART = pathlib.Path(__file__).resolve().parents[2] / "deploy/helm"
_WARNING = "WARNING: the artifact-signing key is chart-generated"
_NODE_ON = (
    "--set",
    "node.enabled=true",
    "--set",
    "artifactStorage.backend=s3",
    "--set-string",
    "artifactStorage.s3.endpointUrl=http://garage:3900",
)


def _notes(*extra: str) -> str:
    args = [
        "helm",
        "install",
        "r",
        str(_CHART),
        "--dry-run=client",
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
        *extra,
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    stdout = result.stdout
    assert "NOTES:" in stdout, stdout[-2000:]
    return stdout.split("NOTES:", 1)[1]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_a_chart_generated_signing_key_is_warned_about() -> None:
    notes = _notes(*_NODE_ON)

    assert _WARNING in notes
    # The warning names both ways out, so an operator can act on it without the README.
    assert "artifactSigning.existingSecret" in notes
    assert "artifactSigning.signingKey" in notes


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "extra",
    [
        ("--set-string", "artifactSigning.existingSecret=my-signing-secret"),
        ("--set-string", "artifactSigning.signingKey=a-pinned-key"),
    ],
    ids=["existingSecret", "signingKey"],
)
def test_a_supplied_signing_key_is_not_warned_about(extra: tuple[str, str]) -> None:
    assert _WARNING not in _notes(*_NODE_ON, *extra)


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_node_tier_off_is_not_warned_about() -> None:
    """With the node off there is no signer and no Secret, so there is nothing to warn about."""
    assert _WARNING not in _notes()


def _signing_secret(*extra: str) -> str:
    args = [
        "helm",
        "template",
        "r",
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
        *_NODE_ON,
        "--show-only",
        "templates/secret-artifact-signing.yaml",
        *extra,
    ]
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_an_offline_render_carries_the_warning_in_the_secret_itself() -> None:
    """WHY: ArgoCD renders with `helm template`, which never prints NOTES.txt — the rendered
    manifest (and so the GitOps diff) is the one place that operator sees the warning."""
    assert "WARNING (FX-91): this signing key is chart-generated" in _signing_secret()


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_a_pinned_signing_key_renders_no_warning_in_the_secret() -> None:
    assert "WARNING" not in _signing_secret("--set-string", "artifactSigning.signingKey=pinned")
