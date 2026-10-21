"""The paid lane's pinned Candidates — the Fusion panel every Benchmark runs, and the
Corrective Loop ifeval also runs — shared by smoke and pin tests.

Mental model: this is the lane's exam-taker roster, written down once. The smoke test
builds the panel from it; the free pin test checks the roster against the gateway's
seed list, so an unseeded model is caught for $0 before anyone presses the paid button.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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


def fusion_panel() -> _sf.Recipe:
    """Assemble the pinned Fusion panel (imported lazily so free tests never need sf)."""

    import screamingface as sf

    members = [sf.Model(model=model, params=MEMBER_PARAMS[model]) for model in MEMBER_MODELS]
    synthesizer = sf.Model(model=SYNTHESIZER_MODEL, params=PANEL_PARAMS, prompt=SYNTHESIS_PROMPT)
    return sf.Fanout(members, name="paid_smoke_panel") >> sf.Synthesize(synthesizer)


# --- The Corrective Loop entry (OME-1527 row 15b) ---------------------------------------
#
# Mental model: a Fusion never asks the Benchmark's mid-run check anything, so ifeval's
# Draft Feedback chain (checker words → check route → judge coaching → retry prompt) is
# never exercised by the Fusion entries above. One extra entry runs ifeval as a Corrective
# Loop: two weak members draft, the check marks each draft, and a no-pass round buys one
# coaching call and a retry.

#: The one Benchmark that also runs as a Corrective Loop when the press picks it.
CORRECTIVE_BENCHMARK: Final = "ifeval"

# WHY weak members on purpose: the entry exists to prove the retry chain, and a strong
# model passes round 1, so the chain never runs. These two are the members of the
# recorded ifeval Corrective Loop golden, seeded in the gateway as "IFEval-fallible by
# design", both non-reasoning (no member can spend its whole budget thinking), and both
# about $0.10 per million tokens (recorded: ministral-3b $0.10 in / $0.10 out, phi-4
# $0.07 in / $0.14 out).
# WHY the golden's exact prompt and params: same model, same bytes, temperature 0 is the
# best available bet that round 1 fails where it failed when recorded (see
# CORRECTIVE_CASE_LIMIT). 8192, not PANEL_PARAMS' 32768: it is what the golden sent, and
# phi-4's context window is 16k.
# INVARIANT: every model here is a gateway seed — `test_panel_models.py` pins it.
CORRECTIVE_MEMBER_MODELS: Final[tuple[str, str]] = (
    "openrouter/mistralai/ministral-3b-2512",
    "openrouter/microsoft/phi-4",
)
CORRECTIVE_MEMBER_PROMPT: Final = (
    "Answer the request accurately and completely. "
    "Follow every instruction and formatting constraint in the request."
)
CORRECTIVE_MEMBER_PARAMS: Final[dict[str, int | float]] = {"max_tokens": 8192, "temperature": 0.0}

# WHY haiku as the judge, not the golden's deepseek-v4-flash: the judge writes the
# coaching this entry exists to prove, and deepseek-v4-flash is a reasoning model. On the
# golden's Case 10 its coaching reply came back empty (all reasoning), so that Case died
# with model_token_cap instead of reaching round 2, and on Case 6 it wrote an answer
# instead of coaching. Haiku answers without thinking, already runs in every press as a
# Fusion member, and replies with a bare label on tie-breaks (the engine falls back to the
# first passer on anything else, so a bad label never fails a Case). No prompt: the loop
# hands the judge its role instructions, and a "write the answer" prompt would fight the
# coach's "do not write an answer". Cost: about $1 in / $5 out per million tokens.
CORRECTIVE_JUDGE_MODEL: Final = "openrouter/anthropic/claude-haiku-4.5"

CORRECTIVE_MAX_ROUNDS: Final = 3

#: How many Cases the Corrective Loop entry runs: the first 8 of ifeval's 541.
#: WHY 8: the SDK cannot pin Case ids (`evaluate` takes the first `limit`), and ifeval's
#: Case ids are 1..541 in the pinned split's row order, so the first 8 are fixed. In the
#: recorded golden (same two members, temperature 0; tape
#: `tests/e2e/fixtures/snapshots/ifeval.snapshot.gz`) no member passed round 1 on two of
#: them, so each bought coaching and ran all 3 rounds:
#:   Case 6 (exactly 3 markdown bullets in a ball gown vs sweats dialogue) and
#:   Case 8 (Matthias Algiers resume: fewer than 10 all-caps words, wrapped in quotes).
#: 8 is the smallest N whose first N Cases hold two of them; the next are Case 10 (whose
#: coach died, see above), 12, 24, 26, 34, 41, 43 and 49. Evidence: the tape keeps
#: responses only, in call time order; round 1 of all 50 Cases ran in Case order in one
#: recording session, and every later-round call (a coaching reply followed by both
#: members' retries) sits in a second session whose answers match those Cases' prompts.
#: Cost (recorded tokens for Cases 1..8, judge repriced to haiku): about 1.5 cents a press;
#: if every Case ran 3 rounds: 48 member calls + 16 coaching calls + 8 tie-breaks ≈ 7 cents.
CORRECTIVE_CASE_LIMIT: Final[int] = 8


def corrective_loop() -> _sf.CorrectiveLoop:
    """Assemble the Corrective Loop the ifeval entry runs (sf imported lazily, as above)."""

    import screamingface as sf

    members = [
        sf.Model(model=model, prompt=CORRECTIVE_MEMBER_PROMPT, params=CORRECTIVE_MEMBER_PARAMS)
        for model in CORRECTIVE_MEMBER_MODELS
    ]
    judge = sf.Model(model=CORRECTIVE_JUDGE_MODEL, params=PANEL_PARAMS)
    return sf.CorrectiveLoop(
        members=members,
        judge=judge,
        max_rounds=CORRECTIVE_MAX_ROUNDS,
        name="paid_smoke_corrective_loop",
    )


@dataclass(frozen=True, slots=True)
class SmokeRun:
    """How one press entry runs its Benchmark: which Candidate, how many Cases, its name.

    Worked example: the Benchmark ``ifeval`` under ``FUSION_RUN`` is the entry
    ``ifeval`` (2 Cases, Report ``ifeval.json``); under ``CORRECTIVE_RUN`` it is the
    entry ``ifeval · corrective loop`` (8 Cases, Report ``ifeval.corrective-loop.json``),
    so both Reports sit side by side in ``reports/``.
    """

    candidate: Callable[[], _sf.Recipe]
    limit: int
    #: Appended to the Benchmark id in the log and the overview; empty for the Fusion.
    label_suffix: str
    #: Appended to the Benchmark id in the kept Report's file name; empty for the Fusion.
    report_suffix: str
    #: True when the entry must show the retry chain ran (see `_corrective_chain.py`).
    reads_chain: bool

    def label(self, benchmark: str) -> str:
        """The entry's name in the log and the overview."""
        return benchmark + self.label_suffix

    def report_name(self, benchmark: str) -> str:
        """The kept Report's file name under ``reports/``."""
        return f"{benchmark}{self.report_suffix}.json"


FUSION_RUN: Final = SmokeRun(
    candidate=fusion_panel, limit=CASE_LIMIT, label_suffix="", report_suffix="", reads_chain=False
)
CORRECTIVE_RUN: Final = SmokeRun(
    candidate=corrective_loop,
    limit=CORRECTIVE_CASE_LIMIT,
    label_suffix=" · corrective loop",
    report_suffix=".corrective-loop",
    reads_chain=True,
)
