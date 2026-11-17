"""Public warning categories for completed Evaluations with degraded quality."""


class EvaluationWarning(UserWarning):
    """An Evaluation planning or result condition needs the caller's attention."""


class CascadeSeedWarning(EvaluationWarning):
    """A sf.Cascade stage repeats the sample seeds of an earlier stage, so it may reuse cached
    answers instead of fresh samples (E4c, CA-23)."""


class DuplicateMembersWarning(EvaluationWarning):
    """Two members of a sf.Fanout send the same request, so they may be one cached answer."""


class FixedSeedSittingWarning(EvaluationWarning):
    """A run seed is set, but calls with their own seed send the same request in every sitting."""


class JudgeWriterWarning(EvaluationWarning):
    """A Pipeline stage writes with the model that judged the stage before it (the writer
    scores)."""


__all__ = [
    "CascadeSeedWarning",
    "DuplicateMembersWarning",
    "EvaluationWarning",
    "FixedSeedSittingWarning",
    "JudgeWriterWarning",
]
