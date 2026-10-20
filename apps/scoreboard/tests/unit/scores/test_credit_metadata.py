"""The shared validator for `authors_metadata` and `paper_metadata` (spec section 3).

FEATURE: open author and paper metadata with known keys, bounds and matching. One validator for
submit and edit, so a PATCH can never accept what a POST refuses.

Every check below compares parsed values (problem locations, error lists, model fields); none
searches inside a message.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from pydantic import ValidationError

from scoreboard.scores.credit_metadata import (
    MetadataProblem,
    authors_metadata_problems,
    keep_matching_authors,
    paper_metadata_problems,
    split_paper_metadata,
    unmatched_author_keys,
)
from scoreboard.scores.schemas import ScoreMetadataPatch, ScoreSchema, ScoreSubmission

ANA = "ana@uni.edu"
BO = "bo@lab.org"
PAPER = "https://arxiv.org/abs/2610.01234"


def _locs(problems: list[MetadataProblem]) -> list[tuple[str, ...]]:
    return [problem.loc for problem in problems]


# --- paper_metadata --------------------------------------------------------------------------


def test_a_paper_object_with_every_known_key_and_open_keys_passes() -> None:
    value = {
        "title": "t" * 300,
        "citation": "c" * 2000,
        "url": PAPER,
        "venue": "v" * 500,
        "pages": 12,
        "score_scale": 0.5,
        "peer_reviewed": True,
    }

    assert paper_metadata_problems(value) == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("title", "t" * 301),
        ("citation", "c" * 2001),
        ("venue", "v" * 501),
        ("title", 3),
        ("citation", True),
        ("url", "ftp://example.org/paper"),
        ("url", "https://user@example.org/"),
        ("url", ""),
        ("url", "https://example.org/" + "a" * 2048),
        ("url", 5),
        ("venue", None),
        ("venue", ["a"]),
        ("venue", {"a": 1}),
        ("venue", math.nan),
        ("venue", math.inf),
        ("venue", -math.inf),
    ],
)
def test_each_bad_value_is_one_problem_naming_its_key(key: str, value: Any) -> None:
    assert _locs(paper_metadata_problems({key: value})) == [("paper_metadata", key)]


@pytest.mark.parametrize("key", ["", "k" * 65])
def test_a_key_outside_one_to_sixty_four_characters_is_a_problem(key: str) -> None:
    assert _locs(paper_metadata_problems({key: "x"})) == [("paper_metadata", key)]


def test_sixty_four_character_keys_and_twenty_keys_pass() -> None:
    value = {f"{index:02d}" + "k" * 62: index for index in range(20)}

    assert paper_metadata_problems(value) == []


def test_twenty_one_keys_is_one_problem_on_the_object() -> None:
    value = {f"key{index}": index for index in range(21)}

    assert _locs(paper_metadata_problems(value)) == [("paper_metadata",)]


def test_every_problem_is_reported_not_only_the_first() -> None:
    problems = paper_metadata_problems({"title": 1, "citation": 2, "ok": "fine", "venue": None})

    assert _locs(problems) == [
        ("paper_metadata", "title"),
        ("paper_metadata", "citation"),
        ("paper_metadata", "venue"),
    ]


def test_split_moves_url_out_and_keeps_the_rest() -> None:
    assert split_paper_metadata({"title": "T", "url": PAPER}) == ({"title": "T"}, PAPER)
    assert split_paper_metadata({"url": PAPER}) == ({}, PAPER)
    assert split_paper_metadata({"title": "T"}) == ({"title": "T"}, None)


# --- authors_metadata ------------------------------------------------------------------------


def test_an_authors_object_with_known_and_open_keys_passes() -> None:
    value = {
        ANA: {"full_name": "n" * 200, "institution": "i" * 200, "orcid": "0000", "senior": True},
        BO: {},
    }

    assert authors_metadata_problems(value) == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("full_name", "n" * 201),
        ("institution", "i" * 201),
        ("full_name", None),
        ("institution", 7),
        ("homepage", ["x"]),
    ],
)
def test_a_bad_author_value_names_the_author_and_the_key(key: str, value: Any) -> None:
    assert _locs(authors_metadata_problems({ANA: {key: value}})) == [("authors_metadata", ANA, key)]


def test_an_author_entry_that_is_not_an_object_is_a_problem() -> None:
    assert _locs(authors_metadata_problems({ANA: "Ana Silva"})) == [("authors_metadata", ANA)]


def test_an_author_entry_with_twenty_one_keys_is_a_problem() -> None:
    entry = {f"key{index}": index for index in range(21)}

    assert _locs(authors_metadata_problems({ANA: entry})) == [("authors_metadata", ANA)]


def test_two_keys_for_the_same_author_after_casefolding_name_both() -> None:
    problems = authors_metadata_problems({ANA: {}, "Ana@Uni.EDU": {}})

    assert _locs(problems) == [("authors_metadata", "Ana@Uni.EDU")]
    assert problems[0].keys == (ANA, "Ana@Uni.EDU")


def test_matching_uses_the_authors_normalization() -> None:
    assert unmatched_author_keys({"ANA@uni.edu": {}}, [ANA, BO]) == []


def test_each_key_not_in_the_credit_line_is_one_problem() -> None:
    problems = unmatched_author_keys({ANA: {}, "carol@x.org": {}, "dan@y.org": {}}, [ANA])

    assert _locs(problems) == [
        ("authors_metadata", "carol@x.org"),
        ("authors_metadata", "dan@y.org"),
    ]


def test_with_no_credit_line_every_key_is_unmatched() -> None:
    assert _locs(unmatched_author_keys({ANA: {}}, None)) == [("authors_metadata", ANA)]


def test_keep_matching_drops_removed_authors_and_keeps_the_stored_spelling() -> None:
    stored = {"Ana@Uni.edu": {"full_name": "Ana"}, BO: {"full_name": "Bo"}}

    assert keep_matching_authors(stored, [ANA]) == {"Ana@Uni.edu": {"full_name": "Ana"}}
    assert keep_matching_authors(stored, ["carol@x.org"]) == {}


# --- the request schemas -----------------------------------------------------------------------


def _submission(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "spec_id": "spec-1",
        "url4_expression": "url4://x",
        "score": 0.5,
        "total_questions": 4,
        "ran_with_providers": ["openai"],
    }
    payload.update(overrides)
    return payload


def _error_locs(raised: pytest.ExceptionInfo[ValidationError]) -> list[tuple[str | int, ...]]:
    return [tuple(error["loc"]) for error in raised.value.errors()]


def test_a_submission_reports_one_error_per_problem_with_its_location() -> None:
    with pytest.raises(ValidationError) as raised:
        ScoreSubmission.model_validate(
            _submission(
                authors=[ANA],
                paper_metadata={"title": 1, "venue": None},
                authors_metadata={ANA: {"full_name": 2}},
            )
        )

    assert sorted(_error_locs(raised)) == sorted(
        [
            ("paper_metadata", "title"),
            ("paper_metadata", "venue"),
            ("authors_metadata", ANA, "full_name"),
        ]
    )


def test_a_submission_with_valid_metadata_keeps_it_as_sent() -> None:
    paper = {"title": "T", "url": PAPER}
    authors = {ANA: {"full_name": "Ana Silva"}}

    submission = ScoreSubmission.model_validate(
        _submission(authors=[ANA], paper_metadata=paper, authors_metadata=authors)
    )

    assert submission.paper_metadata == paper
    assert submission.authors_metadata == authors


def test_a_submission_whose_two_urls_disagree_is_refused() -> None:
    with pytest.raises(ValidationError) as raised:
        ScoreSubmission.model_validate(_submission(paper_url=PAPER, paper_metadata={"title": "T"}))

    assert _error_locs(raised) == [("paper_metadata", "url")]


def test_a_submission_whose_two_urls_agree_is_accepted() -> None:
    submission = ScoreSubmission.model_validate(
        _submission(paper_url=PAPER, paper_metadata={"url": PAPER})
    )

    assert submission.paper_url == PAPER


def test_a_patch_runs_the_same_validator() -> None:
    with pytest.raises(ValidationError) as raised:
        ScoreMetadataPatch.model_validate({"paper_metadata": {"title": "t" * 301}})

    assert _error_locs(raised) == [("paper_metadata", "title")]


def test_a_patch_may_clear_either_object_with_null() -> None:
    patch = ScoreMetadataPatch.model_validate({"authors_metadata": None, "paper_metadata": None})

    assert patch.model_fields_set == {"authors_metadata", "paper_metadata"}


def test_a_patch_whose_null_object_disagrees_with_a_sent_url_is_refused() -> None:
    with pytest.raises(ValidationError) as raised:
        ScoreMetadataPatch.model_validate({"paper_metadata": None, "paper_url": PAPER})

    assert _error_locs(raised) == [("paper_metadata", "url")]


def test_a_patch_with_two_keys_for_one_author_is_refused() -> None:
    with pytest.raises(ValidationError) as raised:
        ScoreMetadataPatch.model_validate({"authors_metadata": {ANA: {}, "ANA@uni.edu": {}}})

    assert _error_locs(raised) == [("authors_metadata", "ANA@uni.edu")]


# --- the read schema -------------------------------------------------------------------------


def _read(**overrides: Any) -> ScoreSchema:
    fields: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "version": 1,
        "benchmark_id": "hle",
        "benchmark_revision": None,
        "spec_id": "spec-1",
        "url4_expression": "url4://x",
        "submitted_by": ANA,
        "submitted_at": "2026-10-15T00:00:00Z",
        "score": 0.5,
        "total_questions": 4,
        "correct_questions": None,
        "ran_with_providers": ["openai"],
        "ran_at_local": None,
        "client_name": None,
        "client_version": None,
        "client_platform": None,
        "verified_by_screamingface": True,
        "metadata": None,
        "run_cost_usd": None,
    }
    fields.update(overrides)
    return ScoreSchema.model_validate(fields)


def test_the_read_puts_the_url_back_into_the_paper_object() -> None:
    row = _read(paper_url=PAPER, paper_metadata={"title": "T"})

    assert row.paper_metadata == {"title": "T", "url": PAPER}


def test_a_url_without_a_stored_object_reads_without_paper_metadata() -> None:
    # INVARIANT: a row that only ever had `paper_url` exports exactly as before.
    row = _read(paper_url=PAPER)

    assert "paper_metadata" not in row.model_dump(mode="python")


def test_public_json_keys_authors_metadata_by_the_published_author() -> None:
    row = _read(
        authors=[ANA, BO],
        authors_metadata={ANA: {"full_name": "Ana Silva", "institution": "MIT"}},
    )

    public = row.model_dump(mode="json")
    staff = row.model_dump(mode="python")

    assert public["authors"] == ["ana", "bo"]
    assert public["authors_metadata"] == {"ana": {"full_name": "Ana Silva", "institution": "MIT"}}
    assert staff["authors_metadata"] == {ANA: {"full_name": "Ana Silva", "institution": "MIT"}}


def test_two_authors_sharing_a_local_part_publish_full_keys() -> None:
    other_ana = "ana@lab.org"
    row = _read(
        authors=[ANA, other_ana],
        authors_metadata={"Ana@Uni.edu": {"full_name": "Ana S"}, other_ana: {"full_name": "Ana L"}},
    )

    public = row.model_dump(mode="json")

    assert public["authors"] == [ANA, other_ana]
    assert public["authors_metadata"] == {
        ANA: {"full_name": "Ana S"},
        other_ana: {"full_name": "Ana L"},
    }


def test_a_derived_credit_line_masks_the_submitter_key() -> None:
    # authors NULL on the row reads as [submitted_by]; the key masks the same way.
    row = _read(authors=None, authors_metadata={ANA: {"full_name": "Ana"}})

    assert row.model_dump(mode="json")["authors_metadata"] == {"ana": {"full_name": "Ana"}}


def test_a_key_matching_no_credited_author_still_never_publishes_its_domain() -> None:
    # Only a raw write can leave such a key (the store refuses and prunes them); it fails closed.
    row = _read(authors=[BO], authors_metadata={ANA: {"full_name": "Ana"}})

    assert row.model_dump(mode="json")["authors_metadata"] == {"ana": {"full_name": "Ana"}}
