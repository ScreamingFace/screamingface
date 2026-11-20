# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A Judge row pins only params its model's providers accept (FutureX-Past bug, 2026-11-19).

FEATURE: judged Benchmarks grade on the hosted Engine.
STORY: as a Candidate author, I run FutureX-Past and every level-3/4 Case is graded, not
failed as scorer_error.

WHY: the gateway sends `provider.require_parameters = true` on every OpenRouter call
(apps/aigateway/docs/openrouter-routing-controls.md). OpenRouter then refuses a call when no
endpoint for the model accepts every param. No endpoint for OpenAI's gpt-5 models lists
`temperature` (checked 2026-11-19), so a pinned temperature fails every Judge call. This is the
offline half of the check: it needs no network and calls no model.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402

#: Judge models whose OpenRouter endpoints expose no temperature control.
_NO_TEMPERATURE_PREFIX: str = "openrouter/openai/gpt-5"


def test_no_openai_reasoning_judge_pins_temperature() -> None:
    """INVARIANT: no Judge on an OpenAI gpt-5 model pins `temperature` (OME-1602's house rule)."""

    offenders: list[str] = [
        row.key
        for row in BENCHMARKS
        if row.judge is not None
        and row.judge.model.startswith(_NO_TEMPERATURE_PREFIX)
        and any(name == "temperature" for name, _ in row.judge.params)
    ]

    assert offenders == [], (
        f"{offenders}: these Judges pin temperature on {_NO_TEMPERATURE_PREFIX}*. OpenRouter has "
        "no endpoint for that model that accepts it, and the gateway forces require_parameters, "
        "so every Judge call fails. Leave temperature out, as on the other gpt-5.4 Judge rows."
    )


def test_futurex_past_judge_sends_no_temperature() -> None:
    """The FutureX-Past Judge sends the house gpt-5.4 params: no search, a 4,096-token cap."""

    row = next(row for row in BENCHMARKS if row.key == "futurex_past")

    assert row.judge is not None
    assert row.judge.params == (("web_search", "false"), ("max_tokens", "4096"))
