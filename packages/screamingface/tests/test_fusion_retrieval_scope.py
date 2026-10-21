"""Model parameters remain explicit and retrieval remains Engine-owned."""

from __future__ import annotations

import pytest

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate


def test_compiled_fusion_injects_no_model_parameters() -> None:
    compiled = compile_candidate(
        sf.Fanout([sf.Model("provider/left"), sf.Model("provider/right")])
        >> sf.Synthesize("provider/synthesizer")
    )

    assert compiled.url4 is not None
    assert "max_tokens=" not in compiled.url4
    assert "web_search=" not in compiled.url4
    assert "/provider/left($input)" in compiled.url4
    assert "/provider/right($input)" in compiled.url4
    assert "/provider/synthesizer(" in compiled.url4


@pytest.mark.parametrize("reserved", ["web_search", "plugins", "tools", "provider", "q"])
def test_execution_owned_parameters_are_rejected_on_every_candidate_type(reserved: str) -> None:
    with pytest.raises(ValueError, match=rf"{reserved!r} is reserved"):
        sf.Model("provider/model", params={reserved: True})

    with pytest.raises(ValueError, match=rf"{reserved!r} is reserved"):
        _ = sf.Fanout([sf.Model("provider/left"), sf.Model("provider/right")]) >> sf.Synthesize(
            sf.Model(
                "provider/synthesizer",
                params={reserved: True},
            )
        )
