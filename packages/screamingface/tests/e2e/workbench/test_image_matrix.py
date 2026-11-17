"""The image input matrix's cell logic (plan Task 2): expectation, answer check, verdict.

Review Focus items 1, 2, 4 and 5 of the plan are pinned here without a live target; the
notebook only feeds these functions what the stack returned.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from workbench.image_matrix import (
    Cell,
    Expected,
    Observed,
    answer_contains,
    classify,
    expectation,
    modality_of,
    verdict,
)

GEMINI = "google/gemini-3-flash-preview"
SCOUT = "meta-llama/llama-4-scout"
MISTRAL = "mistralai/mistral-small-24b-instruct-2501"
GPT = "openai/gpt-5-nano"

LISTING: dict[str, Any] = {
    "object": "list",
    "data": [
        {"id": f"openrouter/{GEMINI}", "input_modalities": ["text", "image", "pdf"]},
        {"id": SCOUT, "input_modalities": ["text", "image"]},
        {"id": MISTRAL, "input_modalities": ["text"]},
        # OpenRouter's raw catalogue word for a PDF is `file`.
        {"id": GPT, "input_modalities": ["text", "image", "file"]},
        {"id": "legacy/no-field"},
    ],
}


def _cell(**over: Any) -> Cell:
    base: dict[str, Any] = {
        "path": "url4",
        "model": GEMINI,
        "media_type": "image/png",
        "expected": "answer",
        "observed": "answered",
        "answer": "7392",
        "code": None,
        "trace_id": "a" * 32,
        "spend_usd": Decimal("0.0001"),
        "reason": None,
    }
    return Cell(**(base | over))


@pytest.mark.parametrize(
    ("media_type", "modality"),
    [
        ("image/png", "image"),
        ("image/jpeg", "image"),
        ("image/gif", "image"),
        ("image/webp", "image"),
        ("application/pdf", "pdf"),
    ],
)
def test_modality_of(media_type: str, modality: str) -> None:
    assert modality_of(media_type) == modality


def test_modality_of_rejects_an_unknown_type() -> None:
    with pytest.raises(ValueError, match="text/plain"):
        modality_of("text/plain")


@pytest.mark.parametrize(
    ("model", "media_type", "expected"),
    [
        (GEMINI, "image/png", "answer"),  # matched through the provider prefix
        (GEMINI, "application/pdf", "answer"),
        (f"openrouter/{GEMINI}", "application/pdf", "answer"),  # exact id
        (SCOUT, "image/webp", "answer"),
        (SCOUT, "application/pdf", "refuse"),  # Review Focus 2
        (MISTRAL, "image/png", "refuse"),  # Review Focus 1
        (MISTRAL, "application/pdf", "refuse"),
        (GPT, "application/pdf", "answer"),  # `file` maps to pdf
        ("absent/model", "image/png", "unknown"),
        ("legacy/no-field", "image/png", "unknown"),
    ],
)
def test_expectation(model: str, media_type: str, expected: str) -> None:
    assert expectation(LISTING, model, media_type) == expected


def test_expectation_is_unknown_for_an_ambiguous_suffix() -> None:
    listing = {
        "data": [
            {"id": "a/x/m", "input_modalities": ["text", "image"]},
            {"id": "b/x/m", "input_modalities": ["text"]},
        ]
    }
    assert expectation(listing, "x/m", "image/png") == "unknown"


@pytest.mark.parametrize("listing", [{}, {"data": "nope"}, {"data": [1, "x", None]}])
def test_expectation_is_unknown_for_a_malformed_listing(listing: dict[str, Any]) -> None:
    assert expectation(listing, GEMINI, "image/png") == "unknown"


@pytest.mark.parametrize(
    ("answer", "expected", "ok"),
    [
        ("The number is 7392.", "7392", True),  # Review Focus 4
        ("7392", "7392", True),
        ("  7392\n", "7392", True),
        ("17392", "7392", False),
        ("73920", "7392", False),
        ("7 3 9 2", "7392", False),
        ("The number is 7391.", "7392", False),
        ("heliotrope", "HELIOTROPE", True),
        ("The word is:\n  Heliotrope", "HELIOTROPE", True),
        ("HELIO TROPE", "HELIOTROPE", False),
        ("", "7392", False),
    ],
)
def test_answer_contains(answer: str, expected: str, ok: bool) -> None:
    assert answer_contains(answer, expected) is ok


@pytest.mark.parametrize(
    ("expected", "answer", "code", "observed"),
    [
        ("answer", "It shows 7392", None, "answered"),
        ("answer", "It shows 1234", None, "wrong"),
        ("answer", None, "intent_error", "refused"),
        ("refuse", None, "intent_error", "refused"),
        ("refuse", None, "unsupported_content_part", "refused"),
        ("refuse", None, "x.source_fetch_failed", "error"),
        ("refuse", "7392", None, "answered"),
        ("answer", None, None, "error"),  # neither an answer nor a code
        ("unknown", "7392", None, "skipped"),
    ],
)
def test_classify(
    expected: Expected, answer: str | None, code: str | None, observed: Observed
) -> None:
    assert classify(expected, answer=answer, error_code=code, expected_value="7392") == observed


def test_verdict_passes_a_clean_matrix() -> None:
    cells = [
        _cell(),
        _cell(model=SCOUT, media_type="application/pdf", expected="refuse", observed="refused"),
        _cell(model=MISTRAL, expected="refuse", observed="refused", code="intent_error"),
        _cell(model="absent/model", expected="unknown", observed="skipped", reason="unlisted"),
    ]
    assert verdict(cells) == []


@pytest.mark.parametrize("observed", ["refused", "error"])
def test_expected_answer_that_did_not_answer_fails(observed: str) -> None:
    [reason] = verdict([_cell(observed=observed, answer=None, code="intent_error")])
    assert GEMINI in reason and "image/png" in reason and observed in reason


def test_text_only_model_that_answers_is_a_stale_capability_table() -> None:
    [reason] = verdict([_cell(model=MISTRAL, expected="refuse", observed="answered")])
    assert "capability table stale" in reason and MISTRAL in reason


def test_expected_refusal_with_a_non_refusal_error_fails() -> None:
    cell = _cell(model=MISTRAL, expected="refuse", observed="error", code="x.source_fetch_failed")
    [reason] = verdict([cell])
    assert "x.source_fetch_failed" in reason


def test_expected_refusal_that_reached_the_model_fails_even_when_wrong() -> None:
    [reason] = verdict([_cell(model=MISTRAL, expected="refuse", observed="wrong", answer="no")])
    assert MISTRAL in reason


def test_scout_pdf_refused_and_pictures_answered_passes() -> None:
    """Review Focus 2: a model that takes images but not PDFs."""
    cells = [_cell(model=SCOUT, media_type=m) for m in ("image/png", "image/webp")]
    cells.append(
        _cell(model=SCOUT, media_type="application/pdf", expected="refuse", observed="refused")
    )
    assert verdict(cells) == []


def test_url4_wrong_fails() -> None:
    [reason] = verdict([_cell(observed="wrong", answer="1234")])
    assert "wrong" in reason


def test_one_benchmark_model_missing_a_gold_case_still_passes() -> None:
    """Review Focus 5: scoring noise on one model is reported, not failed."""
    case = {"path": "benchmark", "case": "figqa#3"}
    cells = [
        _cell(**case, model=GEMINI, observed="wrong", answer="B"),
        _cell(**case, model=GPT, observed="answered", answer="A"),
    ]
    assert verdict(cells) == []


def test_every_benchmark_model_missing_a_gold_case_fails() -> None:
    case = {"path": "benchmark", "case": "figqa#3"}
    cells = [
        _cell(**case, model=GEMINI, observed="wrong", answer="B"),
        _cell(**case, model=GPT, observed="wrong", answer="C"),
        _cell(**case, model=MISTRAL, expected="refuse", observed="refused"),
        # Another Case, answered: it does not rescue figqa#3.
        _cell(path="benchmark", case="figqa#4", model=GEMINI),
    ]
    [reason] = verdict(cells)
    assert "figqa#3" in reason


def test_skipped_unknown_cell_is_not_a_failure_nor_a_pass_signal() -> None:
    assert verdict([_cell(expected="unknown", observed="skipped", reason="no row")]) == []


@pytest.mark.parametrize(
    ("answer", "expected", "ok"),
    [
        ("HELIOTROPES", "HELIOTROPE", False),  # a word must stand alone too
        ("unheliotrope", "HELIOTROPE", False),
        ("7392.5", "7392", False),  # a decimal tail is a different number
        ("0.7392", "7392", False),
        ("It is 7392.", "7392", True),  # a sentence full stop is not a decimal
        ("(7392)", "7392", True),
        ('"Heliotrope"', "HELIOTROPE", True),
    ],
)
def test_answer_contains_is_a_whole_token(answer: str, expected: str, ok: bool) -> None:
    assert answer_contains(answer, expected) is ok


def test_an_empty_matrix_fails() -> None:
    """Unknown is never a pass: a run that evaluated nothing must not go green."""
    [reason] = verdict([])
    assert "no cell" in reason


def test_refused_cell_with_gateway_chat_calls_fails() -> None:
    """Review Focus 1: a refusal that still reached the gateway's chat route is not a refusal."""
    cell = _cell(
        model=MISTRAL, expected="refuse", observed="refused", code="intent_error", chat_calls=1
    )
    [reason] = verdict([cell])
    assert MISTRAL in reason and "chat call" in reason


