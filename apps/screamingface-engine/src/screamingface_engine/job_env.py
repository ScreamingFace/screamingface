"""Every env var a Runner Job reads, and which side supplies it.

One image runs both modes now (`screamingface-engine serve` /
`screamingface-engine run`), so this is a single module rather than the two
hand-synced copies it replaces. Two sources feed a Job's environment, and the run
mode cannot tell them apart — it just reads its environment:

- PER-RUN, written by the App onto the Job spec (:data:`WRITTEN_BY_APP`). None of it exists
  until a request arrives, which is exactly why Helm cannot supply it.
- PER-DEPLOY, named AND valued by the Helm chart and injected wholesale with ``envFrom``
  (:data:`DEPLOY_TIME`). The App never writes these — the chart is the only writer, so there is
  nothing to keep in sync.

These names are screamingface-engine's, not the engine's: half are aigateway-specific and the rest
describe how this app schedules a run. None of it is part of the url4 language or its wire
format.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from url4.streaming.protocol import CachePolicy

# --- per-run: written by the App onto the Job spec -------------------------------------------
TOPIC = "URL4_CLOUD_TOPIC"
EXPRESSION = "URL4_CLOUD_EXPRESSION"
JOB_DEADLINE_S = "URL4_CLOUD_JOB_DEADLINE_S"
TRACEPARENT = "URL4_CLOUD_TRACEPARENT"

AIGATEWAY_PROFILE = "AIGATEWAY_PROFILE"
"""Per-request profile selection; absent means the gateway's default.

Orthogonal to identity: it selects WHICH of the resolved account's stored credentials to use, not
who the caller is, so it is forwarded on its own merits.
"""

IDENTITY_HEADER_ENV: Mapping[str, str] = MappingProxyType(
    {
        "X-User-Email": "URL4_CLOUD_IDENTITY_USER_EMAIL",
    }
)
"""The caller's VERIFIED identity, and the env name it travels under.

https://pulse.dev.openmined.org/docs/products/gateway-identity-flow/ — Cloudflare Access
authenticates the caller at the edge, and Envoy re-verifies that assertion against Cloudflare's
JWKS before clearing any client-supplied copy of this header and re-injecting it from the verified
claims. By the time it reaches the App it is trustworthy and a client cannot forge it.

WHY only the email: aigateway keys a caller's account on it, and an email is globally unique — so
the flow's tenant header adds nothing to a key built from it. Cloudflare service tokens (which carry
a `common_name` and no email) are out of scope until the gateway issues its own API keys, so
automation is not identified here at all rather than half-identified.

INVARIANT: this table is the ONLY place the header↔env correspondence is written. Both adapters
render a Job's env from it and the run mode reads its env back through it, so a header added here
reaches aigateway without touching either half.

WHY plain env and not a Secret: this is identity, not a credential — it authorizes nothing on its
own, and a Secret would imply a confidentiality it does not have. The accepted cost
is that ``get jobs`` RBAC reveals the caller's email.

