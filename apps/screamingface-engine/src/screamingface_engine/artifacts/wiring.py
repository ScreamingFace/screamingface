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

from screamingface_engine import job_env
from screamingface_engine.artifacts.s3 import S3Config
from screamingface_engine.artifacts.sigv4 import Credentials

# Which settings must be non-empty before an S3 store can be built. The region has a default
# and the secret key is checked alongside the access key, so only these three are unguessable.
_REQUIRED_S3 = (
    job_env.ARTIFACT_S3_ENDPOINT_URL,
    job_env.ARTIFACT_S3_BUCKET,
    job_env.ARTIFACT_S3_ACCESS_KEY,
    job_env.ARTIFACT_S3_SECRET_KEY,
)


def s3_config_from_values(values: Mapping[str, str]) -> S3Config:
    """Build an `S3Config` from env-named values, or raise naming what is missing.

    Args:
        values: env-var name → value, using the `job_env.ARTIFACT_S3_*` names. Callers holding
            a typed settings object render it into this shape so ONE validation path serves
            both halves.

    Raises:
        ValueError: naming the first missing variable. The name is the whole point — an
            operator reading it should not have to guess which of six settings is empty.
    """
    missing = [name for name in _REQUIRED_S3 if not (values.get(name) or "").strip()]
    if missing:
        raise ValueError(
            "artifact object storage is selected but not fully configured: "
            f"{', '.join(missing)} "
            + ("is" if len(missing) == 1 else "are")
            + " empty. Set them, or set "
            f"{job_env.ARTIFACT_STORE}=filesystem for a single-process deployment."
        )
    return S3Config(
        endpoint_url=values[job_env.ARTIFACT_S3_ENDPOINT_URL].strip(),
        bucket=values[job_env.ARTIFACT_S3_BUCKET].strip(),
        credentials=Credentials(
            access_key=values[job_env.ARTIFACT_S3_ACCESS_KEY].strip(),
            secret_key=values[job_env.ARTIFACT_S3_SECRET_KEY].strip(),
            region=(values.get(job_env.ARTIFACT_S3_REGION) or "").strip()
            or job_env.DEFAULT_ARTIFACT_S3_REGION,
        ),
    )


__all__ = ["s3_config_from_values"]
