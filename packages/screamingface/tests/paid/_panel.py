"""The paid lane's one Fusion panel — pinned models, shared by smoke and pin tests.

Mental model: this is the lane's exam-taker roster, written down once. The smoke test
builds the panel from it; the free pin test checks the roster against the gateway's
seed list, so an unseeded model is caught for $0 before anyone presses the paid button.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import screamingface as _sf

# INVARIANT: every model here must be a gateway seed (aigateway's openrouter plugin
# settings). A model missing from the seeds resolves at discovery time but 404s at
# run time — the exact bug class this lane exists to catch, so the lane must never
# carry it itself. `test_panel_models.py` pins this for free.
MEMBER_MODELS: Final[tuple[str, str]] = (
    "openrouter/qwen/qwen3.7-flash",
    "openrouter/deepseek/deepseek-v4-flash-0731",
)
SYNTHESIZER_MODEL: Final[str] = "openrouter/google/gemini-3-flash-preview"

# WHY temperature 0 and a generous cap: the smoke asserts the pipe, not the answer —
# determinism-ish output and headroom against `model_token_cap` keep the signal about
# wiring, not sampling luck. Same shape as examples/12_inspect_evals_benchmarks.ipynb.
PANEL_PARAMS: Final[dict[str, int | float]] = {"max_tokens": 8192, "temperature": 0.0}

# WHY board-agnostic wording: one panel serves all 17 imported boards (math, MCQ,
# yes/no), so the prompt asks for reconciliation and one committed final answer
# without assuming any answer format.
SYNTHESIS_PROMPT: Final[str] = (
    "You are given several models' answers to one question. Weigh their reasoning, "
    "resolve any disagreement by re-deriving the disputed step, and commit to a "
    "single final answer in the format the question asks for."
)

#: One evaluation = this many Cases per board — the cost cap that keeps a whole-shelf
#: smoke under a dollar.
CASE_LIMIT: Final[int] = 2


def fusion_panel() -> _sf.Fusion:
    """Assemble the pinned Fusion panel (imported lazily so free tests never need sf)."""

    import screamingface as sf

    members = [sf.Model(model=model, params=PANEL_PARAMS) for model in MEMBER_MODELS]
    synthesizer = sf.Model(model=SYNTHESIZER_MODEL, params=PANEL_PARAMS, prompt=SYNTHESIS_PROMPT)
    return sf.Fusion(name="paid_smoke_panel", members=members, synthesizer=synthesizer)
