"""The KEYWORDS labels a Router regex selector gives its question, recomputed (C2, C4).

FEATURE: Router Recipe extension. A regex selector's row is the E4c KEYWORDS result for the
admitted question. KEYWORDS is pure, so DECIDE recomputes it from the admitted question and the
C2 rules instead of trusting a row a caller could author.

INVARIANT: E4c KEYWORDS exactly (`world/branch.py` `_keywords`): RE2, the first 65,536
characters, every rule in declared order, the first match unless ``multi``.
WHY no import of `world.branch`: it imports url4, and the Router steps stay off the url4
allowlist (`router_steps`); a test pins the window to E4c's.
"""

from __future__ import annotations

import functools
from typing import Any

from screamingface_engine.combine.operators.extract import compile_regex, re2_head
from screamingface_engine.world.router_spec import RegexSelector

KEYWORDS_WINDOW = 65_536
"""E4c `branch.KEYWORDS_WINDOW`: the characters of the question RE2 reads."""


def keyword_labels(selector: RegexSelector, question: str) -> tuple[str, ...]:
    """The labels KEYWORDS returns for ``question`` under ``selector``'s rules."""
    head = re2_head(question, KEYWORDS_WINDOW)
    matched = tuple(
        rule.label
        for rule in selector.rules
        if _compiled(rule.pattern, rule.ignore_case).search(head) is not None
    )
    return matched if selector.multi else matched[:1]


# WHY cached: every Case of a run reads the same rules; each pattern compiles once. The C2
# reader already compiled each pattern, so this cannot fail for an admitted definition.
@functools.lru_cache(maxsize=256)
def _compiled(pattern: str, ignore_case: bool) -> Any:
    return compile_regex({"pattern": pattern, "ignore_case": ignore_case})


__all__ = ["KEYWORDS_WINDOW", "keyword_labels"]
