"""The shipped review notebook executes offline against the actual public Client."""

import json
from pathlib import Path

import IPython.display


def test_review_notebook_executes_without_network_or_paid_calls(monkeypatch):
    displayed = []
    monkeypatch.setattr(IPython.display, "display", displayed.append)
    notebook = json.loads(
        (Path(__file__).parents[1] / "examples" / "14_report_accounting.ipynb").read_text()
    )
    namespace = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            exec(compile("".join(cell["source"]), "<accounting-review>", "exec"), namespace)
    assert len(displayed) == 2
    complete, missing = displayed
    assert complete.candidates[0].accounting.by_case[2].cache.hits == 1
    assert missing.candidates[0].accounting.by_member["b"].usage.cost_usd is None
    assert "Cost &amp; usage" in complete._repr_html_()
