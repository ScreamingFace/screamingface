"""The two-turn exchange, byte-frozen.

INVARIANT: these templates are hashed into the benchmark's revision. A stray space is a different
benchmark, because judge-free grading makes the prompt the ONLY thing standing between a model and
its score.

Ported from the official MedXpertQA harness (eval/config/prompt_templates.py), whose published
leaderboard numbers use this exchange. Answer-only prompting is a different — and harsher —
protocol.
"""

from __future__ import annotations

# Official system role (prompt_templates.py).
# AIDEV-NOTE: the wording is medical because MedXpertQA is. A future non-medical MCQ benchmark must
# not import this constant — it needs its own, or the system prompt lies to the model.
ANSWER_SYSTEM = "You are a helpful medical assistant."

# Turn 1 — free step-by-step reasoning.
COT_PROMPT_TEMPLATE = "Q: {question}\nA: Let's think step by step."

# Turn 2 — commit. Sent as its OWN user message with no other content, which is what makes the
# committed letter come first and first-match extraction correct.
COT_TRIGGER_TEMPLATE = "Therefore, among {start} through {end}, the answer is"

# Turn 2 — the reply rule, sent on its own line before the trigger (OME-2018).
# NAMED DEVIATION: the official harness sends the trigger alone and relies on the model finishing
# the sentence. Today's chat models read a bare trigger as a new question and explain again: on
# the first paid run of revision 952ea002b0f5e3b0 the reply was 277 and 496 tokens of new
# reasoning on 2 of 2 Cases, and one Case changed its turn-1 answer from the key to a wrong
# letter. Checked on 6 real Cases with a local model (qwen3.8:27b): a bare trigger gave the
# letter first on 2 of 6 replies (mean 1,092 characters), this line on 6 of 6 (mean 10).
# WHY before the trigger, not after: the message still ends on the unfinished sentence, the
# harness's design, so the letter is the next thing the model writes.
COMMIT_INSTRUCTION = "Finish the sentence below with the option letter only, and nothing else."

__all__ = ["ANSWER_SYSTEM", "COMMIT_INSTRUCTION", "COT_PROMPT_TEMPLATE", "COT_TRIGGER_TEMPLATE"]
