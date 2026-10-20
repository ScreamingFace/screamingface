"""The Fusion synthesizer receives one stable structured context value."""

from __future__ import annotations

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate


def test_fusion_compiles_input_and_ordered_outputs_as_structured_context() -> None:
    compiled = compile_candidate(
        sx.Fanout(
            [
                sf.Model("provider/left", name="left) $literal"),
                sf.Model("provider/right", name="right label"),
            ]
        )
        >> sx.Synthesize("provider/writer")
    )

    assert compiled.url4 is not None
    assert "{input: '$input', outputs:" in compiled.url4
    assert "member_1: '$model_1'" in compiled.url4
    assert "member_2: '$model_2'" in compiled.url4
    executable = compiled.url4.split("_sf_recipe", 1)[0]
    assert "left) $literal" not in executable
    assert "right label" not in executable
    assert "Produce the unified prose answer now." not in compiled.url4
