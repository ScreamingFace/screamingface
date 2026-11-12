"""Starting a run on the job runner: what the start route and the Engine's driver both do.

FEATURE: a detached Run (OME-1837, E5 P2 plan E3). The driver starts a Candidate the way the start
route starts a run, so model admission and the schedule call live here, free of any Request. The
runner's own errors propagate (`StoppedBeforeSchedule`, `JobAlreadyExists`, `JobRunnerAtCapacity`,
`RunQueueUnavailable`); the route maps them to its Problems, and the driver to a retry or a stop.

LAYERING: control plane (`.claude/scripts/check_layering.py`).
"""

from __future__ import annotations

from collections.abc import Mapping

from screamingface_engine import job_env
from screamingface_engine.benchmarks.expression_routes import local_route_paths
from screamingface_engine.catalog.admission import RunModelAdmission, is_dynamically_admissible
from screamingface_engine.catalog.port import Credential
from screamingface_engine.ports import IdentityAwareJobRunner
from screamingface_engine.world.models.registry import decode_route_id
from url4.streaming.protocol import CachePolicy


def named_dynamic_models(url4: str) -> tuple[str, ...]:
    """The dynamically admissible real model ids ``url4`` routes to, sorted.

    Each route path is decoded (OME-873 ``~`` escape) before the shape gate, so the id is the
    gateway's real one — what ``RunModelAdmission.admit_run_models`` expects. Declared routes
    (``/benchmarks/*``, a declared namespace) never pass the gate. Never raises: an unreadable
    url4 names nothing.
    """
    ids = {decode_route_id(path.removeprefix("/")) for path in local_route_paths(url4)}
    return tuple(sorted(model for model in ids if is_dynamically_admissible(model)))


async def admit_named_models(
    model_admission: RunModelAdmission | None,
    url4: str,
    *,
    identity: Mapping[str, str] | None,
    traceparent: str | None,
) -> None:
    """Admit the dynamically admissible models ``url4`` names, before the run is scheduled.

    FEATURE: run any OpenRouter model (OME-878) from a client that never probes — the SDK's url4
    replay (``sf.evaluate("<url4>")``), a raw HTTP caller, the Engine's driver.

    INVARIANT (ordering): this runs BEFORE ``job_runner.schedule``, which snapshots the admitted
    overlay into the run's env (``queue_runner.py`` / ``inprocess.py``). Admission and snapshot
    in one call on one replica: an Engine restart since an earlier probe, or a probe served by
    another replica, cannot leave the run's world without its model.

    INVARIANT (no new REST contract): best-effort. A refusal never raises here; the run is
    scheduled and reports the failure on its own stream, as before. The ask runs as the caller —
    the credential ``GET /v1/model-parameters`` derives from the same identity headers.
    """
    if model_admission is None:
        return
    model_ids = named_dynamic_models(url4)
    if model_ids:
        await model_admission.admit_run_models(
            Credential.derive(identity), model_ids, traceparent=traceparent
        )


async def schedule_run(
    job_runner: IdentityAwareJobRunner,
    model_admission: RunModelAdmission | None,
    topic: str,
    url4: str,
    deadline_s: int,
    *,
    cache: CachePolicy,
    traceparent: str | None = None,
    identity: Mapping[str, str] | None = None,
    answer_seed: int | None = None,
    client_version: str | None = None,
    shape: job_env.RunShape = "expression",
    capture: bool = False,
    replay_frozen_copy: str | None = None,
    result_prefix: str | None = None,
    exclusive: bool = False,
) -> None:
    """Admit the models ``url4`` names, then schedule the run.

    INVARIANT (OME-1381): both scheduling ingresses refuse a stated ``X-Profile`` before this hop,
    and the port cannot represent a selector, so every run this Engine schedules is selector-less.
    """
    # INVARIANT (spec 02 §5.3 1a): a frozen-copy replay never asks the gateway to admit a model.
    if replay_frozen_copy is None:
        await admit_named_models(model_admission, url4, identity=identity, traceparent=traceparent)
    await job_runner.schedule(
        topic,
        url4,
        deadline_s,
        traceparent=traceparent,
        identity=identity,
        cache=cache,
        answer_seed=answer_seed,
        client_version=client_version,
        shape=shape,
        capture=capture,
        replay_frozen_copy=replay_frozen_copy,
        result_prefix=result_prefix,
        exclusive=exclusive,
    )


__all__ = ["admit_named_models", "named_dynamic_models", "schedule_run"]
