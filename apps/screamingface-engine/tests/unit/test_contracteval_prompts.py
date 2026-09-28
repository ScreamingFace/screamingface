"""The prompt bytes ARE the exam — pinned, because nothing else protects them.

WHY this file exists (review of PR #984): this is a judge-free board, so the prompt is the only
thing standing between a model and its score — `prompts.py` says as much: "Do not rephrase or
summarize" is the difference between a correct answer and a zero. Those same bytes feed
`compute_revision`, so they define the board's published identity.

Before this, no test mentioned `SYSTEM_PROMPT`, `USER_TEMPLATE` or `render_case_input`. A
transcription typo was undetectable with every gate green, and would have moved our F1 off the
paper's while still claiming to be it.

Transcribed from https://github.com/olivialiu121/ContractEval (MIT) `proprietary_model.py` at
commit f2de74479bb067a13da2fd034972eec6905563b2 — system prompt lines 75-79, user template
lines 19-27.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.contracteval.definition import compute_revision
from screamingface_engine.benchmarks.contracteval.prompts import (
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    render_case_input,
)

#: Byte-for-byte from the reference. Do NOT re-wrap, re-indent, or "fix" the em dash.
_REFERENCE_SYSTEM_PROMPT = (
    "You are an assistant with strong legal knowledge, supporting senior lawyers "
    "by preparing reference materials.\n"
    "Given a Context and a Question, extract and return only the sentence(s) from the "
    "Context that directly address or relate to the Question.\n"
    "Do not rephrase or summarize in any way—respond with exact sentences from the Context "
    "relevant to the Question. If a relevant sentence contains unrelated elements such as "
    "page numbers or whitespace, include them exactly as they appear.\n"
    'If no part of the Context is relevant to the Question, respond with: "No related clause."\n'
)

# KNOWN one-byte delta from the pinned commit: the reference opens with `"Context: \n"`
# (trailing space); the board's `USER_TEMPLATE` — and therefore this pin — drops it. Recorded
# in `prompts.py`'s docstring; restoring the byte would re-address every route via
# `compute_revision`, so that decision belongs to the board owner, not a tidy-up here.
_REFERENCE_USER_TEMPLATE = "Context:\n```\n{context}\n```\nQuestion:\n```\n{question}\n```\n"


def test_the_system_prompt_is_byte_identical_to_the_reference() -> None:
    assert SYSTEM_PROMPT == _REFERENCE_SYSTEM_PROMPT


def test_the_user_template_is_byte_identical_to_the_reference() -> None:
    assert USER_TEMPLATE == _REFERENCE_USER_TEMPLATE


def test_the_em_dash_is_not_quietly_normalised_to_a_hyphen() -> None:
    """The reference writes "summarize in any way—respond"; a linter or editor that helpfully
    swaps the em dash for "-" or " - " changes the exam's bytes and its revision."""

    assert "any way—respond" in SYSTEM_PROMPT
    assert "any way-respond" not in SYSTEM_PROMPT


def test_the_abstain_string_the_grader_looks_for_is_the_one_we_ask_for() -> None:
    """INVARIANT: `grading.is_abstention` searches for "no related clause". If the prompt asked
    for different words, every correct abstention would score as a wrong answer."""

    from screamingface_engine.benchmarks.contracteval.grading import is_abstention

    assert '"No related clause."' in SYSTEM_PROMPT
    assert is_abstention("No related clause.") is True


def test_the_rendered_case_carries_the_instructions_then_the_contract_and_question() -> None:
    rendered = render_case_input("THE CONTRACT BODY", "Which state's law governs?")

    assert rendered.startswith(SYSTEM_PROMPT)
    assert "THE CONTRACT BODY" in rendered
    assert "Which state's law governs?" in rendered
    # The contract must precede the question, as in the reference template.
    assert rendered.index("THE CONTRACT BODY") < rendered.index("Which state's law governs?")


def test_both_prompts_are_inside_the_revision_hash() -> None:
    """WHY: a changed prompt is a changed exam and must re-address every route, or an
    already-recorded submission silently becomes incomparable.

    `compute_revision`'s injectable kwargs exist precisely so this can be proved.
    """

    baseline = compute_revision()

    assert compute_revision(system_prompt=SYSTEM_PROMPT + " ") != baseline
    assert compute_revision(user_template=USER_TEMPLATE + " ") != baseline
    assert compute_revision(dataset_revision="deadbeef") != baseline
    assert compute_revision() == baseline
