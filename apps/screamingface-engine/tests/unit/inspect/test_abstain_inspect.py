"""An abstained Candidate keeps its mark through an imported Inspect benchmark (E4a, AB-D10).

FEATURE: the single-shot Inspect lane carries ``candidate_abstained`` from the check record to
the hoisted row, so the shared grading code scores an abstained Case 0.0 (OME-1289).
STORY: as a researcher on GSM8K, a vote that found no answer costs one Case, and the report says
the Case abstained while still showing the scorer's own check.

Runs only with the `inspect` extra installed (`uv run --extra inspect pytest ...`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_inspect_gsm8k_benchmark import GSM8K_BENCHMARK, _prepare  # noqa: E402

from screamingface_engine.benchmarks.case_request import candidate_input  # noqa: E402
from screamingface_engine.benchmarks.contract import (  # noqa: E402
    CANDIDATE_ROUTE,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.graded_answer import (  # noqa: E402
    install_graded_answer_endpoint,
)
from url4 import Text, expr, render, src  # noqa: E402
from url4.peer.server import Request, Url4Node  # noqa: E402

_ABST = encode_candidate_invocation("", "stop", None, abstained=True)


@pytest.mark.asyncio
async def test_abstained_case_score_replaced_inspect(tmp_path: Path) -> None:
    node = Url4Node("test")
    GSM8K_BENCHMARK.benchmark.install(node, _prepare(tmp_path))
    install_graded_answer_endpoint(node)

    @node.endpoint(CANDIDATE_ROUTE)
    def candidate(request: Request) -> str:
        _, case_id = candidate_input(request)
        if str(case_id) == "2":
            return _ABST
        return encode_candidate_invocation("ANSWER: 42", "stop", None)

    expression = expr(
        src(Text("unused-candidate-recipe"), name="candidate", weight=0.0),
        src(GSM8K_BENCHMARK.benchmark.protocol(2), name="exam", weight=0.0),
        intent=Text("$exam"),
    )
    result = json.loads((await node.evaluate(render(expression))).text)

    assert result["score"] == 0.5
    answered, abstained = result["cases"]
    assert (answered["status"], answered["grade"]["score"]) == ("scored", 1.0)
    assert "abstained" not in answered
    assert (abstained["status"], abstained["grade"]["score"]) == ("scored", 0.0)
    assert abstained.get("abstained") is True
    assert abstained["grade"]["method"] == "inspect_scorer"
    assert abstained["grade"]["checks"][0]["type"] == "inspect_scorer"
