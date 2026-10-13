"""Public warning categories for completed Evaluations with degraded quality."""


class EvaluationWarning(UserWarning):
    """An Evaluation planning or result condition needs the caller's attention."""


class DuplicateMembersWarning(EvaluationWarning):
    """Two members of a reducer Fusion send the same request, so they may be one cached answer."""


class FixedSeedSittingWarning(EvaluationWarning):
    """A run seed is set, but calls with their own seed send the same request in every sitting."""


__all__ = ["DuplicateMembersWarning", "EvaluationWarning", "FixedSeedSittingWarning"]
