"""The laid-out code of a Gate keeps the sf.Estimate of a nested Gate branch (E4c, BU-3, GT-22).

FEATURE: OME-1291. ``Url4.to_python()`` lays a long ``sf.Gate`` out over lines, and a nested Gate
in a branch opens one level deeper. STORY: as a researcher who edits the rebuilt code, the
``sf.Estimate`` I wrote on a nested Gate branch is still there, so the code compiles to the same
url4 (RB-1).
"""

from __future__ import annotations

from _reducer_fixtures import engine_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.render import code


def _compiled(recipe: object) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4  # type: ignore[arg-type]


def _estimated_nested_gate() -> sf.Gate:
    selector = sf.Keywords([("math", "integral"), ("code", "python")])
    inner = sf.Gate(when=sf.label(selector) == "code", then="prov/code", otherwise="prov/general")
    return sf.Gate(
        when=sf.label(selector) == "math",
        then="prov/math",
        otherwise=sf.Estimate(inner, usd=0.02, tokens=300),
    )


def test_laid_out_code_keeps_the_estimate_of_a_nested_gate() -> None:
    value = _estimated_nested_gate()
    python = code(value, "candidate", width=40)
    assert len(python.splitlines()) > 1
    assert "otherwise=sf.Estimate(sf.Gate(" in python
    namespace: dict[str, object] = {"sf": sf}
    exec(python, namespace)  # noqa: S102 - the SDK's own generated code, offline
    assert namespace["candidate"] == value
    rebuilt = sf.Budgeted(namespace["candidate"], usd=0.05, tokens=1000)  # type: ignore[arg-type]
    assert _compiled(rebuilt) == _compiled(sf.Budgeted(value, usd=0.05, tokens=1000))


def test_to_python_of_a_nested_estimated_gate_recompiles_to_the_same_url4() -> None:
    # An sf.Estimate needs sf.Budgeted at the root, and the root Budgeted stays on one line.
    url4 = _compiled(sf.Budgeted(_estimated_nested_gate(), usd=0.05, tokens=1000))
    python = sf.Url4(url4).to_python()
    namespace: dict[str, object] = {}
    exec(python, namespace)  # noqa: S102 - the SDK's own generated code, offline
    assert _compiled(namespace["candidate"]) == url4
