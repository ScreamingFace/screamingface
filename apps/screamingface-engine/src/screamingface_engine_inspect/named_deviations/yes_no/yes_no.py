# pyright: reportMissingImports=false
# WHY file-level: this module imports inspect_ai, absent in the default (extra-less) install the
# typecheck gate runs against; it is loaded only at grading time, behind the `inspect` extra.
"""PAWS and BoolQ marked on a bare Yes or No, as inspect_evals now marks them.

Think of it as a teacher who only accepts the answer box: the reply must be Yes or No and
nothing else, apart from spaces and punctuation around it (`No.`, `**Yes**`). Both evals'
prompts already ask for exactly that.

NAMED DEVIATION — adopted from inspect_evals PR #2334 (merged 2026-09-16, after our v0.20.0
pin; https://github.com/UKGovernmentBEIS/inspect_evals/pull/2334, issue #2331). COPIED
VERBATIM: each scorer below returns the exact `pattern(r"...")` expression the merged PR puts
in its Task's `scorer=`, at merge commit 2999eaad:
https://github.com/UKGovernmentBEIS/inspect_evals/blob/2999eaadad35edebada59bac4a687793c11d1c3c/src/inspect_evals/paws/paws.py#L41
and
https://github.com/UKGovernmentBEIS/inspect_evals/blob/2999eaadad35edebada59bac4a687793c11d1c3c/src/inspect_evals/boolq/boolq.py#L53
Ours is only the `@scorer` factory around each expression, forced by the pin: a row names its
scorer by import path, and v0.20.0's Tasks cannot be edited. v0.20.0 marks:

    - PAWS with `includes()`, a case-insensitive substring test: "no" sits inside "cannot", so
      "I cannot determine this." is right on every No Case. A model that always refuses that
      way scores 4,464 / 8,000 = 55.8% without answering anything.
    - BoolQ with `pattern(r"(Yes|No).?\\Z")`: "I don't know" ends in "no" plus one letter, so
      it is right on all 1,237 No Cases.

What changes the other way: a reply that wraps the label in prose ("The answer is: No") was
right before and is now wrong, as inspect_evals decided; the prompts ask for the bare word.

INVARIANT: these patterns are Benchmark identity; this file's source is hashed into the paws
and boolq revisions.
"""

from __future__ import annotations

from inspect_ai.scorer import Scorer, accuracy, pattern, scorer, stderr


@scorer(metrics=[accuracy(), stderr()])
def paws_yes_no() -> Scorer:
    """PAWS: right only when the whole reply is the expected Yes or No."""

    return pattern(r"\A\W*\b(Yes|No)\b\W*\Z")


@scorer(metrics=[accuracy(), stderr()])
def boolq_yes_no() -> Scorer:
    """BoolQ: right only when the whole reply is the expected Yes or No."""

    return pattern(r"\A[\W_]*(Yes|No)[\W_]*\Z")
