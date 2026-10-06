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


def neutralise_litellm_debug(environment: MutableMapping[str, str]) -> None:
    """Force litellm's handler level off DEBUG for the runtime (OME-1050).

    WHY: at debug level litellm logs every outbound request as a curl command carrying the
    full body (messages included) and the raw response, and its handler writes to stderr,
    which is runtime.log. `LITELLM_LOG=DEBUG` is the first thing a user sets when a run
    misbehaves. aigateway's `request_hardening` already strips the per-request twin of this
    switch (`litellm_request_debug`).
    WHY set and never unset: litellm reads `os.getenv("LITELLM_LOG", "DEBUG")` at import, so
    an ABSENT variable is debug. WHY override an explicit choice: unlike the provider
    defaults above, this one exists to stop a leak, so the user's value does not win here.
    """
    environment["LITELLM_LOG"] = "WARNING"


def pin_litellm_redaction() -> None:
    """Stop litellm appending the request's messages to exception text (OME-1050)."""
    import litellm  # pyright: ignore[reportMissingImports]

    litellm.redact_messages_in_exceptions = True


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
                # OME-1056: the board's ranking filter needs this, and without it every LOCAL
                # seed leaves `case_count` NULL — so the filter is off in the one environment
                # where `limit=1` smoke runs are routine, and a one-case 1.0 still takes rank 1.
                # Conditional like the two below: keep the JSON projection sparse. The board's
                # SeedBenchmark parser turns absence into None, correctly clearing any stale
                # scope because these rows are passed as authoritative `engine_rows`.
                **(
                    {"case_count": case_count}
                    if (case_count := getattr(benchmark, "case_count", None))
                    else {}
                ),
                # Optional in the Engine, so absent stays absent rather than becoming null.
                **({"focus": focus} if (focus := getattr(benchmark, "focus", None)) else {}),
                **(
                    {"dataset_url": dataset_url}
                    if (dataset_url := getattr(benchmark, "dataset_url", None))
                    else {}
                ),
                # OME-1455: the provenance block and the verdict, in the board's SEED-ROW
                # shape (one `provenance` object, `saturation` beside it) — not the flat keys
                # the Engine's HTTP catalogue serves. The deployed board cuts the block off the
                # flat keys itself; this JSON goes straight to the board's seed-row parser,
                # which forbids unknown keys, so a flat key here would refuse the whole local
                # seed at boot (review finding on PR 1236).
                **_provenance_seed_fields(benchmark),
            }
            for benchmark in benchmarks
        ]
    )


def _provenance_seed_fields(benchmark: BenchmarkDefinition) -> dict[str, object]:
    """The provenance block and the verdict of one definition, read off its catalogue entry.

    The keys come from the SDK's catalogue decoder, so this twin never re-derives a verdict,
    re-types a link, or keeps a key list of its own. None of either when the definition has
    no catalogue entry (a bare stub), and no `provenance` when the entry carries no key.
    """

    from screamingface._engine.catalog_contract import PROVENANCE_KEYS

    entry = getattr(benchmark, "catalog_entry", None)
    if not callable(entry):
        return {}
    served = entry()
    if not isinstance(served, dict):
        return {}
    fields: dict[str, object] = {}
    block: dict[str, object] = {key: served[key] for key in PROVENANCE_KEYS if key in served}
    if block:
        fields["provenance"] = block
    if isinstance(served.get("saturation"), str):
        fields["saturation"] = served["saturation"]
    return fields


__all__: list[str] = []
