"""Decode completed candidate rows using the same validation as the final report."""

from collections.abc import Callable

from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface._evaluation.results import report_from_outcomes


def completion_callback(
    evaluation: _Evaluation, observer: object
) -> Callable[[Candidate, _RunOutcome], None] | None:
    selected = getattr(observer, "candidate_result", None)
    if not callable(selected):
        return None

    def complete(candidate: Candidate, outcome: _RunOutcome) -> None:
        # INVARIANT: live final scores pass the final Report's validation too.
        # The runner isolates UI failures; final decoding remains authoritative.
        report = report_from_outcomes(evaluation, ((candidate, outcome),))
        selected(report.candidates[0])

    return complete
