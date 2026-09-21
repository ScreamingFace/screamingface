"""ContractEval's deterministic verdict and Jaccard — the paper's definitions, reproduced.

Every assertion here is protocol alignment: these are not our choices to make, and a "cleanup"
that makes any of them prettier moves our published numbers off the paper's.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.contracteval.grading import (
    is_abstention,
    jaccard,
    normalized,
    verdict,
)


class TestNormalized:
    def test_strips_the_reference_wrapper_characters(self) -> None:
        """proprietary_model.py applies `.strip(" \\n`")` to BOTH sides of every comparison."""

        assert normalized("  ```\nThe term is five years.\n``` ") == "The term is five years."

    def test_leaves_interior_text_untouched(self) -> None:
        assert normalized("a  b\nc") == "a  b\nc"


class TestIsAbstention:
    def test_detects_the_literal_refusal(self) -> None:
        assert is_abstention("No related clause.") is True

    def test_is_case_insensitive(self) -> None:
        assert is_abstention("NO RELATED CLAUSE") is True

    def test_matches_a_substring_not_only_a_prefix(self) -> None:
        """PROTOCOL (spec F-3): Evaluation.py ignores `classification` on negative rows and
        recomputes with `'no related clause' in ...`. The `startswith` variant in
        proprietary_model.py never reaches a published number. Substring is the real test."""

        assert is_abstention("After review, no related clause was found.") is True

    def test_an_ordinary_answer_is_not_an_abstention(self) -> None:
        assert is_abstention("The termination clause is section 9.") is False

    def test_an_empty_reply_is_not_an_abstention(self) -> None:
        """An empty reply is a failure to answer, NOT a refusal — it must not earn a TN."""

        assert is_abstention("") is False


class TestVerdict:
    def test_positive_row_needs_every_gold_span_present(self) -> None:
        output = "Clause A says X. Clause B says Y."

        assert verdict(output, ["Clause A says X.", "Clause B says Y."]) is True

    def test_positive_row_fails_when_one_gold_span_is_missing(self) -> None:
        """INVARIANT: all-or-nothing. The reference is `all(substr in output ...)` — there is
        no partial credit anywhere in this protocol (spec F-1)."""

        output = "Clause A says X."

        assert verdict(output, ["Clause A says X.", "Clause B says Y."]) is False

    def test_positive_row_matches_by_substring_not_by_token_overlap(self) -> None:
        """The gold span must appear VERBATIM; sharing words is not enough."""

        assert verdict("X says clause A.", ["Clause A says X."]) is False

    def test_positive_row_accepts_a_gold_span_embedded_in_a_longer_answer(self) -> None:
        """Containment, not equality — a model may quote extra surrounding text and still pass."""

        assert verdict("Preamble. Clause A says X. Trailing.", ["Clause A says X."]) is True

    def test_positive_row_is_wrong_when_the_model_abstains(self) -> None:
        assert verdict("No related clause.", ["Clause A says X."]) is False

    def test_negative_row_is_right_only_when_the_model_abstains(self) -> None:
        assert verdict("No related clause.", []) is True

    def test_negative_row_is_wrong_when_the_model_answers(self) -> None:
        assert verdict("Clause A says X.", []) is False

    def test_wrapper_characters_are_stripped_from_both_sides(self) -> None:
        assert verdict("```\nClause A says X.\n```", ["  Clause A says X.  "]) is True


class TestJaccard:
    def test_identical_text_scores_one(self) -> None:
        assert jaccard(["alpha beta"], "alpha beta") == pytest.approx(1.0)

    def test_disjoint_text_scores_zero(self) -> None:
        assert jaccard(["alpha"], "beta") == pytest.approx(0.0)

    def test_reproduces_the_reference_normalisation(self) -> None:
        """get_jaccard removes . , ; : then lowercases then maps / to space."""

        assert jaccard(["Alpha, Beta; Gamma."], "alpha/beta gamma") == pytest.approx(1.0)

    def test_multiple_gold_spans_are_joined_with_a_space(self) -> None:
        """Evaluation.py passes `' '.join(label)` as the ground truth."""

        assert jaccard(["alpha", "beta"], "alpha beta") == pytest.approx(1.0)

    def test_the_reference_empty_token_inflates_the_union(self) -> None:
        """PROTOCOL (spec F-5): the reference splits on `" "`, so a double space yields an
        empty-string token that joins the set. Here gold={'alpha','beta'} and
        pred={'alpha','beta',''} -> 2/3, NOT 1.0. Mirrored deliberately; do not "fix" it."""

        assert jaccard(["alpha beta"], "alpha  beta") == pytest.approx(2.0 / 3.0)
