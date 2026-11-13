"""The shape of one answer rule: the sentence a submitter reads, and the replies that prove it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnswerFormat:
    """One grader's answer rule, in the words a submitter reads, with replies that prove it.

    Attributes:
        sentence: appended to the description of every row it serves; quotes each example
            reply in single quotes.
        case_input: the stand-in Case's question text the examples answer.
        material: the stand-in Case's Grading Material (its key, and options or metadata where
            the grader reads them), in the shape Case Preparation writes. None for a
            judge-graded row: grading one of its replies is a paid judge call, so its sentence
            quotes no graded replies and says that a judge reads the reply.
        accepted: replies the sentence says are graded right; each scores 1 on ``material``.
        rejected: replies the sentence says are read as no answer or as wrong; each scores 0.

    INVARIANT: a judge-graded rule (``material`` None) has no examples, and every other rule
    has at least one accepted and one rejected reply.
    """

    sentence: str
    case_input: str = ""
    material: Mapping[str, Any] | None = None
    accepted: tuple[str, ...] = field(default=())
    rejected: tuple[str, ...] = field(default=())

    @property
    def judged(self) -> bool:
        """True when a judge, not a fixed rule, reads the reply."""

        return self.material is None
