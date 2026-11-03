"""Build the artifact store both halves need, and refuse the states that lose results.

FEATURE: over-cap results survive the Runner Job on a multi-pod deployment (OME-929).

WHY here and not in `adapters.factory`: that module is control-plane, and the Runner cannot
import it. Both halves need this decision — the Runner to write, the App to read — so it
belongs in the shared leaf, taking a plain mapping rather than either side's config object.

INVARIANT: an incomplete object-storage configuration raises HERE, at wiring time. The failure
it replaces arrived at redemption, after a full run's spend; the whole point is to move it to
the earliest moment the information exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from screamingface_engine import job_env
from screamingface_engine.artifacts.blobs import (
    BlobObjects,
    BlobScope,
    BlobStore,
    FilesystemBlobObjects,
    S3BlobObjects,
    ScopedBlobReader,
)
from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.ports import ArtifactWriter
from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3Config
from screamingface_engine.artifacts.sigv4 import Credentials


def result_writer_from_env(env: Mapping[str, str]) -> ArtifactWriter:
    """The spill store of the Runner's result path.

    FEATURE: deliver large results in full (OME-892). A mount call is a direct run (uniform
    executor PRD 04), so its spill parks here too.

    WHY one construction: the run path must park into one location, and the App must read from
    that same one. `result_delivery_from_env` (run mode) calls THIS.

    The filesystem/S3 choice and the half-configured refusal are unchanged from the run path's
    old inline expression; this is that expression, lifted so it has one home.
    """
    if (env.get(job_env.ARTIFACT_STORE) or "filesystem").strip() == "s3":
        return S3ArtifactStore(s3_config_from_values(env))
    artifacts_dir = env.get(job_env.ARTIFACTS_DIR) or job_env.DEFAULT_ARTIFACTS_DIR
    return FilesystemArtifactStore(Path(artifacts_dir))


def blob_objects_from_values(values: Mapping[str, str]) -> BlobObjects:
    """The run blob store's backend, from env-named values — ONE decision for both halves.

    FEATURE: uploads get their own store (#1603 review, owner decision 2026-11-03), so a full
    blob store fails uploads and never the result delivery a paid run depends on.

    Args:
        values: env-var name → value, using the `job_env.BLOB_*` / `job_env.ARTIFACT_*` names.
            The Runner passes its env; the App renders its `Settings` into this shape.

    `BLOB_STORE` unset → FOLLOW the artifact store (the `blobs/` prefix of the artifact directory
    or bucket). WHY kept: it is the layout the store shipped with and the one a bare local
    process gets; the chart always states `BLOB_STORE`, so no deployment lands here.
    `BLOB_STORE=filesystem` → `BLOBS_DIR` (default `DEFAULT_BLOBS_DIR`, a sibling of the
    artifact default). `BLOB_STORE=s3` → the `BLOB_S3_*` settings, all required.

    Raises:
        ValueError: an unknown backend, or an incomplete S3 configuration (naming what is empty).
    """
    selected = (values.get(job_env.BLOB_STORE) or "").strip()
    if not selected:
        return _objects_following_the_artifact_store(values)
    if selected == "s3":
        return S3BlobObjects(S3ArtifactStore(blob_s3_config_from_values(values)))
    if selected != "filesystem":
        raise ValueError(f"{job_env.BLOB_STORE} must be 'filesystem' or 's3', not {selected!r}")
    return FilesystemBlobObjects(Path(values.get(job_env.BLOBS_DIR) or job_env.DEFAULT_BLOBS_DIR))


def _objects_following_the_artifact_store(values: Mapping[str, str]) -> BlobObjects:
    """`BLOB_STORE` unset: the `blobs/` prefix of the artifact directory or bucket."""
    if (values.get(job_env.ARTIFACT_STORE) or "filesystem").strip() == "s3":
        return S3BlobObjects(S3ArtifactStore(s3_config_from_values(values)))
    return FilesystemBlobObjects(
        Path(values.get(job_env.ARTIFACTS_DIR) or job_env.DEFAULT_ARTIFACTS_DIR)
    )


def blob_store_from_env(env: Mapping[str, str]) -> BlobStore:
    """The run blob store (OME-1540) on the Runner: the same backend the App's routes write.

    WHY `blob_objects_from_values`: the App builds its store through the same function from
    the same names, so the two halves cannot be pointed at different blob stores.
    """
    return BlobStore(blob_objects_from_values(env))


def blob_scope_from_env(env: Mapping[str, str]) -> BlobScope:
    """This run's blob scope, from the run context only (spec F3 step 1).

    INVARIANT: the topic and the verified identity the run was STARTED with — the same pair the
    App's upload route scoped the blob to — never anything a ref or an expression says.

    Raises:
        ValueError: the env carries no usable topic, so there is no run to scope to.
    """
    email = job_env.identity_from_env(env).get("X-User-Email")
    return BlobScope.for_caller(email, env.get(job_env.TOPIC) or "")


def blob_reader_from_env(env: Mapping[str, str]) -> ScopedBlobReader:
    """The `BlobReader` (OME-1545 port) the Runner binds for its model calls."""
    return ScopedBlobReader(blob_store_from_env(env), blob_scope_from_env(env))


def s3_config_from_values(values: Mapping[str, str]) -> S3Config:
    """Build the ARTIFACT store's `S3Config` from env-named values, or raise naming what is missing.

    Args:
        values: env-var name → value, using the `job_env.ARTIFACT_S3_*` names. Callers holding
            a typed settings object render it into this shape so ONE validation path serves
            both halves.

    Raises:
        ValueError: naming the first missing variable. The name is the whole point — an
            operator reading it should not have to guess which of six settings is empty.
    """
    return _s3_config(
        values,
        _ARTIFACT_S3,
        "artifact object storage",
        f"{job_env.ARTIFACT_STORE}=filesystem for a single-process deployment.",
    )


def blob_s3_config_from_values(values: Mapping[str, str]) -> S3Config:
    """Build the BLOB store's `S3Config` from the `job_env.BLOB_S3_*` names, or raise.

    INVARIANT: never falls back to the artifact credentials or bucket — a blob store that
    silently shared the results bucket would bring back the shared-capacity failure it exists
    to remove.
    """
    return _s3_config(
        values,
        _BLOB_S3,
        "blob object storage",
        f"{job_env.BLOB_STORE}=filesystem for a single-process deployment.",
    )


@dataclass(frozen=True)
class _S3Names:
    endpoint_url: str
    bucket: str
    region: str
    access_key: str
    secret_key: str

    @property
    def required(self) -> tuple[str, ...]:
        # The region has a default, so only these four are unguessable.
        return (self.endpoint_url, self.bucket, self.access_key, self.secret_key)


_ARTIFACT_S3 = _S3Names(
    endpoint_url=job_env.ARTIFACT_S3_ENDPOINT_URL,
    bucket=job_env.ARTIFACT_S3_BUCKET,
    region=job_env.ARTIFACT_S3_REGION,
    access_key=job_env.ARTIFACT_S3_ACCESS_KEY,
    secret_key=job_env.ARTIFACT_S3_SECRET_KEY,
)
_BLOB_S3 = _S3Names(
    endpoint_url=job_env.BLOB_S3_ENDPOINT_URL,
    bucket=job_env.BLOB_S3_BUCKET,
    region=job_env.BLOB_S3_REGION,
    access_key=job_env.BLOB_S3_ACCESS_KEY,
    secret_key=job_env.BLOB_S3_SECRET_KEY,
)


def _s3_config(values: Mapping[str, str], names: _S3Names, what: str, fallback: str) -> S3Config:
    missing = [name for name in names.required if not (values.get(name) or "").strip()]
    if missing:
        raise ValueError(
            f"{what} is selected but not fully configured: "
            f"{', '.join(missing)} "
            + ("is" if len(missing) == 1 else "are")
            + f" empty. Set them, or set {fallback}"
        )
    return S3Config(
        endpoint_url=values[names.endpoint_url].strip(),
        bucket=values[names.bucket].strip(),
        credentials=Credentials(
            access_key=values[names.access_key].strip(),
            secret_key=values[names.secret_key].strip(),
            region=(values.get(names.region) or "").strip() or job_env.DEFAULT_ARTIFACT_S3_REGION,
        ),
    )


__all__ = [
    "blob_objects_from_values",
    "blob_reader_from_env",
    "blob_s3_config_from_values",
    "blob_scope_from_env",
    "blob_store_from_env",
    "result_writer_from_env",
    "s3_config_from_values",
]
