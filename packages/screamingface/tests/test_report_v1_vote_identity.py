"""report.v1 bytes of a real sf.Vote and sf.Median run (OME-1289 gap, RT#1).

CHAR: passes at once. The derivations (``answers``, ``trace``, ``trace_dict``) run first and never
leak into ``to_json``. The golden is ``data/report_v1_vote_median_report.json``; rewrite it, only
on purpose, from ``packages/screamingface`` with::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_report_v1_vote_identity as m; m.write_golden()"
"""

from __future__ import annotations

from pathlib import Path

import httpx
from _vote_run_fixtures import ScriptedTransport, benchmark_resource, engine_handler, vote_case

import screamingface as sf
from screamingface._evaluation.model import Candidate

GOLDEN = Path(__file__).parent / "data" / "report_v1_vote_median_report.json"
_VOTE_OPS = ("op_model_1", "op_model_2", "op_model_3")
_MEDIAN_OPS = (*_VOTE_OPS, "op_model_4")


def _cases_for(candidate: Candidate) -> list[dict[str, object]]:
    if candidate.name == "vote":
        return [
            vote_case(
                ["The answer is 42", "no idea", "So 42"],
                "vote_one_failed",
                model_ops=_VOTE_OPS,
                output="The answer is 42",
                models=("provider/a", "provider/b", "provider/c"),
            )
        ]
    return [
        vote_case(
            ["I think 10", "20", "maybe 40", "no number here"],
            "median_nearest",
            model_ops=_MEDIAN_OPS,
            output="20",
            models=("provider/a", "provider/b", "provider/c", "provider/d"),
        )
    ]


def vote_median_report() -> sf.Report:
    vote = sf.Fanout(["provider/a", "provider/b", "provider/c"], name="vote") >> sf.Vote(
        over="last_number", normalize="numeric"
    )
    median = sf.Fanout(
        ["provider/a", "provider/b", "provider/c", "provider/d"], name="median"
    ) >> sf.Median(over="last_number")
    transport = ScriptedTransport("draco", "fixture-revision", _cases_for)
    resources = {"draco": benchmark_resource("draco")}
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(engine_handler([], resources=resources)),
        run_transport=transport,
    ) as client:
        return client.evaluate([vote, median], benchmark="draco", progress=False)


def write_golden() -> None:
    GOLDEN.write_text(vote_median_report().to_json() + "\n", encoding="utf-8")


def test_vote_and_median_report_v1_bytes() -> None:
    report = vote_median_report()
    for result in report.candidates:
        for case in result.cases:
            case.answers()
            case.trace()
    report.trace_dict()

    assert report.to_json() + "\n" == GOLDEN.read_text(encoding="utf-8")
