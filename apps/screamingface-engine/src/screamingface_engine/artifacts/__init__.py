"""Artifact storage: the ports, and the adapters that implement them.

FEATURE: over-cap results survive the Runner Job on a multi-pod deployment (OME-929).

`ArtifactStore` is retained as an alias for `FilesystemArtifactStore`: it names the same
class 24 call sites and 4 test modules already import, and this repo's tests are
append-only, so the name must keep resolving. New code should say which adapter it means.
"""

from screamingface_engine.artifacts.delivery import (
    ResultDelivery,
    allowed_result_bytes,
    decide_result_delivery,
)
from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.ports import (
    ArtifactContent,
    ArtifactReader,
    ArtifactWriter,
    LocalFile,
    RemoteStream,
)
from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3Config, S3StorageError
from screamingface_engine.artifacts.signing import (
    sign_artifact_id,
    signed_artifact_path,
    verify_artifact_signature,
)

# AIDEV-NOTE: an alias, not a subclass. A subclass would be a second type that
# `isinstance` and `is` comparisons could tell apart, which is exactly the drift the
# rename was meant to avoid.
ArtifactStore = FilesystemArtifactStore

__all__ = [
    "ArtifactContent",
    "ArtifactReader",
    "ArtifactStore",
    "ArtifactWriter",
    "FilesystemArtifactStore",
    "LocalFile",
    "RemoteStream",
    "ResultDelivery",
    "S3ArtifactStore",
    "S3Config",
    "S3StorageError",
    "allowed_result_bytes",
    "decide_result_delivery",
    "sign_artifact_id",
    "signed_artifact_path",
    "verify_artifact_signature",
]
