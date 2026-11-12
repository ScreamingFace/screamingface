"""``sf.abstain()`` and ``sf.fail()``: the two outcomes a branch can end in without a model call.

FEATURE: E4c (OME-1291, 2026-11-12 proposal review). A Gate branch or the last part of a
``sf.Cascade`` can be an outcome instead of a recipe. ``sf.abstain()`` ends the Case as a scored
decline (``gate_not_met``); ``sf.fail()`` fails the Case with the code ``fail_closed``. They are
the typed spelling of the words ``"abstain"`` and ``"fail_closed"``: the SDK stores the word, so
the compiled recipe and the report codes do not change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screamingface.branch import Word


_SPELLING: dict[str, str] = {"abstain": "abstain", "fail_closed": "fail"}


@dataclass(frozen=True, slots=True)
class Outcome:
    """A branch outcome with no model call: ``sf.abstain()`` or ``sf.fail()``."""

    word: Word

    def __repr__(self) -> str:
        return outcome_text(self.word)


def outcome_text(word: Word, prefix: str = "") -> str:
    """The typed spelling of a word: ``abstain()`` or ``fail()``, with the ``sf.`` ``prefix``."""

    return f"{prefix}{_SPELLING[word]}()"


def abstain() -> Outcome:
    """The Case abstains: a scored decline with the reason ``gate_not_met``. No model runs."""

    return Outcome("abstain")


def fail() -> Outcome:
    """The Case fails with the code ``fail_closed`` (a guard). No model runs after it."""

    return Outcome("fail_closed")


__all__ = ["Outcome", "abstain", "fail", "outcome_text"]
