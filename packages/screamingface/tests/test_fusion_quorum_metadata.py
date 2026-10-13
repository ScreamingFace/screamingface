"""Default-valued metadata cannot conceal executable Fusion policy."""

import json
from typing import Literal

import pytest
from url4 import Expression, Source, Text, build, expr, render, src, text

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.url4 import _candidate_from_url4


def _reset_metadata(value: str, mode: str) -> sf.Url4:
    node = build(value)
    assert isinstance(node, Expression)
    source = next(s for s in node.sources if isinstance(s, Source) and s.name == "_sf_recipe")
    assert isinstance(source.value, Text)
    original = source.value.value
    payload = json.loads(original)
    fusion = payload["recipe"]
    if mode == "omit":
        fusion.pop("quorum", None)
        for member in fusion["members"]:
            member.pop("optional", None)
    else:
        fusion["quorum"] = "all"
        for member in fusion["members"]:
            member["optional"] = False
    replacement = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sf.Url4(value.replace(original, replacement))


@pytest.mark.parametrize("mode", ["omit", "defaults"])
@pytest.mark.parametrize("entrypoint", ["python", "replay"])
@pytest.mark.parametrize(("quorum", "optional"), [(1, True), (1, False), ("all", True)])
def test_default_metadata_cannot_hide_executable_fusion_policy(
    mode: str, entrypoint: str, quorum: int | Literal["all"], optional: bool
) -> None:
    # WHY: checking only policy declared in the rider lets removal of its fields
    # silently export a stricter Recipe than the expression actually executes.
    recipe = sf.Fusion(["a", sf.Model("b", optional=optional)], synthesizer="synth", quorum=quorum)
    value = _reset_metadata(compile_candidate(recipe).url4, mode)
    with pytest.raises(ValueError, match="metadata"):
        if entrypoint == "python":
            value.to_python()
        else:
            linked = render(expr(src(text(value), name="candidate", weight=0), intent=text("x")))
            _candidate_from_url4(linked)
