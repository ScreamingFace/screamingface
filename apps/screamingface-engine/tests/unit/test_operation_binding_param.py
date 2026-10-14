"""The ``binding`` model param is attribution only (OME-1289 E4a, unit 8; P2).

FEATURE: a judge or writer call on the same route as a member keeps its own fingerprint.
STORY: as the SDK, I send ``("binding", "judge_1")`` on a judge call, so attribution tells it
apart from a member call on the same model; the gateway never sees the param.
"""

from __future__ import annotations

from screamingface_engine.world.request_parameters import OPERATION_BINDING_PARAM, model_params


def test_binding_param_is_attribution_only() -> None:
    assert OPERATION_BINDING_PARAM == "binding"
    assert model_params({"binding": "judge_1", "temperature": "0"}) == {"temperature": 0}
