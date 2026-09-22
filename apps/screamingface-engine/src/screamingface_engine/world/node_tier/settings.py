"""The node tier's settings: every number on its ladder, its env names, and their validation.

FEATURE (unit 3, prd/03): the sync surface's timeout/admission ladder, in ONE place (T4
refactor). No literal for any of these numbers may appear anywhere else — a second copy is how
a ladder ends up non-monotonic.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from screamingface_engine import job_env

# WHY `__package__`: the tier was one module before FX-21, and its log lines named
# `screamingface_engine.world.node_tier`. Every module of the package logs under that one name.
logger = logging.getLogger(__package__)

_NODE_ENV = "URL4_CLOUD_NODE_"
REQUEST_TIMEOUT_ENV = f"{_NODE_ENV}REQUEST_TIMEOUT_S"
AIGATEWAY_TIMEOUT_ENV = f"{_NODE_ENV}AIGATEWAY_TIMEOUT_S"
SPILL_TIMEOUT_ENV = f"{_NODE_ENV}SPILL_TIMEOUT_S"
MAX_INFLIGHT_PER_WORKER_ENV = f"{_NODE_ENV}MAX_INFLIGHT_PER_WORKER"
WORKERS_ENV = f"{_NODE_ENV}WORKERS"
RETRY_AFTER_ENV = f"{_NODE_ENV}RETRY_AFTER_S"
ARTIFACT_URL_TTL_ENV = f"{_NODE_ENV}ARTIFACT_URL_TTL_S"
HOST_ENV = f"{_NODE_ENV}HOST"
PORT_ENV = f"{_NODE_ENV}PORT"
METRICS_PORT_ENV = f"{_NODE_ENV}METRICS_PORT"
LOG_LEVEL_ENV = f"{_NODE_ENV}LOG_LEVEL"

# WHY the env names are local to this package rather than in `job_env`: `job_env` is the JOB's
# contract (per-run and per-deploy values the chart writes onto a run), while these are the node
# tier's own Deployment. They move into `job_env` with the Helm unit that actually writes them;
# until then a name here cannot drift against a chart value that does not exist yet.

NODE_DEFAULT_RESULT_HARD_CAP_BYTES = 64 * 1024 * 1024
"""The node tier's own hard cap (FX-11): 64 MiB, not the run path's 1 GiB.

