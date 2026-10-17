"""Paid E2E for the E4b part 3 signal sources (recipes PRD RC#8, RC#9).

FEATURE: the declared logprob source reads the reply logprobs of a live OpenRouter model, and a
model that refuses logprobs fails the Case with the engine code ``logprobs_unsupported``.
STORY: as a researcher, I run the README logprob recipe on the pinned model and see a finite value,
and I see the failure text when a model cannot return logprobs.
INVARIANT: the SDK preflight passes the refusing model (the catalog marks it supported), so the
failure comes from the runtime path, not from the SDK.
WHY paid: only a live OpenRouter call proves that the pinned model returns logprobs and that a
refusing model fails with the engine code.
Runs only on the paid button (tests/conftest.py deselects tests/paid otherwise).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final

import pytest
from conftest import PaidStack

if TYPE_CHECKING:
    import screamingface as _sf

pytestmark = pytest.mark.paid

# Unit 1 ledger (docs/work/2026-10-15-e4b-signal-sources.md, "Unit 1 note"):
PINNED_LOGPROB_MODEL: Final = "openrouter/openai/gpt-4o-mini"
# The gateway catalog marks logprobs `supported` for this model, but OpenRouter refuses it:
# the SDK preflight lets it pass, and the runtime path must give logprobs_unsupported.
UNCATALOGUED_REFUSING_MODEL: Final = "openrouter/anthropic/claude-haiku-4.5"
_BENCHMARK: Final = "inspect-gsm8k"  # short answers: the cheapest board with one Case
_PARAMS: Final[dict[str, int | float]] = {"max_tokens": 1024, "temperature": 0.0}


def _logprob_fusion(model: str) -> _sf.Fusion:
    import screamingface as sf

    return sf.Fusion(
        [sf.Model(model=model, params=_PARAMS)],
        signals={"lp": sf.Logprob("mean")},
        synthesizer=sf.Pick(by_signal=sf.signal("lp"), order="max"),
    )


def _evaluate_one_case(paid_stack: PaidStack, model: str, report_name: str) -> _sf.CaseResult:
    import screamingface as sf

    with sf.Client(engine_url=paid_stack.engine_url) as client:
        try:
            report = client.evaluate(
                _logprob_fusion(model), benchmark=_BENCHMARK, limit=1, progress=False
            )
        except sf.ScreamingFaceError as exc:
            pytest.fail(f"{model}: the run did not reach the model call — {exc}", pytrace=False)
    reports = paid_stack.log_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    report.export(reports / f"{report_name}.json")  # debug evidence, as the smoke does
    cases = report.candidates.only.cases
    assert len(cases) == 1
    return cases[0]


def test_pinned_openrouter_model_returns_logprobs(paid_stack: PaidStack) -> None:
    case = _evaluate_one_case(paid_stack, PINNED_LOGPROB_MODEL, "signal_sources_pinned")

    assert [failure.code for failure in case.failures] == []
    combine = next(op.combine for op in case.operations or () if op.combine is not None)
    value = combine.members[0].signals["lp"]
    assert value is not None and math.isfinite(value) and value <= 0.0  # RC-3
    assert combine.declared == {"lp": {"source": "logprob", "form": "mean"}}


def test_uncatalogued_refusing_model_fails_logprobs_unsupported(paid_stack: PaidStack) -> None:
    case = _evaluate_one_case(paid_stack, UNCATALOGUED_REFUSING_MODEL, "signal_sources_refusal")

    codes = [failure.code for failure in case.failures]
    assert "logprobs_unsupported" in codes, codes  # RC-E1, Q5
    assert "unsupported_model_parameter" not in codes  # the preflight did not stop it (P12)
    assert case.status != "scored"
    refusal = next(f for f in case.failures if f.code == "logprobs_unsupported")
    # fixed engine text (P13); the first 30 characters are checked in the ledger (unit 3 constant)
    assert "may not return token log-probabilities" in refusal.message