INVARIANT: this is now the ONLY thing screamingface-engine forwards about a caller.
aigateway runs either ``cloudflare_headers`` (deployed — reads this header) or
``disabled`` (local — anonymous). Neither reads ``Authorization``, so no bearer
token is carried anywhere in this app.
"""


def identity_from_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """The identity headers present on an inbound request, canonical name → value.

    ``headers`` must look up case-insensitively (Starlette's ``Headers`` does); HTTP header names
    are case-insensitive on the wire, but the value returned here is keyed by the canonical casing
    so the outgoing request renders one spelling regardless of what arrived.

    A present-but-blank header is dropped: it carries no identity, and forwarding it would let a
    downstream reader see the header and conclude the caller is of that kind.
    """
    return {
        header: stripped
        for header in IDENTITY_HEADER_ENV
        if (stripped := (headers.get(header) or "").strip())
    }


def identity_to_env(identity: Mapping[str, str]) -> dict[str, str]:
    """Render an identity mapping as the Job env keys that carry it. Unknown headers are dropped."""
    return {
        IDENTITY_HEADER_ENV[header]: value
        for header, value in identity.items()
        if value and header in IDENTITY_HEADER_ENV
    }


def identity_from_env(env: Mapping[str, str]) -> dict[str, str]:
    """Read an identity mapping back out of a run's environment, canonical header name → value."""
    return {
        header: stripped
        for header, name in IDENTITY_HEADER_ENV.items()
        if (stripped := (env.get(name) or "").strip())
    }


CACHE_PARTICIPATE = "URL4_CLOUD_CACHE_PARTICIPATE"
"""Whether this run may participate in the gateway's response cache — `"true"` / `"false"`.

Per-run for the same reason ``AIGATEWAY_PROFILE`` is: it does not exist until a caller states it,
so Helm cannot supply it and the App must. INVARIANT: it is written per RUN and never onto shared
world configuration — the run mode's ``AigatewayConfig`` describes the gateway for every run in the
process, and a per-run value parked there is one caller's directive another caller's run can read.

Absent means the App stated nothing, which the run mode carries through as
"not stated" rather than resolving: the D1 default belongs to convergence
(:mod:`screamingface_engine.rest.cache_policy`) and is decided exactly once, there.
"""

CACHE_MAX_AGE_S = "URL4_CLOUD_CACHE_MAX_AGE_S"
"""The caller's freshness bound in whole seconds, when they stated one.

url4-INTERNAL: it is never sent to the gateway, whose cache-control grammar is closed to a single
key and BYPASSES on any other. It travels only so the value survives to read-back, where an entry's
age can be compared against it.
"""

EXTRA_MODELS = "URL4_CLOUD_EXTRA_MODELS"
"""Dynamically admitted model ids this run's world must ALSO route (OME-880).

A JSON array of gateway model ids. Per-run for the same reason the identity is: the overlay
does not exist until the gateway admits something, so Helm cannot supply it — the App writes
the CURRENT overlay onto every scheduled run, which is what lets a model admitted a second
ago reach the very next run. The run mode merges these ADDITIVELY into the declared world
(:func:`screamingface_engine.world_config.parse_config`); an id already declared keeps its declared
spec, so the overlay can never weaken a compiled route.
"""


def extra_models_to_env(ids: Sequence[str]) -> dict[str, str]:
    """Render the admitted overlay as the Job env key that carries it.

    An empty overlay renders NOTHING — the common case (no dynamic admission
    this deployment) leaves the Job spec exactly as it was before OME-880.
    """
    if not ids:
        return {}
    return {EXTRA_MODELS: json.dumps(sorted(ids))}


_TRUE, _FALSE = "true", "false"


def cache_policy_to_env(policy: CachePolicy | None) -> dict[str, str]:
    """Render a run's cache policy as the Job env keys that carry it.

    Args:
        policy: The run's RESOLVED policy, or ``None`` when this hop was told nothing — a Job
            scheduled directly rather than through the REST edge. ``None`` renders NOTHING, so an
            unstated policy stays distinguishable from a stated one all the way down.

    Returns:
        Only the fields the policy actually states. A `None` field is silence, and rendering it as
        a literal would turn "nobody said" into "somebody said the default".
    """
    if policy is None:
        return {}
    env: dict[str, str] = {}
    if policy.participate is not None:
        env[CACHE_PARTICIPATE] = _TRUE if policy.participate else _FALSE
    if policy.max_age is not None:
        env[CACHE_MAX_AGE_S] = str(policy.max_age)
    return env


def cache_policy_from_env(env: Mapping[str, str]) -> CachePolicy:
    """Read a run's cache policy back out of its environment. Total — it never raises.

    Returns a policy rather than ``CachePolicy | None`` because an all-unstated
    policy already IS "nothing declared":
    :func:`screamingface_engine.runner.cache.policy_to_body_field` renders it as an
    absent `cache` field, which the gateway reads as participation. So a Job whose env
    carries no policy behaves like every other one WITHOUT the run mode re-deciding
    what silence means.

    An unreadable ``CACHE_PARTICIPATE`` resolves to **opt out**, not to silence. This env is
    App-written, so an unrecognised value is a bug rather than caller input, and of the two wrong
    answers the cheap one — a missed hit — is the one to take: the expensive one serves a run a
    shared, permanent answer it may have explicitly refused. An unreadable bound is simply dropped;
    it is advisory and cannot be got wrong in a direction that costs anything.
    """
    raw_participate = env.get(CACHE_PARTICIPATE)
    raw_max_age = env.get(CACHE_MAX_AGE_S)
    return CachePolicy(
        participate=None if raw_participate is None else raw_participate.strip().lower() == _TRUE,
        max_age=int(raw_max_age) if raw_max_age is not None and raw_max_age.isdigit() else None,
    )


def io_concurrency_from_env(env: Mapping[str, str]) -> int | None:
    """Read a run's downstream in-flight budget back out of its environment. Total — never raises.

    Absent, malformed, or below 1 resolves to ``None``, which the executor renders by OMITTING
    the ``concurrency`` kwarg entirely — URL4's own default then applies, the exact behavior a
    pre-OME-908 run had. WHY total rather than raising: `build_executor` runs inside
    `InProcessJobRunner.schedule`, where an exception takes down the caller's request with
    nothing on the stream, and the env is App-written anyway (a garbage value is an operator
    bug, and the safe reading of it is the historic default — same reasoning as an unreadable
    cache bound above). Local mode never carries the variable at all (`InProcessJobRunner._env`
    pops it); it exists for one-shot Job Pods.
    """
    raw = env.get(IO_CONCURRENCY)
    if raw is None or not raw.strip().isdigit():
        return None
    value = int(raw)
    return value if value >= 1 else None


# --- per-deploy: named by the chart, injected via envFrom ------------------------------------
NATS_URL = "URL4_CLOUD_NATS_URL"
AIGATEWAY_BASE_URL = "AIGATEWAY_BASE_URL"

AIGATEWAY_MODEL = "AIGATEWAY_MODEL"
"""Overrides the default route declared in the image's `url4.toml` (`config.aigatewayModel`)."""

TAVILY_API_KEY = "TAVILY_API_KEY"
"""Injected from the Tavily Secret by `envFrom`, so the Secret's KEY must be this exact name.
Absent => web tools stay off."""

STREAM_GRACE_S = "URL4_CLOUD_STREAM_GRACE_S"
"""How long the Runner waits after its run ends before deleting the run's stream, so a client
still draining the final frames is not cut off.

WHY the App writes it rather than Helm: the App must ALSO widen the Job's
``activeDeadlineSeconds`` to cover this wait, and two independently-set values would silently
disagree — a grace longer than the deadline slack is a pod SIGKILLed mid-teardown, which is the
leak this whole mechanism exists to close. One writer, one source of truth."""

DEFAULT_STREAM_GRACE_S = 60.0
"""Fallback for an unset :data:`STREAM_GRACE_S`, matching ``iat_window_s`` — the widest window in
which any client can still hold a valid ticket and be attached to the run."""

RUNNER_CONFIG = "URL4_RUNNER_CONFIG"
"""Path to the declared world (:mod:`screamingface_engine.world_config`). Baked into
the image; the App never writes it."""

ARTIFACTS_DIR = "URL4_CLOUD_ARTIFACTS_DIR"
"""Directory where over-threshold results are spilled as content-addressed files and from
which ``GET /artifacts/{id}`` serves them (OME-892). One name read by BOTH the Runner (write
side, via :func:`runner.main.build_executor`) and the App's ``Settings.artifacts_dir`` (serve
side) so the two halves cannot be pointed at different directories by a one-sided edit.

AIDEV-NOTE: this is the LOCAL-mode store only. In the `k8s` backend the Runner Job and the
App are separate pods with separate disks, so a filesystem store there loses every over-cap
result (OME-929) — which is why that pairing is now refused at startup. Deployed artifact
storage is object storage; see :data:`ARTIFACT_STORE`."""

DEFAULT_ARTIFACTS_DIR = str(Path(tempfile.gettempdir()) / "screamingface-engine" / "artifacts")
"""Fallback for an unset :data:`ARTIFACTS_DIR`. A temp path on purpose: artifacts are
short-lived hand-offs (swept by TTL), not an archive.

AIDEV-NOTE: fetching does NOT delete them — that was removed on OME-892 review (content
addressing means one file backs many tickets, and a Range request must leave the rest
fetchable). TTL is the only cleanup."""

# --- artifact storage backend (OME-929) -----------------------------------------------------
# WHY these are DEPLOY_TIME and not derived: the Runner cannot see the cluster topology it runs
# in, so the chart states it. The App CAN see it (`Settings.runner`), and refuses to start when
# `runner="k8s"` is paired with filesystem storage — the combination that IS the OME-929 bug.
#
# INVARIANT: each name here must equal `Settings`' env alias for the same value, i.e.
# `URL4_CLOUD_` + the field name, uppercased. `test_artifact_storage_selection.py` pins that,
# because a one-sided rename would point the writer and the reader at different buckets — the
# same class of failure as OME-929, in a form the 404 message would not even hint at.
ARTIFACT_STORE = "URL4_CLOUD_ARTIFACT_STORE"
"""filesystem" (local: one process, one disk) or "s3" (deployed: separate pods).

Absent means "filesystem", which is right for local and WRONG for `k8s` — so the App refuses
that pairing rather than defaulting into it silently, the way OME-929 did."""

ARTIFACT_S3_ENDPOINT_URL = "URL4_CLOUD_ARTIFACT_S3_ENDPOINT_URL"
"""Base URL of the S3-compatible endpoint, e.g. the bundled Garage Service."""

ARTIFACT_S3_BUCKET = "URL4_CLOUD_ARTIFACT_S3_BUCKET"
"""Bucket holding the content-addressed result objects."""

ARTIFACT_S3_REGION = "URL4_CLOUD_ARTIFACT_S3_REGION"
"""Signing region. Arbitrary but must match what the endpoint expects; Garage's default is
its own configured region name, NOT an AWS one."""

DEFAULT_ARTIFACT_S3_REGION = "garage"

ARTIFACT_S3_ACCESS_KEY = "URL4_CLOUD_ARTIFACT_S3_ACCESS_KEY"
"""Access key id. Travels by Secret, like :data:`TAVILY_API_KEY`."""

ARTIFACT_S3_SECRET_KEY = "URL4_CLOUD_ARTIFACT_S3_SECRET_KEY"
"""Secret access key. INVARIANT: Secret only — never a ConfigMap, never logged. A ConfigMap is
readable by anything with `get` on it and is printed in plain text by `helm get manifest`."""

RESULT_INLINE_CAP_BYTES = "URL4_CLOUD_RESULT_INLINE_CAP_BYTES"
"""Largest result body (UTF-8 bytes) that rides the result frame inline; anything larger is
spilled whole to :data:`ARTIFACTS_DIR`. Replaces the pre-OME-892 truncation cap."""

DEFAULT_RESULT_INLINE_CAP_BYTES = 524_288
"""512 KiB — half the historical 1 MiB wire cap, with the excess as envelope headroom.

WHY not 1 MiB (the measured failure this fixes, OME-949): the inline gate compares the RAW
UTF-8 result against this cap, but what is PUBLISHED is the CloudEvent envelope wrapping it
— ids, source, subject, time, plus JSON re-escaping of the result string. Measured on real
DRACO aggregates the envelope inflates the frame ≈6% over the raw result (619,026-byte
result → 657,732-byte frame), and a broker at the common 1 MiB `max_payload` default then
REJECTS the publish with ``nats: maximum payload exceeded`` — at the run's final frame,
after every model call has already been paid for. A raw result in roughly
(0.94 MiB, 1.00 MiB] therefore failed deterministically while both smaller (inline, fits)
and larger (spilled to an artifact reference, tiny) results succeeded. 512 KiB leaves two
times the observed envelope cost as margin; anything in (512 KiB, hard cap] spills to
:data:`ARTIFACTS_DIR`, which the SDK redeems transparently.
"""

RESULT_HARD_CAP_BYTES = "URL4_CLOUD_RESULT_HARD_CAP_BYTES"
"""Absolute result ceiling: past this the run FAILS with ``result_too_large`` instead of
spilling. The result is already in Runner RAM when checked (string + encoded copy ≈ 2-3× its
size), so size this to pod memory, not disk."""

BRIDGE_MEMORY_BUDGET_BYTES = "URL4_CLOUD_BRIDGE_MEMORY_BUDGET_BYTES"
"""Memory ceiling for the runner's event-bridge backlog: past it the run FAILS with
``BridgeOverflowError`` instead of buffering on. Converted to an event count at 512 B per
event (see ``runner.executor.EVENT_SIZE_ESTIMATE_BYTES``) — a bound on what the backlog may
COST, not on how wide a DAG may be (OME-906)."""

DEFAULT_BRIDGE_MEMORY_BUDGET_BYTES = 67_108_864
"""64 MiB ≈ 131 072 events at the 512 B estimate — 30× the widest burst measured (OME-906)
and 1/16 of :data:`DEFAULT_RESULT_HARD_CAP_BYTES`, in the same process."""

DEFAULT_RESULT_HARD_CAP_BYTES = 1_073_741_824
"""1 GiB — clears a plausible full-benchmark-scale report while catching runaway output."""

DEFAULT_NATS_URL = "nats://localhost:4222"
"""Fallback for an unset :data:`NATS_URL`. Lives beside the name it defaults so the two cannot
drift — every reader of the variable needs the same answer for "and if it is absent?"."""

IO_CONCURRENCY = "URL4_CLOUD_IO_CONCURRENCY"
"""Per-run downstream in-flight budget (OME-908): how many fetches this run may hold
against the gateway at once.

Deployed mode: the App writes it onto every Job from `Settings.runner_io_concurrency`
(a static per-run bound — each Job is its own process, so no shared scheduler exists to
be dynamic), and `build_executor` passes it to `url4.dag.run(concurrency=…)` where
URL4's own `BoundedIOLayer` enforces it.

Local mode NEVER writes it: the in-process runner instead fair-shares one gate across
its concurrent runs (`runner.fair_share`), which replaces — not stacks under — the
per-run bound. `InProcessJobRunner._env` pops any ambient copy for exactly that reason.

Not a secret: a concurrency hint, readable by design like every other per-run knob."""

# --- the sets the adapters and their tests are keyed off -------------------------------------
SECRET: frozenset[str] = frozenset()
"""Values that must NEVER appear literally in a Job spec.

A Job object is not a secret store — it is readable with ``get jobs`` RBAC alone, echoed by
``kubectl describe``/``-o yaml``, and captured in the create-call audit log. Anything listed here
must travel by reference (``valueFrom.secretKeyRef``); `test_job_env_contract.py` pins that, keyed
off this set.

Currently EMPTY, and that is the point: the caller's bearer token was the only member, and no run
carries one any more (see :data:`IDENTITY_HEADER_ENV`). The set stays so the contract test keeps
holding — re-adding a per-run secret must go through it rather than around it.
"""

REQUIRED = frozenset({TOPIC, EXPRESSION})
"""Absent ⇒ run mode raises ``runner.main.RunnerConfigError`` at boot (the PER-RUN env error; a
bad declared world is ``world_config.WorldConfigError``). Every adapter must write these."""

WRITTEN_BY_APP = frozenset(
    {
        TOPIC,
        EXPRESSION,
        JOB_DEADLINE_S,
        STREAM_GRACE_S,
        TRACEPARENT,
        AIGATEWAY_PROFILE,
        CACHE_PARTICIPATE,
        CACHE_MAX_AGE_S,
        EXTRA_MODELS,
        IO_CONCURRENCY,
        *IDENTITY_HEADER_ENV.values(),
    }
)
"""The per-run subset. A key the App writes that is NOT in here reaches nothing.

AIDEV-NOTE (corrected on OME-929): this used to claim "the direction that breaks silently is an
unread WRITE, not an unwritten READ (which simply falls back)". That reasoning is what let
`ARTIFACTS_DIR` sit in `DEPLOY_TIME` — documented as Helm-owned — while Helm set nothing, and
both halves fell back to their own pod-local `/tmp`. An unwritten READ falls back SILENTLY, and
whether that is benign depends entirely on what the fallback means: a byte count has a safe
default, a storage LOCATION does not. Both directions are now checked —
`test_deploy_time_chart_contract.py` asserts the chart actually writes these."""

DEPLOY_TIME = frozenset(
    {
        NATS_URL,
        AIGATEWAY_BASE_URL,
        AIGATEWAY_MODEL,
        TAVILY_API_KEY,
        RUNNER_CONFIG,
        ARTIFACTS_DIR,
        RESULT_INLINE_CAP_BYTES,
        RESULT_HARD_CAP_BYTES,
        BRIDGE_MEMORY_BUDGET_BYTES,
        ARTIFACT_STORE,
        ARTIFACT_S3_ENDPOINT_URL,
        ARTIFACT_S3_BUCKET,
        ARTIFACT_S3_REGION,
        ARTIFACT_S3_ACCESS_KEY,
        ARTIFACT_S3_SECRET_KEY,
    }
)
"""Helm owns these end-to-end. The App writing one would make it two sources of truth again."""

__all__ = [
    "AIGATEWAY_BASE_URL",
    "AIGATEWAY_MODEL",
    "AIGATEWAY_PROFILE",
    "ARTIFACTS_DIR",
    "BRIDGE_MEMORY_BUDGET_BYTES",
    "CACHE_MAX_AGE_S",
    "CACHE_PARTICIPATE",
    "DEFAULT_ARTIFACTS_DIR",
    "DEFAULT_BRIDGE_MEMORY_BUDGET_BYTES",
    "DEFAULT_NATS_URL",
    "DEFAULT_RESULT_HARD_CAP_BYTES",
    "DEFAULT_RESULT_INLINE_CAP_BYTES",
    "DEFAULT_STREAM_GRACE_S",
    "ARTIFACT_S3_ACCESS_KEY",
    "ARTIFACT_S3_BUCKET",
    "ARTIFACT_S3_ENDPOINT_URL",
    "ARTIFACT_S3_REGION",
    "ARTIFACT_S3_SECRET_KEY",
    "ARTIFACT_STORE",
    "DEFAULT_ARTIFACT_S3_REGION",
    "DEPLOY_TIME",
    "EXPRESSION",
    "EXTRA_MODELS",
    "IDENTITY_HEADER_ENV",
    "IO_CONCURRENCY",
    "JOB_DEADLINE_S",
    "NATS_URL",
    "REQUIRED",
    "RESULT_HARD_CAP_BYTES",
    "RESULT_INLINE_CAP_BYTES",
    "RUNNER_CONFIG",
    "STREAM_GRACE_S",
    "SECRET",
    "TAVILY_API_KEY",
    "TOPIC",
    "TRACEPARENT",
    "WRITTEN_BY_APP",
    "cache_policy_from_env",
    "io_concurrency_from_env",
    "cache_policy_to_env",
    "extra_models_to_env",
    "identity_from_env",
    "identity_from_headers",
    "identity_to_env",
]
