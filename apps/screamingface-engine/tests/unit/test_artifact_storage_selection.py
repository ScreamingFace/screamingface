"""Which artifact store a deployment gets, and the states it refuses to boot in (OME-929).

FEATURE: over-cap results survive the worker pool on a multi-pod deployment.

INVARIANT — the whole point of this file: `runner="queue"` with filesystem artifact storage is
UNREPRESENTABLE. That pairing is exactly the OME-929 bug (a worker's child writing to its own
`emptyDir` while the App reads its own), and it used to be not just representable but the
DEFAULT, reachable by setting nothing at all. It is now refused at startup.

WHY refuse at startup rather than warn: the failure it replaces surfaced at redemption time,
after 11,902 model calls had been paid for. Every second between the misconfiguration and the
error costs money, so the error belongs at boot — before a single run is accepted.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _fakes import RecordingJobRunner

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.artifacts import FilesystemArtifactStore, S3ArtifactStore
from screamingface_engine.config import Settings
from screamingface_engine.runner.main import result_delivery_from_env
from screamingface_engine.testing import InMemoryEventStream

S3_ENV = {
    job_env.ARTIFACT_STORE: "s3",
    job_env.ARTIFACT_S3_ENDPOINT_URL: "http://garage.svc:3900",
    job_env.ARTIFACT_S3_BUCKET: "artifacts",
    job_env.ARTIFACT_S3_REGION: "garage",
    job_env.ARTIFACT_S3_ACCESS_KEY: "GKtest",
    job_env.ARTIFACT_S3_SECRET_KEY: "secret",
}


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(jwt_secret="selection-secret-selection-secret", **overrides)  # type: ignore[arg-type]


def _app(settings: Settings) -> object:
    return create_app(settings, stream=InMemoryEventStream(), job_runner=RecordingJobRunner())


# --- the App's read side -----------------------------------------------------------------


def test_a_local_app_still_uses_the_filesystem(tmp_path: Path) -> None:
    """D3: `inprocess`/local shares one disk by construction — behaviour unchanged."""
    app = _app(_settings(tmp_path, runner="none", artifacts_dir=str(tmp_path)))

    assert isinstance(app.state.artifact_store, FilesystemArtifactStore)  # type: ignore[attr-defined]


def test_a_queue_app_configured_for_object_storage_uses_it(tmp_path: Path) -> None:
    app = _app(
        _settings(
            tmp_path,
            runner="queue",
            artifact_store="s3",
            artifact_s3_endpoint_url="http://garage.svc:3900",
            artifact_s3_bucket="artifacts",
            artifact_s3_access_key="GKtest",
            artifact_s3_secret_key="secret",
        )
    )

    assert isinstance(app.state.artifact_store, S3ArtifactStore)  # type: ignore[attr-defined]


def test_a_queue_app_left_on_filesystem_storage_refuses_to_boot(tmp_path: Path) -> None:
    """THE regression guard. This configuration — which was the default — is the bug.

    A worker's child and the App pod do not share a disk, so a filesystem store here means
    every over-cap result 404s at redemption. Nothing about the setup says so, which is why
    it shipped; now it cannot start.
    """
    with pytest.raises(ValueError, match="URL4_CLOUD_ARTIFACT_STORE"):
        _app(_settings(tmp_path, runner="queue", artifacts_dir=str(tmp_path)))


@pytest.mark.parametrize(
    "missing", ["artifact_s3_endpoint_url", "artifact_s3_bucket", "artifact_s3_access_key"]
)
def test_object_storage_with_an_incomplete_configuration_refuses_to_boot(
    tmp_path: Path, missing: str
) -> None:
    """INVARIANT: half-configured object storage fails at boot, naming the missing setting.

    Deferring it means the first over-cap run discovers it — which is the late, expensive
    failure this ticket exists to remove.
    """
    config: dict[str, object] = {
        "runner": "queue",
        "artifact_store": "s3",
        "artifact_s3_endpoint_url": "http://garage.svc:3900",
        "artifact_s3_bucket": "artifacts",
        "artifact_s3_access_key": "GKtest",
        "artifact_s3_secret_key": "secret",
    }
    config[missing] = ""

    with pytest.raises(ValueError, match=missing.upper()):
        _app(_settings(tmp_path, **config))


# --- the Runner's write side -------------------------------------------------------------


def test_the_runner_defaults_to_the_filesystem(tmp_path: Path) -> None:
    _, _, store = result_delivery_from_env({job_env.ARTIFACTS_DIR: str(tmp_path)})

    assert isinstance(store, FilesystemArtifactStore)


def test_the_runner_uses_object_storage_when_the_chart_says_so() -> None:
    _, _, store = result_delivery_from_env(S3_ENV)

    assert isinstance(store, S3ArtifactStore)


@pytest.mark.parametrize(
    "missing",
    [job_env.ARTIFACT_S3_ENDPOINT_URL, job_env.ARTIFACT_S3_BUCKET, job_env.ARTIFACT_S3_ACCESS_KEY],
)
def test_the_runner_refuses_a_half_configured_object_store(missing: str) -> None:
    """Fails building the executor, which surfaces as a Terminated(failed) frame on the
    topic — not as a ticket that redeems to nothing."""
    env = {key: value for key, value in S3_ENV.items() if key != missing}

    with pytest.raises(ValueError, match=missing):
        result_delivery_from_env(env)


# --- the two sides must read the SAME env names ------------------------------------------


@pytest.mark.parametrize(
    ("field", "name"),
    [
        ("artifact_store", job_env.ARTIFACT_STORE),
        ("artifact_s3_endpoint_url", job_env.ARTIFACT_S3_ENDPOINT_URL),
        ("artifact_s3_bucket", job_env.ARTIFACT_S3_BUCKET),
        ("artifact_s3_region", job_env.ARTIFACT_S3_REGION),
        ("artifact_s3_access_key", job_env.ARTIFACT_S3_ACCESS_KEY),
        ("artifact_s3_secret_key", job_env.ARTIFACT_S3_SECRET_KEY),
    ],
)
def test_the_app_setting_and_the_runner_env_name_are_the_same_variable(
    field: str, name: str
) -> None:
    """INVARIANT: one name per value, read by both halves.

    This is the invariant `ARTIFACTS_DIR` was SUPPOSED to have — `job_env` documents it as
    "one name read by BOTH the Runner and the App's Settings" — and nothing checked it. A
    one-sided rename would point the writer and the reader at different buckets, reproducing
    OME-929 in a form the 404 message would not even hint at.
    """
    prefix = Settings.model_config.get("env_prefix", "")

    assert f"{prefix}{field}".upper() == name
