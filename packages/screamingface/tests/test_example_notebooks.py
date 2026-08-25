"""Example notebooks must call the real public API — a user runs these AFTER paying for runs.

INVARIANT under test: any `case.<attr>` access in a generated example resolves on the real
`CaseResult`. The notebook gate only checks deterministic regeneration, never execution, so a
generated cell reading a field that does not exist (`case.id` for `case_id`) raises only on
the user's machine, after the solo + fusion runs were already paid for.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from screamingface.case_result import CaseResult

_EXAMPLES = Path(__file__).parent.parent / "examples"
_CASE_ATTRS = {field.name for field in dataclasses.fields(CaseResult)} | {
    name for name in vars(CaseResult) if not name.startswith("_")
}


@pytest.mark.parametrize("notebook", sorted(_EXAMPLES.glob("*.ipynb")), ids=lambda p: p.name)
def test_case_attribute_accesses_resolve_on_the_real_case_result(notebook: Path) -> None:
    cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
    code = "\n".join("".join(cell["source"]) for cell in cells if cell.get("cell_type") == "code")
    used = set(re.findall(r"\bcase\.(\w+)", code))
    unknown = used - _CASE_ATTRS
    assert not unknown, f"{notebook.name} reads CaseResult attributes that do not exist: {unknown}"