WHY a separate default under the SAME env name (`job_env.RESULT_HARD_CAP_BYTES`): one sync
request holds its whole body in the pod's memory while it decides, and the node serves many
callers at once. The run path's ceiling is sized for one Job per pod. An operator who sets the
env var still sets both paths with one value."""


class NodeTierError(ValueError):
    """The node tier cannot serve: bad settings, a refused store or key, or no url4 node."""


@dataclass(frozen=True, slots=True)
class NodeTierSettings:
    """Every number on the node tier's timeout/admission ladder, in ONE place (T4 refactor).

    The defaults are the plan's (`contracts.md` timeout ladder, `ans:Q5`): the request wrapper
    fails at 30 s, aigateway at 28 s so the inner failure wins and the caller gets a 502 naming
    the cause, the spill write gets its own 4 s AFTER the request budget (§2.2), and the
    in-flight cap is ``max_inflight_per_worker × workers``.

    ``workers`` is a MULTIPLIER for the in-flight cap and nothing else (RD3): the tier runs ONE
    process per pod, and ``workers`` only scales how many requests that one process admits.

    ``artifact_url_ttl_s`` (OQ-3.2) is centralized here beside the ladder numbers: the node
    signs a spilled artifact's redirect with this TTL and the App enforces the same expiry from
    the signature, so the number has one home. `result_inline_cap_bytes`/`result_hard_cap_bytes`
    are here for the same reason — the sync spill path must decide without a second config read.
    """

    request_timeout_s: float = 30.0
    aigateway_timeout_s: float = 28.0
    spill_timeout_s: float = 4.0
    max_inflight_per_worker: int = 2
    workers: int = 1
    retry_after_s: int = 1
    artifact_url_ttl_s: int = 600
    # WHY the caps live here TOO, even though `job_env` owns their names: the sync tier must
    # refuse an over-hard-cap body without a second read of the environment, and a test needs
    # one seam to aim the boundary at an exact byte. They read the SAME `URL4_CLOUD_RESULT_*`
    # names the run path reads, so the two paths cannot be capped by a one-sided edit.
    result_inline_cap_bytes: int = job_env.DEFAULT_RESULT_INLINE_CAP_BYTES
    result_hard_cap_bytes: int = NODE_DEFAULT_RESULT_HARD_CAP_BYTES
    host: str = "0.0.0.0"
    port: int = 9109
    metrics_port: int = 9110
    log_level: str = "info"

    @property
    def max_inflight(self) -> int:
        """``max_inflight_per_worker × workers``: the bound url4's admission gate enforces."""
        return self.max_inflight_per_worker * max(1, self.workers)

    def validate(self) -> None:
        """Refuse a ladder that cannot work, at boot (FX-13).

        WHY here and not in `from_env`: `from_env` stays tolerant of a value it cannot PARSE (the
        shipped default is the safe answer to a typo). A value that parses but breaks the ladder
        has no safe default — a tier that admits nothing, or whose aigateway budget outlives its
        request budget, serves wrong answers rather than none.

        Raises:
            NodeTierError: naming the first setting that breaks the ladder.
        """
        if self.max_inflight < 1:
            raise NodeTierError(f"max_inflight must be at least 1, got {self.max_inflight}")
        if self.aigateway_timeout_s >= self.request_timeout_s:
            raise NodeTierError(
                f"aigateway_timeout_s ({self.aigateway_timeout_s:g}) must be less than "
                f"request_timeout_s ({self.request_timeout_s:g}), so the inner failure wins"
            )
        if self.spill_timeout_s <= 0:
            raise NodeTierError(f"spill_timeout_s must be positive, got {self.spill_timeout_s:g}")
        # WHY inverted caps are NOT refused (FX-13 as amended): the hard-cap check runs first
        # (`decide_result_delivery`), so an inline cap above the hard cap cannot bypass it.

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> NodeTierSettings:
        """Resolve the tier's settings from its Deployment env, tolerantly and per field.

        INVARIANT: never raises on an unparseable value — this runs at boot, and the safe answer
        to a typo'd knob is the shipped default, not a pod that cannot start. A wrong-but-running
        tier is diagnosable from `/metrics`; a crashing one is not. A value that parses but breaks
        the ladder is `validate`'s to refuse.
        """
        return cls(
            request_timeout_s=_float(env, REQUEST_TIMEOUT_ENV, 30.0),
            aigateway_timeout_s=_float(env, AIGATEWAY_TIMEOUT_ENV, 28.0),
            spill_timeout_s=_float(env, SPILL_TIMEOUT_ENV, 4.0),
            max_inflight_per_worker=_int(env, MAX_INFLIGHT_PER_WORKER_ENV, 2),
            workers=_int(env, WORKERS_ENV, 1),
            retry_after_s=_int(env, RETRY_AFTER_ENV, 1),
            artifact_url_ttl_s=_int(env, ARTIFACT_URL_TTL_ENV, 600),
            result_inline_cap_bytes=_int(
                env, job_env.RESULT_INLINE_CAP_BYTES, job_env.DEFAULT_RESULT_INLINE_CAP_BYTES
            ),
            result_hard_cap_bytes=_int(
                env, job_env.RESULT_HARD_CAP_BYTES, NODE_DEFAULT_RESULT_HARD_CAP_BYTES
            ),
            host=env.get(HOST_ENV) or "0.0.0.0",
            port=_int(env, PORT_ENV, 9109),
            metrics_port=_int(env, METRICS_PORT_ENV, 9110),
            log_level=env.get(LOG_LEVEL_ENV) or "info",
        )


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("ignoring unparseable %s=%r", name, raw)
        return default


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("ignoring unparseable %s=%r", name, raw)
        return default


__all__ = [
    "AIGATEWAY_TIMEOUT_ENV",
    "ARTIFACT_URL_TTL_ENV",
    "HOST_ENV",
    "LOG_LEVEL_ENV",
    "MAX_INFLIGHT_PER_WORKER_ENV",
    "METRICS_PORT_ENV",
    "NODE_DEFAULT_RESULT_HARD_CAP_BYTES",
    "PORT_ENV",
    "REQUEST_TIMEOUT_ENV",
    "RETRY_AFTER_ENV",
    "SPILL_TIMEOUT_ENV",
    "WORKERS_ENV",
    "NodeTierError",
    "NodeTierSettings",
]
