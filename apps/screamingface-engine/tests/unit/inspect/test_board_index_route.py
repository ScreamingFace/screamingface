# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""An installed Imported Benchmark serves its Cases through the board index (OME-1790).

STORY: as a researcher running 2 Cases of a large board, I want the Engine to read 2 Cases, so
the run fits its memory budget. The route that ``install_imported_benchmark`` registers opens
the board's index, serves the selected rows only, and envelopes only those (gdpval-text keeps
the OME-1527 envelope).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from screamingface_engine_inspect.prepare import PreparedCase, _write_cases  # noqa: E402
from url4 import RelExpr, Text, expr, render, src  # noqa: E402
from url4.peer.server import Url4Node  # noqa: E402

_INPUTS: list[str] = ["Draft the memo.", "Summarise the contract — briefly.", "Plan the audit."]


async def _resolve(node: Url4Node, path: str, count: int) -> list[dict[str, Any]]:
    expression = expr(
        src(RelExpr(path=path, intent=Text(str(count))), name="result", weight=0.0),
        intent=Text("$result"),
    )
    return json.loads((await node.evaluate(render(expression))).text)


@pytest.mark.asyncio
async def test_an_envelope_board_serves_only_the_selected_rows_enveloped(tmp_path: Path) -> None:
    benchmark = imported_benchmark("gdpval-text")
    prepared: list[PreparedCase] = [
        {
            "case": {"id": index, "case_id": str(index), "input": text},
            "grading_material": {"target": ""},
        }
        for index, text in enumerate(_INPUTS, start=1)
    ]
    _write_cases(prepared, tmp_path / benchmark.benchmark.id)
    node = Url4Node("board-index")
    benchmark.benchmark.install(node, tmp_path)

    served = await _resolve(node, benchmark.cases_route, 2)

    assert [row["id"] for row in served] == [1, 2]
    assert [json.loads(row["input"]) for row in served] == [
        {
            "schema": "screamingface.candidate-input.v1",
            "messages": [{"role": "user", "content": text}],
        }
        for text in _INPUTS[:2]
    ]
