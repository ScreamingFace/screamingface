"""E5 P2 spec D9a and §8: which run-results store the App and the runner pool build.

FEATURE: a detached Run (OME-1837). Both halves resolve the store from the same `job_env` names
through one function, as the blob store does, so they cannot point at different buckets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from screamingface_engine import job_env
from screamingface_engine.adapters.factory import build_run_result_store, run_results_values
from screamingface_engine.artifacts.run_results import (
    FilesystemRunResultStore,
    S3RunResultStore,
)
from screamingface_engine.artifacts.wiring import (
    RunResultStoreNotConfigured,
    run_results_from_values,
)
from screamingface_engine.config import Settings

S3_VALUES = {
    job_env.RUN_RESULTS_STORE: "s3",
    job_env.RUN_RESULTS_S3_ENDPOINT_URL: "http://garage-run-results:3900",
    job_env.RUN_RESULTS_S3_BUCKET: "run-results",
    job_env.RUN_RESULTS_S3_ACCESS_KEY: "GKpool",
    job_env.RUN_RESULTS_S3_SECRET_KEY: "secret",
}


def test_an_unset_store_is_not_configured() -> None:
    """R5: a runner that is sent a result prefix with no store fails `result_store_missing`."""
    with pytest.raises(RunResultStoreNotConfigured):
        run_results_from_values({})
    with pytest.raises(RunResultStoreNotConfigured):
        run_results_from_values({job_env.RUN_RESULTS_STORE: "  "})


def test_s3_values_build_the_s3_store() -> None:
    assert isinstance(run_results_from_values(S3_VALUES), S3RunResultStore)


@pytest.mark.parametrize(
    "missing", [job_env.RUN_RESULTS_S3_BUCKET, job_env.RUN_RESULTS_S3_SECRET_KEY]
)
def test_an_incomplete_s3_store_names_what_is_missing(missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        run_results_from_values({**S3_VALUES, missing: ""})


def test_s3_never_borrows_the_artifact_bucket() -> None:
    """INVARIANT: results kept for 30 days never land in the bucket that expires in 2."""
    values = {
        job_env.RUN_RESULTS_STORE: "s3",
        job_env.ARTIFACT_S3_ENDPOINT_URL: "http://garage:3900",
        job_env.ARTIFACT_S3_BUCKET: "artifacts",
        job_env.ARTIFACT_S3_ACCESS_KEY: "GKa",
        job_env.ARTIFACT_S3_SECRET_KEY: "s",
    }
    with pytest.raises(ValueError, match=job_env.RUN_RESULTS_S3_BUCKET):
        run_results_from_values(values)


def test_a_folder_needs_its_path(tmp_path: Path) -> None:
    store = run_results_from_values(
        {job_env.RUN_RESULTS_STORE: "filesystem", job_env.RUN_RESULTS_DIR: str(tmp_path)}
    )
    assert isinstance(store, FilesystemRunResultStore)
    with pytest.raises(ValueError, match=job_env.RUN_RESULTS_DIR):
        run_results_from_values({job_env.RUN_RESULTS_STORE: "filesystem"})


def test_an_unknown_backend_is_refused() -> None:
    with pytest.raises(ValueError, match="'filesystem' or 's3'"):
        run_results_from_values({job_env.RUN_RESULTS_STORE: "gcs"})


def test_the_app_builds_the_s3_store_from_its_settings() -> None:
    settings = Settings(
        runner="queue",
        run_results_store="s3",
        run_results_s3_endpoint_url="http://garage-run-results:3900",
        run_results_s3_bucket="run-results",
        run_results_s3_access_key="GKapp",
        run_results_s3_secret_key="secret",
    )

    assert isinstance(build_run_result_store(settings), S3RunResultStore)


def test_a_deployed_app_refuses_a_folder_its_workers_cannot_reach() -> None:
    settings = Settings(runner="queue", run_results_store="filesystem", run_results_dir="/data")

    with pytest.raises(ValueError, match=job_env.RUN_RESULTS_STORE):
        build_run_result_store(settings)


def test_a_deployed_app_with_no_store_has_none() -> None:
    assert build_run_result_store(Settings(runner="queue")) is None


def test_local_mode_keeps_results_beside_its_database(tmp_path: Path) -> None:
    """D9a: local mode uses a folder in the Engine data dir."""
    store = build_run_result_store(Settings(runner="none"), home=tmp_path)

    assert isinstance(store, FilesystemRunResultStore)
    key = f"runs/run_{'a' * 32}/context"
    store.put(key, b"context")
    assert (tmp_path / ".screamingface-engine" / "run-results" / key).read_bytes() == b"context"


def test_an_empty_backend_setting_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(job_env.RUN_RESULTS_STORE, "")

    assert Settings().run_results_store is None


def test_local_runs_are_told_the_folder_the_app_reads(tmp_path: Path) -> None:
    """R14: a local run the driver starts writes its result where the App serves it from."""
    values = run_results_values(Settings(runner="none"), home=tmp_path)

    assert values[job_env.RUN_RESULTS_STORE] == "filesystem"
    assert values[job_env.RUN_RESULTS_DIR] == str(
        tmp_path / ".screamingface-engine" / "run-results"
    )
    assert values[job_env.RUN_RESULT_WRITE_BUDGET_S] == "60.0"


def test_a_deployment_names_no_folder() -> None:
    values = run_results_values(Settings(runner="queue"))

    assert values[job_env.RUN_RESULTS_STORE] == ""
    assert values[job_env.RUN_RESULTS_DIR] == ""