def test_refused_cell_with_zero_chat_calls_passes() -> None:
    cell = _cell(
        model=MISTRAL, expected="refuse", observed="refused", code="intent_error", chat_calls=0
    )
    assert verdict([cell]) == []


# --- provider refusals (OME-1946) -------------------------------------------------------------
#
# A router lists `image`, not each format, so the gateway admits a GIF that the backend then
# rejects (DeepInfra serves Kimi-K3 PNG/JPEG/WebP but answers 415 to a GIF). Such a cell is
# expected to be REFUSED, and — unlike an admission refusal — after exactly one provider call.

KIMI = "huggingface/moonshotai/Kimi-K3:deepinfra"
KIMI_LISTING: dict[str, Any] = {"data": [{"id": KIMI, "input_modalities": ["text", "image"]}]}


def test_a_known_provider_refusal_is_expected_as_a_refusal() -> None:
    from workbench.image_matrix import PROVIDER_REFUSALS

    assert (KIMI, "image/gif") in PROVIDER_REFUSALS
    assert expectation(KIMI_LISTING, KIMI, "image/gif") == "refuse"
    assert expectation(KIMI_LISTING, KIMI, "image/png") == "answer"


def test_a_provider_refusal_may_spend_one_call_and_no_more() -> None:
    def refused(calls: int) -> Cell:
        return _cell(
            model=KIMI,
            media_type="image/gif",
            expected="refuse",
            observed="refused",
            answer=None,
            code="intent_error",
            chat_calls=calls,
        )

    assert verdict([refused(1)]) == []
    assert verdict([refused(2)]) != []
    # An admission refusal elsewhere still allows none.
    assert (
        verdict(
            [
                _cell(
                    expected="refuse",
                    observed="refused",
                    answer=None,
                    code="intent_error",
                    chat_calls=1,
                )
            ]
        )
        != []
    )
