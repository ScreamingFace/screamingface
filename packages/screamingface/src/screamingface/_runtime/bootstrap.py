from __future__ import annotations

import json
from collections.abc import Iterable, MutableMapping
from typing import Protocol


class BenchmarkDefinition(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def revision(self) -> str: ...


# Local gateway environment defaults (OME-1001). Every entry is a setdefault: an
# explicit operator choice always wins.
# WHY no AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE here: the gateway documents provider
# startup bootstrap as opt-in — the user authorizes profiles explicitly rather than
# finding a "default" profile they never consented to. Anyone who wants it exports
# the variable themselves.
LOCAL_GATEWAY_DEFAULTS = {
    # The local BYOK provider plugin defaults to disabled; without it the Gateway
    # catalog contains no openrouter/* models for the Engine to project.
    "AIGW_OPENROUTER_ENABLED": "true",
    # WHY 32: one Engine run fans out up to 32 concurrent model calls (url4
    # DEFAULT_RUN_CONCURRENCY) but the gateway's per-provider default admits 4;
    # queued calls wait inside the gateway with no admission deadline, burn the
    # Engine's 600s per-call budget, and full HealthBench evals die on calls that
    # never reached OpenRouter (OME-889; long-term admission fix: OME-886).
    "AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES": '{"openrouter": 32}',
}


def enable_local_providers(environment: MutableMapping[str, str]) -> None:
    """Apply the local gateway defaults while preserving explicit operator choices."""

    for name, value in LOCAL_GATEWAY_DEFAULTS.items():
        environment.setdefault(name, value)


def scoreboard_seed_json(benchmarks: Iterable[BenchmarkDefinition]) -> str:
    """Project the Engine-owned registry onto Scoreboard's registration contract.

    This is the local twin of what a deployment does over HTTP: the same fields the Engine's
    ``/v1/benchmarks`` catalogue publishes, read by import because a local stack runs the
    Engine and the board in one virtualenv (OME-904). Keeping the two projections in step is
    what makes a local leaderboard look like the deployed one.
    """

    return json.dumps(
        [
            {
                "id": benchmark.id,
                "display_name": benchmark.title,
                "description": benchmark.description,
                "revision": benchmark.revision,
                # Optional in the Engine, so absent stays absent rather than becoming null.
                **({"focus": focus} if (focus := getattr(benchmark, "focus", None)) else {}),
                **(
                    {"dataset_url": dataset_url}
                    if (dataset_url := getattr(benchmark, "dataset_url", None))
                    else {}
                ),
            }
            for benchmark in benchmarks
        ]
    )


__all__: list[str] = []
