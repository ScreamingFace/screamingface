"""The chart side of the separate blob store (#1603 review comment 1; owner decision 2026-11-03).

FEATURE: run blob store (OME-1540). The chart's second bundled Garage holds blobs on its own
volume with its own key pair, so a full blob store fails uploads and never result delivery.

WHY textual, like `test_deploy_time_chart_contract.py`: this lane has no helm binary. The
rendered shape (two StatefulSets, two PVCs, two endpoints) is asserted by
`.github/scripts/verify_chart_wiring.py` in the Charts workflow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from screamingface_engine import job_env

_CHART = Path(__file__).resolve().parents[2] / "deploy/helm/templates"


def _text(name: str) -> str:
    return (_CHART / name).read_text(encoding="utf-8")


def _assigned_keys(name: str) -> list[str]:
    keys = []
    for raw in _text(name).splitlines():
        line = raw.strip()
        if line and not line.startswith(("#", "{{")) and ":" in line:
            keys.append(line.split(":", 1)[0].strip())
    return keys


def test_the_blob_garage_self_configures_like_the_results_one() -> None:
    # INVARIANT: no bootstrap Job — the README rule holds for the second Garage too.
    garage = _text("garage-blobs.yaml")
    for flag in ("--single-node", "--default-access-key", "--default-bucket"):
        assert flag in garage
    assert "kind: Job" not in garage
    assert "helm.sh/hook" not in garage


@pytest.mark.parametrize(
    ("garage_var", "secret_key"),
    [
        ("GARAGE_DEFAULT_ACCESS_KEY", job_env.BLOB_S3_ACCESS_KEY),
        ("GARAGE_DEFAULT_SECRET_KEY", job_env.BLOB_S3_SECRET_KEY),
    ],
)
def test_the_blob_garage_adopts_the_blob_key_pair(garage_var: str, secret_key: str) -> None:
    garage = _text("garage-blobs.yaml")
    assert garage_var in garage
    assert f"key: {secret_key}" in garage
    # INVARIANT: never the results pair — separate stores, separate credentials.
    assert "URL4_CLOUD_ARTIFACT_S3" not in garage


def test_the_blob_garage_has_its_own_component_label() -> None:
    # INVARIANT: the results Garage's Service selects `component: garage`; sharing it would
    # put blob pods behind the results endpoint.
    garage = _text("garage-blobs.yaml")
    assert "app.kubernetes.io/component: garage-blobs" in garage
    assert "app.kubernetes.io/component: garage\n" not in garage


def test_the_blob_garage_sizes_its_own_volume() -> None:
    garage = _text("garage-blobs.yaml")
    assert ".Values.blobs.storage.garage.persistence.size" in garage
    assert ".Values.garage.persistence" not in garage


@pytest.mark.parametrize(
    "name", [job_env.BLOB_STORE, job_env.BLOB_S3_ENDPOINT_URL, job_env.BLOB_S3_BUCKET]
)
def test_both_halves_render_the_blob_location(name: str) -> None:
    # INVARIANT: the App (writer) and the pool (reader) must name ONE blob store.
    assert name in _assigned_keys("configmap.yaml")
    assert name in _assigned_keys("configmap-runner-env.yaml")


@pytest.mark.parametrize("configmap", ["configmap.yaml", "configmap-runner-env.yaml"])
def test_the_blob_secret_key_is_not_assigned_in_a_configmap(configmap: str) -> None:
    assert job_env.BLOB_S3_SECRET_KEY not in _assigned_keys(configmap)
    assert job_env.BLOB_S3_SECRET_KEY not in _assigned_keys("_helpers.tpl")


def test_the_blob_secret_key_is_assigned_in_the_blob_secret() -> None:
    assert job_env.BLOB_S3_SECRET_KEY in _assigned_keys("secret-blob-storage.yaml")
    assert job_env.BLOB_S3_ACCESS_KEY in _assigned_keys("secret-blob-storage.yaml")


@pytest.mark.parametrize("deployment", ["deployment.yaml", "deployment-runner.yaml"])
def test_both_workloads_read_the_blob_key_pair_by_name(deployment: str) -> None:
    # WHY by name: `envFrom` of the blob Secret would also hand GARAGE_RPC_SECRET to the App and
    # every runner process.
    assert 'include "screamingface-engine.blobCredentialEnv"' in _text(deployment)
    assert 'name: {{ include "screamingface-engine.blobSecretName"' not in _text(deployment)


def test_the_blob_garage_rpc_secret_is_random_not_derived() -> None:
    # INVARIANT (#1603 security review): derived from the release name and a constant master,
    # an RPC secret is predictable; the blob Garage reads a random one from its Secret.
    garage = _text("garage-blobs.yaml")
    assert "derivePassword" not in garage
    assert "key: GARAGE_RPC_SECRET" in garage
    secret = _text("secret-blob-storage.yaml")
    assert "GARAGE_RPC_SECRET" in _assigned_keys("secret-blob-storage.yaml")
    assert "randAlphaNum" in secret
    assert 'index $existing.data "GARAGE_RPC_SECRET"' in secret
