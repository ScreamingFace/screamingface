"""Public warning categories for completed Evaluations with degraded quality."""


class EvaluationWarning(UserWarning):
    """An Evaluation planning or result condition needs the caller's attention."""


class DuplicateMembersWarning(EvaluationWarning):
    """Two members of a sf.Fanout send the same request, so they may be one cached answer."""


class FixedSeedSittingWarning(EvaluationWarning):
    """A run seed is set, but calls with their own seed send the same request in every sitting."""


class JudgeWriterWarning(EvaluationWarning):
    """A Pipeline stage writes with the model that judged the stage before it (the writer
    scores)."""


__all__ = [
    "DuplicateMembersWarning",
    "EvaluationWarning",
    "FixedSeedSittingWarning",
    "JudgeWriterWarning",
]
