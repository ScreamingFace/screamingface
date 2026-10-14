"""Free guards for the paid lane — everything checkable without a key or a stack."""

from __future__ import annotations

from pathlib import Path

from _panel import MEMBER_MODELS, SYNTHESIZER_MODEL

_SEEDS_FILE: Path = (
    Path(__file__).resolve().parents[4]
    / "apps"
    / "aigateway"
    / "src"
    / "aigateway"
    / "plugins"
    / "openrouter_provider"
    / "settings.py"
)


def test_panel_models_are_gateway_seeds() -> None:
    """INVARIANT: every pinned panel model is an aigateway seed — checked for $0.

    An unseeded model passes discovery-free tests and 404s only at run time (the
    exact bug class the paid lane hunts), so the lane's own roster must be seed-
    backed before anyone presses the paid button. A textual pin on the seed file is
    deliberate: the SDK venv cannot import aigateway (separate uv projects), and the
    seed list is an append-mostly literal, so exact-string presence is stable.
    """
    seeds_source: str = _SEEDS_FILE.read_text(encoding="utf-8")
    missing: list[str] = [
        model for model in (*MEMBER_MODELS, SYNTHESIZER_MODEL) if f'"{model}"' not in seeds_source
    ]
    assert not missing, (
        f"paid-lane panel models missing from the gateway seed list ({_SEEDS_FILE}): "
        f"{missing} — re-pin the panel to seeded models or seed these first "
        f"(a live run would otherwise 404 at dispatch)"
    )


_QWEN: str = "openrouter/qwen/qwen3.7-flash"
#: The panel-wide params every non-qwen call keeps, spelled as literals so a drift in
#: `_panel.PANEL_PARAMS` itself is caught here rather than silently followed.
_SHARED_PARAMS: dict[str, object] = {"max_tokens": 32768, "temperature": 0.0}


def test_only_the_qwen_member_caps_its_reasoning() -> None:
    """INVARIANT: qwen alone carries reasoning_effort="low" and a 65536 cap; others unchanged.

    WHY (run 37442602029, 2026-10-06): qwen spent the whole 32768-token cap on reasoning on
    both lab_bench cloning Cases and wrote no answer, so the Fusion Cases died with
    model_token_cap. Paid run 37453343696 showed "low" alone still capped 1 of 2 Cases, so qwen
    also gets the model's own 65536 completion maximum. Only qwen re-keys its cache.
    """
    from _panel import fusion_panel

    import screamingface as sf

    panel = fusion_panel()
    calls: list[sf.Model] = [
        call for call in (*panel.members, panel.synthesizer) if isinstance(call, sf.Model)
    ]
    assert len(calls) == 3, "the panel must stay two Model members plus a Model synthesizer"
    params_by_model = {call.model: dict(call.params) for call in calls}

    assert params_by_model.pop(_QWEN) == {
        **_SHARED_PARAMS,
        "max_tokens": 65536,
        "reasoning_effort": "low",
    }
    assert params_by_model == {
        "openrouter/anthropic/claude-haiku-4.5": _SHARED_PARAMS,
        "openrouter/google/gemini-3-flash-preview": _SHARED_PARAMS,
    }


def test_compiled_panel_forwards_reasoning_effort_on_the_qwen_call_only() -> None:
    """The SDK's compile step must hand reasoning_effort to the Engine unchanged, on qwen only.

    Pins the path `sf.Model(params=...)` -> parameter assignment -> URL4 call: the value the
    owner chose is what the Engine receives (the Engine json-decodes params, so "low" stays
    the string "low"), and no other operation picks it up.
    """
    from _panel import fusion_panel

    from screamingface._evaluation.candidate import compile_candidate

    compiled = compile_candidate(fusion_panel())
    assignments = {
        assignment.model: dict(assignment.params) for assignment in compiled.parameter_assignments
    }

    assert assignments[_QWEN]["reasoning_effort"] == "low"
    assert [model for model, params in assignments.items() if "reasoning_effort" in params] == [
        _QWEN
    ]
    assert compiled.url4 is not None
    assert compiled.url4.count("reasoning_effort=low") == 1
    assert assignments[_QWEN]["max_tokens"] == 65536
    raised_cap = [model for model, params in assignments.items() if params["max_tokens"] == 65536]
    assert raised_cap == [_QWEN]


# --- The Corrective Loop entry (OME-1527 row 15b) ---


def test_corrective_loop_models_are_gateway_seeds() -> None:
    """INVARIANT: the loop's members AND its judge are aigateway seeds, checked for $0.

    Same bug class as the Fusion panel above: an unseeded judge 404s only when a round
    fails and the coaching call fires, so it could hide for several presses.
    """
    from _panel import CORRECTIVE_JUDGE_MODEL, CORRECTIVE_MEMBER_MODELS

    seeds_source: str = _SEEDS_FILE.read_text(encoding="utf-8")
    roster: tuple[str, ...] = (*CORRECTIVE_MEMBER_MODELS, CORRECTIVE_JUDGE_MODEL)
    missing: list[str] = [model for model in roster if f'"{model}"' not in seeds_source]
    assert not missing, (
        f"paid-lane Corrective Loop models missing from the gateway seed list ({_SEEDS_FILE}): "
        f"{missing} — a live run would 404 at dispatch"
    )


def test_corrective_loop_is_the_golden_members_with_a_non_reasoning_judge() -> None:
    """The built loop is what the chosen Case limit was measured against.

    WHY these exact values: CORRECTIVE_CASE_LIMIT=8 was picked from the recorded ifeval
    golden, where ministral-3b and phi-4 at temperature 0 with that prompt failed round 1
    on Cases 6 and 8. Swap a member, its prompt or its params and that evidence no longer
    applies. The judge carries no reasoning_effort and no prompt of its own, so its coaching
    reply cannot be eaten by thinking (the golden's reasoning judge died that way on Case 10).
    """
    from _panel import corrective_loop

    import screamingface as sf

    loop = corrective_loop()

    assert isinstance(loop, sf.CorrectiveLoop)
    assert loop.max_rounds == 3
    members: list[sf.Model] = [member for member in loop.members if isinstance(member, sf.Model)]
    assert [member.model for member in members] == [
        "openrouter/mistralai/ministral-3b-2512",
        "openrouter/microsoft/phi-4",
    ]
    for member in members:
        assert dict(member.params) == {"max_tokens": 8192, "temperature": 0.0}
        assert member.prompt == (
            "Answer the request accurately and completely. "
            "Follow every instruction and formatting constraint in the request."
        )
    assert isinstance(loop.judge, sf.Model)
    assert loop.judge.model == "openrouter/anthropic/claude-haiku-4.5"
    assert loop.judge.prompt is None
    assert "reasoning_effort" not in dict(loop.judge.params)
