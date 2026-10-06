"""The paid lane's one Fusion panel — pinned models, shared by smoke and pin tests.

Mental model: this is the lane's exam-taker roster, written down once. The smoke test
builds the panel from it; the free pin test checks the roster against the gateway's
seed list, so an unseeded model is caught for $0 before anyone presses the paid button.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    import screamingface as _sf

# INVARIANT: every model here must be a gateway seed (aigateway's openrouter plugin
# settings). A model missing from the seeds resolves at discovery time but 404s at
# run time — the exact bug class this lane exists to catch, so the lane must never
# carry it itself. `test_panel_models.py` pins this for free.
# WHY one reasoning member and one that answers without thinking: a Fusion Case needs
# EVERY member's answer, so one member burning its whole budget on thinking kills the
# Case. deepseek-v4-flash did that on 4 of 48 Cases in one press, zeroing both lab_bench
# DNA boards (cloning_scenarios, seqqa) and so leaving their grading unproven. Haiku
# answers without thinking, so it always finishes; qwen stays as the reasoning member,
# because the engine's reasoning-only code (reasoning-field parsing, the token-cap and
# reasoning-only-reply codes, reasoning-token accounting) is proven only by a live
# reasoning model.
MEMBER_MODELS: Final[tuple[str, str]] = (
    "openrouter/qwen/qwen3.7-flash",
    "openrouter/anthropic/claude-haiku-4.5",
)
SYNTHESIZER_MODEL: Final[str] = "openrouter/google/gemini-3-flash-preview"

# WHY temperature 0 and a generous cap: the smoke asserts the pipe, not the answer —
# determinism-ish output and headroom against `model_token_cap` keep the signal about
# wiring, not sampling luck.
# WHY 32768 for every board: the first press ran out of tokens at 8192 on reasoning
# boards (aime24/25, frontierscience, lab_bench cloning), leaving no graded Case to
# prove the grading pipe. Short-answer boards stop long before the cap, so raising it
# for all of them costs nothing, and there is no list of reasoning boards to maintain.
PANEL_PARAMS: Final[dict[str, int | float]] = {"max_tokens": 32768, "temperature": 0.0}

# WHY qwen alone reasons at "low" (run 37442602029, 2026-10-06): after #1254's Task replay
# changed inspect's shuffle, `slice=0:2` on lab_bench cloning_scenarios picks two longer DNA
# Cases. qwen spent the whole 32768-token cap on reasoning on both (65536 reasoning tokens)
# and wrote no answer, so both Fusion Cases died with `model_token_cap`; on 2026-10-02 the
# old pair passed at ~15k output tokens. `reasoning_effort="low"` bounds the thinking while
# keeping qwen a live reasoning member. Only qwen gets it: haiku and the synthesizer keep
# PANEL_PARAMS, so only qwen's calls re-key the cache. The gateway's OpenRouter plugin
# forwards the field verbatim (OME-993, enum low/medium/high).
# WHY qwen alone also gets 65536 (paid run 37453343696): "low" did not stop it — one of the
# two cloning Cases still spent all 32768 tokens on reasoning (57.8k reasoning over the pair),
# so the board passed on 1/2 graded, one capped Case from red. 65536 is qwen3.7-flash's own
# max_completion_tokens on OpenRouter, so there is no higher cap to fall back on.
# INVARIANT: every other call keeps PANEL_PARAMS (32768) — `test_panel_models.py` pins it.
MEMBER_PARAMS: Final[dict[str, Mapping[str, int | float | str]]] = {
    "openrouter/qwen/qwen3.7-flash": {
        **PANEL_PARAMS,
        "max_tokens": 65536,
        "reasoning_effort": "low",
    },
    "openrouter/anthropic/claude-haiku-4.5": PANEL_PARAMS,
}

# WHY board-agnostic wording: one panel serves every imported board (math, MCQ,
# yes/no, free-text science), so the prompt asks for reconciliation and one committed final answer
# without assuming any answer format.
SYNTHESIS_PROMPT: Final[str] = (
    "You are given several models' answers to one question. Weigh their reasoning, "
    "resolve any disagreement by re-deriving the disputed step, and commit to a "
    "single final answer in the format the question asks for."
)

#: One evaluation = this many Cases per board — the cost cap that keeps a whole-shelf
#: smoke to a few dollars at most.
CASE_LIMIT: Final[int] = 2

#: Boards evaluated at once. More boards at once means a shorter wall time at the same
#: spend, but also more provider 429s, and a board whose Cases all hit 429 fails with
#: "no Case graded". Four keeps flash-model 429s rare.
BOARD_CONCURRENCY: Final[int] = 4


def fusion_panel() -> _sf.Fusion:
    """Assemble the pinned Fusion panel (imported lazily so free tests never need sf)."""

    import screamingface as sf

    members = [sf.Model(model=model, params=MEMBER_PARAMS[model]) for model in MEMBER_MODELS]
    synthesizer = sf.Model(model=SYNTHESIZER_MODEL, params=PANEL_PARAMS, prompt=SYNTHESIS_PROMPT)
    return sf.Fusion(name="paid_smoke_panel", members=members, synthesizer=synthesizer)
