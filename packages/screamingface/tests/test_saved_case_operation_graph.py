"""A saved report's Cases keep their Candidate's operation graph when read (OME-1289 x OME-1570).

FEATURE: ``case.answers()`` and ``case.trace()`` read the Candidate's operation graph bound to
each Case. A saved report's Cases decode only when read and are never cached, so the graph
binds at each decode, never by walking every Case when the Candidate is built.
"""

from test_saved_runs import saved_fixture

import screamingface as sf


def test_every_read_of_a_saved_case_carries_the_operation_graph(tmp_path) -> None:
    _, saved = saved_fixture(tmp_path, count=3)
    candidate = sf.reports.get(saved.key, directory=tmp_path).candidates[0]
    expected = {operation.id for operation in candidate.operations}

    first = candidate.cases[0]
    by_id = candidate.cases.by_id(first.case_id)
    walked = list(candidate.cases)

    for case in (first, by_id, *walked):
        assert case._operation_graph is not None
        assert set(case._operation_graph) == expected
