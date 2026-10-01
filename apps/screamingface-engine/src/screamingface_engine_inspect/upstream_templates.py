# pyright: reportMissingImports=false
# WHY file-level: it reads the `inspect` extra's packages, absent in the default
# (extra-less) install the typecheck gate runs against.
"""Choice templates an eval builds at run time, kept as constants a declaration can point at.

FEATURE: Task-replay Imported Benchmarks (OME-1273). A declaration names its choice template
as ``"module:attr"``. Most evals keep the template in a module constant; agieval builds its
own at run time, filling ``MULTIPLE_CHOICE_TEMPLATE_EN``'s few-shot and chain-of-thought slots,
so no attribute holds it and Case Preparation would fall back to inspect's default wording.
Each constant here is built from the eval's own constant, filled exactly as the eval fills it.

INVARIANT: each constant equals the template the eval's solver holds; the importer refuses
one that differs (``--choice-template``), and ``test_upstream_templates.py`` pins every one.
"""

from __future__ import annotations

from inspect_evals.agieval.utils import MULTIPLE_CHOICE_TEMPLATE_EN

#: agieval's English multiple-choice template with no few-shot examples and no
#: chain-of-thought: the defaults ``agie_lsat_ar`` and its siblings are called with.
AGIEVAL_MCQ_TEMPLATE_EN: str = MULTIPLE_CHOICE_TEMPLATE_EN.format(
    fewshot_string="",
    cot_string="",
    letters="{letters}",
    question="{question}",
    choices="{choices}",
)

__all__ = ["AGIEVAL_MCQ_TEMPLATE_EN"]
