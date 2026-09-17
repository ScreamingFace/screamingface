"""The pinned ContractEval Candidate instructions.

INVARIANT: byte-for-byte from the reference harness — `proprietary_model.py` lines 74-80 for the
system prompt and lines 18-27 for the user template (MIT,
https://github.com/olivialiu121/ContractEval). These bytes feed the board's revision hash, so an
edit here is a new benchmark identity, not a tweak.

WHY the wording matters more than usual: the grader is pure string containment, so "Do not
rephrase or summarize in any way" is not style guidance — it is the difference between a correct
answer and a zero. Likewise the exact abstain string is what `grading.is_abstention` looks for.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are an assistant with strong legal knowledge, supporting senior lawyers \
by preparing reference materials.
Given a Context and a Question, extract and return only the sentence(s) from the Context that \
directly address or relate to the Question.
Do not rephrase or summarize in any way—respond with exact sentences from the Context relevant \
to the Question. If a relevant sentence contains unrelated elements such as page numbers or \
whitespace, include them exactly as they appear.
If no part of the Context is relevant to the Question, respond with: "No related clause."
"""

USER_TEMPLATE = """Context:
```
{context}
```
Question:
```
{question}
```
"""


def render_case_input(context: str, question: str) -> str:
    """The exact Candidate-facing text for one Case — system instructions plus the pair."""

    return f"{SYSTEM_PROMPT}\n{USER_TEMPLATE.format(context=context, question=question)}"


__all__ = ["SYSTEM_PROMPT", "USER_TEMPLATE", "render_case_input"]
