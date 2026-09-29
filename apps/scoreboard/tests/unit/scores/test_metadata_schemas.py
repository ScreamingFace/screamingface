"""Schema half of the E14a metadata edit: paper URL, shared authors rules, the PATCH body.

FEATURE: OME-1307 (E14a) — MD-2 (CHAR), MD-11, MD-12, MD-14 (schema half).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from scoreboard.export_private_submissions import format_jsonl
from scoreboard.scores.schemas import ScoreMetadataPatch, ScoreSchema, ScoreSubmission


def _submission(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "score": 0.75,
        "total_questions": 4,
        "ran_with_providers": ["openai"],
    }
    payload.update(overrides)
    return payload


def _messages(model: type[ScoreSubmission] | type[ScoreMetadataPatch], **fields: Any) -> list[str]:
    payload = _submission(**fields) if model is ScoreSubmission else dict(fields)
    with pytest.raises(ValidationError) as caught:
        model.model_validate(payload)
    return [error["msg"] for error in caught.value.errors()]


def _score_schema(**overrides: Any) -> ScoreSchema:
    values: dict[str, Any] = {
        "id": uuid4(),
        "version": 1,
        "benchmark_id": "hle",
        "benchmark_revision": None,
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "submitted_by": "ana@x.org",
        "submitted_at": datetime(2026, 9, 29, tzinfo=UTC),
        "score": 0.75,
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
    values.update(overrides)
    return ScoreSchema(**values)


def test_md2_char_public_json_strips_author_domains() -> None:
    """CHAR (passes on today's code): the public JSON credits authors by local part only."""
    score = _score_schema(authors=["ana@x.org", "bruno@y.org"])

    assert score.model_dump(mode="json")["authors"] == ["ana", "bruno"]
    # INVARIANT: the PYTHON dump keeps the full address (the staff export needs it).
    assert score.model_dump(mode="python")["authors"] == ["ana@x.org", "bruno@y.org"]


_LONG_OK = "https://x.org/" + "a" * (2048 - len("https://x.org/"))


@pytest.mark.parametrize(
    "value",
    ["https://arxiv.org/abs/2609.01234", "http://x.org/p", _LONG_OK],
    ids=["https", "http", "2048-chars"],
)
def test_md11_paper_url_rules_accept(value: str) -> None:
    assert len(value) <= 2048
    assert ScoreMetadataPatch.model_validate({"paper_url": value}).paper_url == value
    # INVARIANT: no normalization; the stored value is the value that was sent.
    assert ScoreSubmission.model_validate(_submission(paper_url=value)).paper_url == value


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("ftp://x.org", "paper_url must be an absolute http or https URL"),
        ("javascript:alert(1)", "paper_url must be an absolute http or https URL"),
        ("data:text/html,x", "paper_url must be an absolute http or https URL"),
        ("https://user:pass@x.org", "paper_url must not contain credentials"),
        ("https://user@x.org", "paper_url must not contain credentials"),
        ("/relative", "paper_url must be an absolute http or https URL"),
        ("https://", "paper_url must be an absolute http or https URL"),
        (
            "https://x.org/" + "a" * (2049 - len("https://x.org/")),
            "paper_url must be at most 2048 characters",
        ),
        (" https://x.org", "paper_url must not contain whitespace or control characters"),
        ("https://x.org/a b", "paper_url must not contain whitespace or control characters"),
        ("https://x.org/a\x7fb", "paper_url must not contain whitespace or control characters"),
    ],
    ids=[
        "ftp",
        "javascript",
        "data",
        "user-and-password",
        "user-only",
        "relative",
        "no-host",
        "2049-chars",
        "leading-space",
        "inner-space",
        "del-char",
    ],
)
def test_md11_paper_url_rules(value: str, message: str) -> None:
    for model in (ScoreMetadataPatch, ScoreSubmission):
        assert any(message in msg for msg in _messages(model, paper_url=value))


def test_md12_patch_authors_uses_submit_validator() -> None:
    eleven = [f"person{i}@x.org" for i in range(11)]
    too_big = [f"{'a' * 60}{i}@x.org" for i in range(3)] * 20  # repeats: 3 distinct, > 4096 bytes
    cases: dict[str, list[Any]] = {
        "eleven distinct": eleven,
        "4097 bytes": too_big,
        "bad email": ["not-an-email"],
        "empty": [],
    }
    for label, authors in cases.items():
        submit = _messages(ScoreSubmission, authors=authors)
        patch = _messages(ScoreMetadataPatch, authors=authors)
        assert patch == submit, label
    assert (
        "authors must credit at most 10 distinct people"
        in _messages(ScoreMetadataPatch, authors=eleven)[0]
    )
    assert (
        "authors must serialize to at most 4096 bytes"
        in _messages(ScoreMetadataPatch, authors=too_big)[0]
    )


def test_md14_patch_model_forbids_extra() -> None:
    with pytest.raises(ValidationError) as caught:
        ScoreMetadataPatch.model_validate({"score": 1})

    assert caught.value.errors()[0]["type"] == "extra_forbidden"


def test_score_schema_json_always_carries_metadata_revision() -> None:
    """C4/C5: the revision is the `If-Match` a client sends back, so it is never omitted."""
    dumped = _score_schema().model_dump(mode="json")

    assert dumped["metadata_revision"] == 1
    # The other new columns stay excluded at their default (the OME-1181 Q2 trap).
    assert not {"paper_url", "metadata_updated_at", "system_revision_id"} & dumped.keys()


def test_export_drops_metadata_revision_only_while_it_is_the_default() -> None:
    """INVARIANT: an unedited legacy row exports byte-identically; an edited one shows it."""
    unedited = json.loads(format_jsonl([_score_schema()]))
    edited = json.loads(format_jsonl([_score_schema(metadata_revision=2)]))

    assert "metadata_revision" not in unedited
    assert edited["metadata_revision"] == 2
