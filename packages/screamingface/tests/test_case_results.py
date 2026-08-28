"""Benchmark-neutral, immutable Case Results retain complete grading evidence."""

from __future__ import annotations

from typing import cast

import pytest

import screamingface as sf


def _graded_case() -> sf.CaseResult:
    raw = '{"explanation":"The response states four.","criterion_status":"MET"}'
    return sf.CaseResult(
        case_id=1,
        input="What is two plus two?",
        output="Four.",
        finish_reason="stop",
        grade=sf.CaseGrade(
            method="rubric",
            score=1.0,
            metrics={"coverage": 1.0, "axis_scores": {"correctness": 1.0}},
            checks=(
                sf.Check(
                    type="criterion",
                    id="correct",
                    label="States that two plus two is four",
                    evidence=(
                        sf.Evidence(
                            sequence=1,
                            producer=sf.EvidenceProducer(
                                type="model", id="openrouter/google/gemini-3.1-pro-preview"
                            ),
                            valid=True,
                            outcome="MET",
                            explanation="The response states four.",
                            raw_output=raw,
                            metadata={},
                        ),
                    ),
                    metadata={"criterion_type": "positive", "weight": 1, "axis": "correctness"},
                ),
            ),
        ),
        failures=(),
        metadata={"domain": "Arithmetic", "tags": ["smoke"]},
    )


def test_case_result_serializes_every_observed_fact_losslessly() -> None:
    case = _graded_case()

    assert case.to_dict() == {
        "status": "scored",
        "case_id": 1,
        "input": "What is two plus two?",
        "output": "Four.",
        "finish_reason": "stop",
        "refusal": None,
        "stop_reason": None,
        "rounds_executed": None,
        "grade": {
            "method": "rubric",
            "score": 1.0,
            "metrics": {"coverage": 1.0, "axis_scores": {"correctness": 1.0}},
            "checks": [
                {
                    "type": "criterion",
                    "id": "correct",
                    "label": "States that two plus two is four",
                    "evidence": [
                        {
                            "sequence": 1,
                            "producer": {
                                "type": "model",
                                "id": "openrouter/google/gemini-3.1-pro-preview",
                            },
                            "valid": True,
                            "outcome": "MET",
                            "explanation": "The response states four.",
                            "raw_output": (
                                '{"explanation":"The response states four.",'
                                '"criterion_status":"MET"}'
                            ),
                            "metadata": {},
                            "accounting": None,
                        }
                    ],
                    "metadata": {
                        "criterion_type": "positive",
                        "weight": 1,
                        "axis": "correctness",
                    },
                }
            ],
        },
        "failures": [],
        "metadata": {"domain": "Arithmetic", "tags": ["smoke"]},
    }


def test_case_result_recursively_freezes_benchmark_metadata() -> None:
    case = _graded_case()

    with pytest.raises(TypeError):
        cast(dict[str, object], case.metadata)["domain"] = "changed"
    assert case.grade is not None
    with pytest.raises(TypeError):
        cast(dict[str, object], case.grade.metrics)["coverage"] = 0.0
    assert case.metadata["tags"] == ("smoke",)


def test_failed_case_retains_the_failure_without_fabricating_an_output_or_grade() -> None:
    failure = sf.Failure(
        stage="candidate",
        code="provider_error",
        message="provider failed the request",
        retryable=None,
        case_id=2,
        metadata={"error_kind": "ResolutionError"},
    )

    case = sf.CaseResult(
        status="failed",
        case_id=2,
        input="A clinical question",
        output=None,
        finish_reason=None,
        refusal=None,
        grade=None,
        failures=(failure,),
        metadata={"domain": "Medicine"},
    )

    assert case.to_dict()["failures"] == [
        {
            "stage": "candidate",
            "code": "provider_error",
            "message": "provider failed the request",
            "retryable": None,
            "case_id": 2,
            "metadata": {"error_kind": "ResolutionError"},
        }
    ]


def test_invalid_evidence_keeps_exact_raw_output_and_rejection_reason() -> None:
    evidence = sf.Evidence(
        sequence=2,
        producer=sf.EvidenceProducer(type="model", id="provider/judge"),
        valid=False,
        raw_output="not json",
        metadata={"rejection_reason": "invalid_json"},
    )

    assert evidence.to_dict() == {
        "sequence": 2,
        "producer": {"type": "model", "id": "provider/judge"},
        "valid": False,
        "raw_output": "not json",
        "metadata": {"rejection_reason": "invalid_json"},
        "accounting": None,
    }


_ENVELOPE = (
    '{"schema":"screamingface.candidate-input.v1","messages":['
    '{"role":"user","content":"How do I treat GI bleeding at home?"},'
    '{"role":"assistant","content":"Do not treat it at home."},'
    '{"role":"user","content":"But what if I must?"}]}'
)


def _case_with_input(value: str) -> sf.CaseResult:
    case = _graded_case()
    return sf.CaseResult(
        case_id=case.case_id,
        input=value,
        output=case.output,
        finish_reason=case.finish_reason,
        grade=case.grade,
        failures=case.failures,
        metadata=case.metadata,
    )


def test_an_envelope_input_decodes_into_conversation_turns() -> None:
    """INVARIANT: the candidate-input envelope is decoded in exactly one place —
    these properties — so every renderer shows a conversation, not wire JSON."""

    case = _case_with_input(_ENVELOPE)
    assert case.conversation == (
        ("user", "How do I treat GI bleeding at home?"),
        ("assistant", "Do not treat it at home."),
        ("user", "But what if I must?"),
    )
    assert case.display_input == (
        "user: How do I treat GI bleeding at home?\n\n"
        "assistant: Do not treat it at home.\n\n"
        "user: But what if I must?"
    )
    # The preview is the Case's actual question — the FIRST user turn.
    assert case.prompt_preview == "How do I treat GI bleeding at home?"
    # The raw wire value stays untouched for auditing and round-trips.
    assert case.input == _ENVELOPE


def test_plain_text_input_passes_through_every_display_property() -> None:
    """INVARIANT: single-turn Benchmarks (draco, ifeval) render byte-identically —
    plain text falls through untouched."""

    case = _case_with_input("Write a poem without the letter e.")
    assert case.conversation is None
    assert case.display_input == "Write a poem without the letter e."
    assert case.prompt_preview == "Write a poem without the letter e."


@pytest.mark.parametrize(
    "value",
    [
        "not json at all {",
        '{"schema":"something.else.v1","messages":[{"role":"user","content":"hi"}]}',
        '{"messages":[{"role":"user","content":"hi"}]}',
        '{"schema":"screamingface.candidate-input.v1","messages":[]}',
        '{"schema":"screamingface.candidate-input.v1","messages":[{"role":"user"}]}',
        '{"schema":"screamingface.candidate-input.v1","messages":[{"role":1,"content":"x"}]}',
        '{"schema":"screamingface.candidate-input.v1","messages":"not a list"}',
    ],
)
def test_non_envelope_inputs_are_treated_as_plain_text(value: str) -> None:
    """INVARIANT: decoding never raises and never misfires — anything that is not
    EXACTLY the versioned envelope renders as the raw string (worst case: you see
    wire text, never a crash or a fabricated transcript)."""

    case = _case_with_input(value)
    assert case.conversation is None
    assert case.display_input == value
    assert case.prompt_preview == value
