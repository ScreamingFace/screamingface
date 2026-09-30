"""IFEval per-case grading — the vendored verifier behind a crash-safe boundary.

FEATURE: judge-free IFEval grading — every constraint checked by deterministic code.
STORY: as a researcher, my instruction-following score is exact and costs zero judge calls.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.ifeval.grading import (
    check_case,
    describe_failures,
    describe_instructions,
)


def test_no_comma_passes_a_comma_free_response() -> None:
    result = check_case(
        instruction_id_list=["punctuation:no_comma"],
        kwargs_list=[{}],
        prompt="Write about tea. Do not use commas.",
        response="Tea is a drink made from leaves and hot water.",
    )

    assert result["strict"] == [True]
    assert result["loose"] == [True]


def test_no_comma_fails_a_response_containing_a_comma() -> None:
    result = check_case(
        instruction_id_list=["punctuation:no_comma"],
        kwargs_list=[{}],
        prompt="Write about tea. Do not use commas.",
        response="Tea is warm, comforting and popular.",
    )

    assert result["strict"] == [False]
    assert result["loose"] == [False]


def test_word_count_boundary_is_inclusive_for_at_least() -> None:
    # INVARIANT: "at least N" passes at exactly N — the verifier's relation semantics are
    # the benchmark; an off-by-one here silently shifts every length-constrained score.
    kwargs = [{"relation": "at least", "num_words": 5}]

    exactly_five = check_case(
        instruction_id_list=["length_constraints:number_words"],
        kwargs_list=kwargs,
        prompt="Say something in five or more words.",
        response="one two three four five",
    )
    only_four = check_case(
        instruction_id_list=["length_constraints:number_words"],
        kwargs_list=kwargs,
        prompt="Say something in five or more words.",
        response="one two three four",
    )

    assert exactly_five["strict"] == [True]
    assert only_four["strict"] == [False]


def test_highlighted_sections_counts_asterisk_spans() -> None:
    result = check_case(
        instruction_id_list=["detectable_format:number_highlighted_sections"],
        kwargs_list=[{"num_highlights": 2}],
        prompt="Highlight at least two sections.",
        response="*first point* and also *second point* in the text",
    )

    assert result["strict"] == [True]


def test_loose_mode_recovers_a_quotation_wrapped_in_markdown() -> None:
    # WHY: the paper's loose protocol strips markdown emphasis and edge lines before
    # re-checking — a response that is compliant under any of the 8 variants counts loose.
    result = check_case(
        instruction_id_list=["startend:quotation"],
        kwargs_list=[{}],
        prompt="Wrap your whole answer in double quotes.",
        response='*"the whole answer"*',
    )

    assert result["strict"] == [False]
    assert result["loose"] == [True]


def test_repeat_prompt_requires_the_prompt_as_prefix() -> None:
    kwargs = [{"prompt_to_repeat": "Say hello to the team"}]

    repeated = check_case(
        instruction_id_list=["combination:repeat_prompt"],
        kwargs_list=kwargs,
        prompt="Say hello to the team",
        response="Say hello to the team\nHello team!",
    )
    unrepeated = check_case(
        instruction_id_list=["combination:repeat_prompt"],
        kwargs_list=kwargs,
        prompt="Say hello to the team",
        response="Hello team!",
    )

    assert repeated["strict"] == [True]
    assert unrepeated["strict"] == [False]


def test_multiple_instructions_report_positionally() -> None:
    result = check_case(
        instruction_id_list=[
            "punctuation:no_comma",
            "length_constraints:number_words",
        ],
        kwargs_list=[{}, {"relation": "at least", "num_words": 100}],
        prompt="No commas; at least 100 words.",
        response="Short and comma free answer.",
    )

    assert result["strict"] == [True, False]
    assert result["loose"] == [True, False]


def test_mismatched_instruction_and_kwargs_lengths_raise() -> None:
    # WHY loud: positional parallelism is the dataset contract — a length skew means the
    # prepared assets are corrupt, not that the Candidate failed.
    with pytest.raises(ValueError):
        check_case(
            instruction_id_list=["punctuation:no_comma"],
            kwargs_list=[],
            prompt="anything",
            response="anything",
        )


# ── Non-alphabetic letter_frequency kwargs (official dataset cases 1122 '#', 1129 '!') ──
# WHY these tests exist: the official verifier REPLACES any letter outside a-z with a
# random.choice(ascii_letters) (vendor/instructions.py LetterFrequencyChecker), so the
# official dataset's own '#'/'!' kwargs were graded against a different random letter on
# every call — label said "letter q", feedback said "letter m", loose failed while strict
# passed. Owner decision 2026-08-10: honor the pinned dataset kwarg in grading.py.
# Ledger: docs/work/2026-08-10-OME-TBD-ifeval-letter-frequency-kwarg-fidelity.md

_HASH_KWARGS = [{"let_relation": "at least", "letter": "#", "let_frequency": 4}]


def test_nonalpha_letter_kwarg_is_graded_literally_not_randomized() -> None:
    # INVARIANT: the dataset's pinned letter IS the benchmark — a response with four '#' and no
    # occurrences of any ascii letter can only pass if '#' itself is being counted.
    result = check_case(
        instruction_id_list=["keywords:letter_frequency"],
        kwargs_list=_HASH_KWARGS,
        prompt="Include at least 4 hashtags, starting with '#'",
        response="# # # #",
    )

    assert result["strict"] == [True]
    assert result["loose"] == [True]


def test_nonalpha_letter_kwarg_fails_below_the_pinned_frequency() -> None:
    result = check_case(
        instruction_id_list=["keywords:letter_frequency"],
        kwargs_list=_HASH_KWARGS,
        prompt="Include at least 4 hashtags, starting with '#'",
        response="# # #",
    )

    assert result["strict"] == [False]
    assert result["loose"] == [False]


def test_nonalpha_letter_label_names_the_pinned_character() -> None:
    # STORY: as a researcher reading a report, the check label must state the requirement
    # the prompt asked for ("letter #"), never a verifier-invented random letter.
    for _ in range(3):  # repeated calls guard the determinism, not just the character
        labels = describe_instructions(
            instruction_id_list=["keywords:letter_frequency"],
            kwargs_list=_HASH_KWARGS,
            prompt="Include at least 4 hashtags, starting with '#'",
        )
        assert labels == ["In your response, the letter # should appear at least 4 times."]


def test_nonalpha_letter_feedback_names_the_pinned_character() -> None:
    # WHY: corrective-round feedback drives paid retries — feedback naming a random letter
    # coaches members to satisfy a requirement that does not exist (seen live: "letter m").
    feedback = describe_failures(
        instruction_id_list=["keywords:letter_frequency"],
        kwargs_list=_HASH_KWARGS,
        prompt="Include at least 4 hashtags, starting with '#'",
        strict=[False],
    )

    assert feedback == ["In your response, the letter # should appear at least 4 times."]


def test_nonalpha_letter_strict_pass_implies_loose_pass() -> None:
    # INVARIANT: loose is strict plus forgiveness — strict PASS with loose FAIL is
    # impossible under one consistent instruction (the live-run contradiction on case 1122).
    result = check_case(
        instruction_id_list=["keywords:letter_frequency"],
        kwargs_list=_HASH_KWARGS,
        prompt="Include at least 4 hashtags, starting with '#'",
        response="#one #two #three #four",
    )

    assert result["strict"] == [True]
    assert result["loose"] == [True]


def test_alphabetic_letter_kwargs_keep_official_grading() -> None:
    # WHY a guard: the override must never touch a-z letters — those grade byte-identically
    # to the official verifier for leaderboard comparability.
    kwargs = [{"let_relation": "at least", "letter": "q", "let_frequency": 2}]

    enough = check_case(
        instruction_id_list=["keywords:letter_frequency"],
        kwargs_list=kwargs,
        prompt="Use the letter q at least twice.",
        response="quick quiz",
    )
    too_few = check_case(
        instruction_id_list=["keywords:letter_frequency"],
        kwargs_list=kwargs,
        prompt="Use the letter q at least twice.",
        response="quick fox",
    )

    assert enough["strict"] == [True]
    assert too_few["strict"] == [False]


def test_an_empty_response_fails_every_instruction() -> None:
    result = check_case(
        instruction_id_list=["punctuation:no_comma"],
        kwargs_list=[{}],
        prompt="anything",
        response="",
    )

    assert result["strict"] == [False]
    assert result["loose"] == [False]
