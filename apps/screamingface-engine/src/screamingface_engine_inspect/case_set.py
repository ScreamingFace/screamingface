"""The order-blind seal: a broken Case Digest says whether only the order moved (OME-1492).

FEATURE: OME-1492 — when an Imported Benchmark's Case Digest no longer matches at build, the
log says "same 3498 Cases in another order" or "text changed", so on-call knows whether a
re-seal or a look at the templates is next, without re-running the import on a laptop.

Think of the Case Digest as a photo of a stack of cards: shuffle the stack and the photo no
longer matches, exactly as if a card had been rewritten. The **case-set digest** is a photo of
the same cards laid out in sorted order, so a shuffle leaves it unchanged. Comparing the two
photos tells the shapes apart:

    Case Digest   case-set digest   count      → the reason adds
    differs       matches           same       → "same N Cases in another order"
    differs       differs           same       → "same count, different Cases: text changed"
    (a count change is already named by Case Preparation's own sentence)

Worked example: race_h's 3498 Cases replay with the first two swapped. Every Case's content
is the same, so the sorted photo matches while the ordered one doesn't: "same 3498 Cases in
another order".

INVARIANT: only counts reach the log, never a Case's input or target (the build log is public
and some datasets are gated or licensed). A Case's position fields (``id``, ``case_id``) are
left out of its content: they only say where it is served, so keeping them would make a pure
reorder look like rewritten text.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any, Final

from screamingface_engine_inspect.prepare import PreparedCase, TaskReplayCasesSpec, case_digest

#: The Case fields that only say where a Case is served, not what it is.
_POSITION_FIELDS: Final = frozenset({"id", "case_id"})


def case_set_digest(prepared: Sequence[PreparedCase]) -> str:
    """The Cases' digest with order ignored: sha256 over their sorted content digests.

    WHY reuse ``case_digest`` per Case: it is the one home for "what a Case is" (the JSON
    round trip and canonical form), so this digest can never disagree with the seal about
    which content fields count.

    Returns:
        64 lowercase hex characters.
    """
    contents: list[str] = sorted(case_digest([_content_of(case)]) for case in prepared)
    return hashlib.sha256("\n".join(contents).encode("utf-8")).hexdigest()


def what_moved(spec: TaskReplayCasesSpec, prepared: Sequence[PreparedCase]) -> str:
    """The tail of a Case Digest mismatch's reason; empty when the row has no case-set digest.

    Call it only when the Case count matched and the Case Digest did not.
    """
    if spec.case_set_digest is None:
        return ""
    if case_set_digest(prepared) == spec.case_set_digest:
        return f" — same {len(prepared)} Cases in another order"
    return " — same count, different Cases: text changed"


def _content_of(case: PreparedCase) -> PreparedCase:
    """The Case as content only: everything but its serving position."""
    content: dict[str, Any] = {
        key: value for key, value in case["case"].items() if key not in _POSITION_FIELDS
    }
    return {**case, "case": content}


__all__ = ["case_set_digest", "what_moved"]
