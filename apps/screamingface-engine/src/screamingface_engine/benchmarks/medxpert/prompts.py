"""The two-turn exchange, byte-frozen.

INVARIANT: these templates are hashed into the board's revision. A stray space is a different
exam, because judge-free grading makes the prompt the ONLY thing standing between a model and its
score.

Ported from the official MedXpertQA harness (eval/config/prompt_templates.py), whose published
leaderboard numbers use this exchange. Answer-only prompting is a different — and harsher —
protocol.
"""

from __future__ import annotations

# Official system role (prompt_templates.py).
# AIDEV-NOTE: the wording is medical because MedXpertQA is. A future non-medical MCQ board must
# not import this constant — it needs its own, or the system prompt lies to the model.
ANSWER_SYSTEM = "You are a helpful medical assistant."

# Turn 1 — free step-by-step reasoning.
COT_PROMPT_TEMPLATE = "Q: {question}\nA: Let's think step by step."

# Turn 2 — commit. Sent as its OWN user message with no other content, which is what makes the
# committed letter come first and first-match extraction correct.
COT_TRIGGER_TEMPLATE = "Therefore, among {start} through {end}, the answer is"

__all__ = ["ANSWER_SYSTEM", "COT_PROMPT_TEMPLATE", "COT_TRIGGER_TEMPLATE"]
