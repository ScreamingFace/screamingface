from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from scoreboard.scores.schemas import BaselineImportRow, BaselineSchema, ScoreSubmission


def _valid_payload() -> dict[str, object]:
    return {
        "benchmark_id": "hle",
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "score": 0.75,
        "total_questions": 4,
        "correct_questions": 3,
        "ran_with_providers": ["openai"],
        "run_cost_usd": "1.25",
    }


def test_score_submission_accepts_valid_payload() -> None:
    submission = ScoreSubmission.model_validate(_valid_payload())

    assert submission.version == 1
    assert submission.benchmark_id == "hle"
    assert submission.ran_with_providers == ["openai"]


def test_score_submission_accepts_scores_outside_the_binary_range() -> None:
    # INVARIANT (OME-866): there is no universal 0..1 range — DRACO is fractional and
    # HealthBench worst-30 is negative. The pre-OME-866 versions of this test rejected
    # both; the range check was deleted WITH the binary contract, not weakened.
    for value in (-1.143, 1.01, 3.75):
        payload = _valid_payload()
        payload["score"] = value
        assert ScoreSubmission.model_validate(payload).score == value


def test_score_submission_rejects_non_positive_total_questions() -> None:
    payload = _valid_payload()
    payload["total_questions"] = 0

    try:
        ScoreSubmission.model_validate(payload)
    except ValidationError as exc:
        assert "total_questions must be positive" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_score_submission_rejects_negative_correct_questions() -> None:
    payload = _valid_payload()
    payload["correct_questions"] = -1

    try:
        ScoreSubmission.model_validate(payload)
    except ValidationError as exc:
        assert "correct_questions must be non-negative" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_score_submission_rejects_correct_questions_above_total() -> None:
    payload = _valid_payload()
    payload["correct_questions"] = 5

    try:
        ScoreSubmission.model_validate(payload)
    except ValidationError as exc:
        assert "correct_questions cannot exceed total_questions" in str(exc)
    else:
        raise AssertionError("expected validation error")


def _valid_baseline_payload() -> dict[str, object]:
    return {
        "benchmark_id": "demo-benchmark",
        "model_name": "GPT-5.2",
        "score": 0.62,
        "source": "artificial_analysis",
    }


def test_baseline_import_row_accepts_valid_payload() -> None:
    row = BaselineImportRow.model_validate(_valid_baseline_payload())

    assert row.benchmark_id == "demo-benchmark"
    assert row.model_name == "GPT-5.2"
    assert row.source_url is None
    assert row.metadata is None


def test_baseline_import_row_accepts_optional_source_url_and_metadata() -> None:
    payload = _valid_baseline_payload()
    payload["source_url"] = "https://artificialanalysis.ai/benchmarks/hle"
    payload["metadata"] = {"published_at": "2026-06-01"}

    row = BaselineImportRow.model_validate(payload)

    assert row.source_url == "https://artificialanalysis.ai/benchmarks/hle"
    assert row.metadata == {"published_at": "2026-06-01"}


def test_baseline_import_row_rejects_empty_benchmark_id() -> None:
    payload = _valid_baseline_payload()
    payload["benchmark_id"] = ""

    try:
        BaselineImportRow.model_validate(payload)
    except ValidationError as exc:
        assert "identifier fields must be non-empty" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_baseline_import_row_rejects_empty_model_name() -> None:
    payload = _valid_baseline_payload()
    payload["model_name"] = ""

    try:
        BaselineImportRow.model_validate(payload)
    except ValidationError as exc:
        assert "identifier fields must be non-empty" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_baseline_import_row_rejects_empty_source() -> None:
    payload = _valid_baseline_payload()
    payload["source"] = ""

    try:
        BaselineImportRow.model_validate(payload)
    except ValidationError as exc:
        assert "identifier fields must be non-empty" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_baseline_import_row_accepts_benchmark_native_scores() -> None:
    # INVARIANT (OME-866): an imported baseline's score is benchmark-native — the same
    # scale as the board it ranks on — so any finite number is importable. The 0..1
    # LMArena assumption was deleted with the binary contract.
    for value in (-1.143, 1.01, 3.75):
        payload = _valid_baseline_payload()
        payload["score"] = value
        assert BaselineImportRow.model_validate(payload).score == value


def test_baseline_import_row_rejects_unknown_fields() -> None:
    payload = _valid_baseline_payload()
    payload["extra_field"] = "not allowed"

    try:
        BaselineImportRow.model_validate(payload)
    except ValidationError as exc:
        assert "extra_field" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_baseline_import_row_rejects_bool_accuracy() -> None:
    payload = _valid_baseline_payload()
    payload["score"] = True

    with pytest.raises(ValidationError):
        BaselineImportRow.model_validate(payload)


def test_baseline_import_row_rejects_numeric_string_accuracy() -> None:
    payload = _valid_baseline_payload()
    payload["score"] = "0.62"

    with pytest.raises(ValidationError):
        BaselineImportRow.model_validate(payload)


def test_baseline_import_row_rejects_non_finite_accuracy() -> None:
    payload = _valid_baseline_payload()
    payload["score"] = float("nan")

    with pytest.raises(ValidationError):
        BaselineImportRow.model_validate(payload)


def test_baseline_import_row_still_accepts_plain_float_accuracy() -> None:
    payload = _valid_baseline_payload()
    payload["score"] = 0.71

    row = BaselineImportRow.model_validate(payload)

    assert row.score == 0.71


def test_baseline_import_row_rejects_deeply_nested_metadata() -> None:
    payload = _valid_baseline_payload()
    nested: dict[str, object] = {"v": 1}
    for _ in range(10):
        nested = {"nest": nested}
    payload["metadata"] = nested

    try:
        BaselineImportRow.model_validate(payload)
    except ValidationError as exc:
        assert "nested" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_baseline_import_row_rejects_oversized_metadata() -> None:
    payload = _valid_baseline_payload()
    payload["metadata"] = {"blob": "x" * 10_000}

    try:
        BaselineImportRow.model_validate(payload)
    except ValidationError as exc:
        assert "bytes" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_baseline_import_row_rejects_javascript_source_url() -> None:
    payload = _valid_baseline_payload()
    payload["source_url"] = "javascript:alert(1)"

    try:
        BaselineImportRow.model_validate(payload)
    except ValidationError as exc:
        assert "http" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_baseline_import_row_rejects_data_uri_source_url() -> None:
    payload = _valid_baseline_payload()
    payload["source_url"] = "data:text/html,<script>alert(1)</script>"

    try:
        BaselineImportRow.model_validate(payload)
    except ValidationError as exc:
        assert "http" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_baseline_import_row_rejects_non_url_source_url() -> None:
    payload = _valid_baseline_payload()
    payload["source_url"] = "not a url"

    with pytest.raises(ValidationError):
        BaselineImportRow.model_validate(payload)


def test_baseline_import_row_accepts_https_source_url() -> None:
    payload = _valid_baseline_payload()
    payload["source_url"] = "https://artificialanalysis.ai/evaluations/humanitys-last-exam"

    row = BaselineImportRow.model_validate(payload)

    assert row.source_url == "https://artificialanalysis.ai/evaluations/humanitys-last-exam"


def test_baseline_import_row_rejects_oversized_source_url() -> None:
    payload = _valid_baseline_payload()
    payload["source_url"] = "https://example.test/" + "x" * 2048

    with pytest.raises(ValidationError):
        BaselineImportRow.model_validate(payload)


def test_baseline_import_row_accepts_metadata_within_bounds() -> None:
    payload = _valid_baseline_payload()
    payload["metadata"] = {"published_at": "2026-06-01", "nested": {"note": "ok"}}

    row = BaselineImportRow.model_validate(payload)

    assert row.metadata == {"published_at": "2026-06-01", "nested": {"note": "ok"}}


def _valid_baseline_schema_payload() -> dict[str, object]:
    return {
        "id": uuid4(),
        "benchmark_id": "demo-benchmark",
        "model_name": "GPT-5.2",
        "score": 0.62,
        "source": "artificial_analysis",
        "source_url": None,
        "imported_at": datetime(2026, 7, 10, tzinfo=UTC),
        "metadata": None,
    }


def test_baseline_schema_accepts_metadata_within_bounds() -> None:
    payload = _valid_baseline_schema_payload()
    payload["metadata"] = {"published_at": "2026-06-01"}

    schema = BaselineSchema.model_validate(payload)

    assert schema.metadata == {"published_at": "2026-06-01"}


def test_baseline_schema_rejects_deeply_nested_metadata() -> None:
    payload = _valid_baseline_schema_payload()
    nested: dict[str, object] = {"v": 1}
    for _ in range(10):
        nested = {"nest": nested}
    payload["metadata"] = nested

    with pytest.raises(ValidationError):
        BaselineSchema.model_validate(payload)


def test_baseline_schema_rejects_oversized_metadata() -> None:
    payload = _valid_baseline_schema_payload()
    payload["metadata"] = {"blob": "x" * 10_000}

    with pytest.raises(ValidationError):
        BaselineSchema.model_validate(payload)


# --- OME-834: publish only the local part of a submitter's email ---


@pytest.mark.parametrize(
    ("stored", "published"),
    [
        # The request: an address must not be harvestable from the public API.
        ("trask@openmined.org", "trask"),
        ("filip.boltuzic@openmined.org", "filip.boltuzic"),
        # In authMode: disabled this field is client-supplied free text, so a value
        # that is not an address passes through rather than being mangled.
        ("tester", "tester"),
        ("", ""),
        # The domain is whatever follows the LAST "@".
        ("a@b@openmined.org", "a@b"),
        # An empty local part would render as a missing submitter, so keep the
        # original instead of emitting "".
        ("@openmined.org", "@openmined.org"),
        # OME-834 review: a BLANK local part is the dangerous case. " " is not empty,
        # so the earlier `local or value` guard let it through — and the SDK's _text
        # rejects blank-after-strip, raising LeaderboardError for the WHOLE board.
        (" @openmined.org", " @openmined.org"),
        ("\t@openmined.org", "\t@openmined.org"),
        # OME-834 review: free text containing "@" is not an address. Truncating it
        # contradicts the pass-through contract and loses meaning. What makes it free
        # text is the UNDOTTED domain, not the spaces — see the third-review cases
        # below, where "me @ openmined.org" is an address and is trimmed.
        ("Team A @ OpenMined", "Team A @ OpenMined"),
        # A domain with no dot is not a public address; leave handles alone.
        ("user@github", "user@github"),
        # OME-834 second review: SURROUNDING whitespace must not defeat the strip.
        # The whitespace guard above exists to catch a blank LOCAL part, but it was
        # rejecting the whole value, so one trailing space published the full domain
        # — the exact exposure this change exists to close. In authMode: disabled
        # submitted_by is unvalidated free text, so a padded address is reachable.
        ("trask@openmined.org ", "trask"),
        (" trask@openmined.org", "trask"),
        ("\ttrask@openmined.org\n", "trask"),
        ("  filip.boltuzic@openmined.org  ", "filip.boltuzic"),
        # ...and padding must not resurrect the blank-local hazard: stripping first
        # leaves an EMPTY local part here, so the original still passes through.
        ("  @openmined.org  ", "  @openmined.org  "),
        # OME-834 third review (owner decision, 2026-08-15): submitted_by is an
        # IDENTITY, not a display name, so anything that IS an address once its
        # whitespace is removed gets trimmed. A harvester normalises "me @ x.org"
        # back to an address, so leaving it whole published a working one.
        ("me @ openmined.org", "me"),
        ("trask @ openmined.org", "trask"),
        ("filip.boltuzic @ openmined . org", "filip.boltuzic"),
        # Free text is still safe when its "domain" is not dotted — "OpenMined" is
        # a word, not a host, so this is NOT an address and passes through whole.
        ("Team A @ OpenMined", "Team A @ OpenMined"),
        ("me @ github", "me @ github"),
    ],
)
def test_score_schema_publishes_only_the_local_part(stored: str, published: str) -> None:
    import json

    from scoreboard.scores.schemas import ScoreSchema

    schema = ScoreSchema(
        id=uuid4(),
        version=1,
        benchmark_id="hle",
        # OME-770 makes this required. The published-identity contract under test
        # here is independent of cost, so None is honest rather than a placeholder.
        run_cost_usd=None,
        # OME-775 made this required; the published-identity contract under test here
        # is independent of which benchmark revision produced the score.
        benchmark_revision=None,
        spec_id="spec-1",
        url4_expression="x",
        submitted_by=stored,
        submitted_at=datetime(2026, 8, 14, 12, tzinfo=UTC),
        score=0.5,
        total_questions=2,
        correct_questions=1,
        ran_with_providers=["openai"],
        ran_at_local=None,
        client_name=None,
        client_version=None,
        client_platform=None,
        verified_by_screamingface=True,
        metadata=None,
    )

    assert json.loads(schema.model_dump_json())["submitted_by"] == published
    # INVARIANT: only the WIRE form is trimmed. The value in memory — and therefore
    # the value written to and read from the database — keeps its domain, so
    # OpenMined can still contact and audit a submitter (OME-404).
    assert schema.submitted_by == stored


def test_a_null_submitter_stays_null() -> None:
    import json

    from scoreboard.scores.schemas import ScoreSchema

    schema = ScoreSchema(
        id=uuid4(),
        version=1,
        benchmark_id="hle",
        # OME-770 makes this required. The published-identity contract under test
        # here is independent of cost, so None is honest rather than a placeholder.
        run_cost_usd=None,
        # OME-775 made this required; the published-identity contract under test here
        # is independent of which benchmark revision produced the score.
        benchmark_revision=None,
        spec_id="spec-1",
        url4_expression="x",
        submitted_by=None,
        submitted_at=datetime(2026, 8, 14, 12, tzinfo=UTC),
        score=0.5,
        total_questions=2,
        correct_questions=1,
        ran_with_providers=["openai"],
        ran_at_local=None,
        client_name=None,
        client_version=None,
        client_platform=None,
        verified_by_screamingface=True,
        metadata=None,
    )

    assert json.loads(schema.model_dump_json())["submitted_by"] is None


# --- OME-820: a client must never declare its own trust tier (spec 3) ---


@pytest.mark.parametrize("claimed", [True, False])
def test_score_submission_rejects_a_client_supplied_verified_flag(claimed: bool) -> None:
    """INVARIANT: verified_by_screamingface is server-side only.

    The board's trust signal must never be assertable by the party it exists to
    constrain, and the write path is public (authenticated, but public). This is
    enforced today by extra="forbid" rather than by an explicit rule, so it is
    pinned here: relaxing that config must break a test, not just widen the DTO.
    """
    payload = _valid_payload()
    payload["verified_by_screamingface"] = claimed

    with pytest.raises(ValidationError):
        ScoreSubmission.model_validate(payload)


# --- OME-770 / OME-822: run cost on a submission ---------------------------
# Every direct submission reports a cost. Zero means "this run genuinely cost
# nothing" (a fully cache-served run); omission and null are client errors.
# Imported and legacy rows retain their distinct unknown-cost state in the
# nullable database and read DTOs, outside ScoreSubmission.


def test_score_submission_accepts_a_run_cost() -> None:
    payload = _valid_payload()
    payload["run_cost_usd"] = "12.50"

    submission = ScoreSubmission.model_validate(payload)

    assert submission.run_cost_usd == Decimal("12.50")


@pytest.mark.parametrize("missing", [True, False])
def test_score_submission_requires_a_non_null_run_cost(missing: bool) -> None:
    payload = _valid_payload()
    if missing:
        payload.pop("run_cost_usd")
    else:
        payload["run_cost_usd"] = None

    with pytest.raises(ValidationError):
        ScoreSubmission.model_validate(payload)


def test_score_submission_accepts_a_genuinely_zero_run_cost() -> None:
    """A fully cache-served run costs 0 — that is data, not a missing value."""
    payload = _valid_payload()
    payload["run_cost_usd"] = "0"

    submission = ScoreSubmission.model_validate(payload)

    assert submission.run_cost_usd == Decimal("0")
    assert submission.run_cost_usd is not None


def test_score_submission_rejects_a_negative_run_cost() -> None:
    payload = _valid_payload()
    payload["run_cost_usd"] = "-0.01"

    with pytest.raises(ValidationError):
        ScoreSubmission.model_validate(payload)


def test_score_submission_keeps_sub_cent_run_cost_precision() -> None:
    """A smoke run can cost fractions of a cent; rounding it to 2dp loses it."""
    payload = _valid_payload()
    payload["run_cost_usd"] = "0.000123"

    submission = ScoreSubmission.model_validate(payload)

    assert submission.run_cost_usd == Decimal("0.000123")


def test_score_submission_keeps_four_figure_run_cost() -> None:
    """The other end of the range — a real DRACO rerun was quoted at $3-4k."""
    payload = _valid_payload()
    payload["run_cost_usd"] = "4210.75"

    submission = ScoreSubmission.model_validate(payload)

    assert submission.run_cost_usd == Decimal("4210.75")


# --- OME-770 review: the contract must match the column's precision ---------
# ge=0 alone let three distinct failures through, all reproduced live before
# these tests were written: 0.0000009 was ACCEPTED and silently stored as
# 0.000001 (a published dollar figure the submitter never sent); 1000000 was
# accepted on SQLite but exceeds DECIMAL(12,6)'s six integer digits and so fails
# on Postgres — passing locally, breaking in production; and 1e30 produced an
# HTTP 500 rather than a 422. The column's shape has to be enforced at the edge.


def test_score_submission_rounds_a_sub_quantum_cost_up() -> None:
    """A positive cost below the smallest storable unit rounds AWAY from zero.

    Rewritten (spec 2.2, second revision): this test previously asserted a 422.
    Rejecting turned out to discard the WHOLE submission -- the accuracy result
    with it -- and would make an almost-free run unpublishable once cost becomes
    mandatory. Rounding up never understates the cost, so it cannot buy a place on
    the frontier, and never yields 0.000000, so D5 still holds.
    """
    payload = _valid_payload()
    payload["run_cost_usd"] = "0.0000009"

    submission = ScoreSubmission.model_validate(payload)

    assert submission.run_cost_usd == Decimal("0.000001")


def test_score_submission_rejects_a_cost_above_the_column_ceiling() -> None:
    """DECIMAL(12,6) leaves six integer digits, so 1000000 does not fit.

    Previously accepted on SQLite and rejected by Postgres — a backend-dependent
    failure that local testing hides.
    """
    payload = _valid_payload()
    payload["run_cost_usd"] = "1000000"

    with pytest.raises(ValidationError):
        ScoreSubmission.model_validate(payload)


def test_score_submission_rejects_an_absurd_exponent() -> None:
    """1e30 previously reached the database and returned HTTP 500."""
    payload = _valid_payload()
    payload["run_cost_usd"] = "1e30"

    with pytest.raises(ValidationError):
        ScoreSubmission.model_validate(payload)


def test_score_submission_still_accepts_the_documented_bounds() -> None:
    """The rejections above must not narrow the range the column supports."""
    for value in ("0.000001", "999999.999999"):
        payload = _valid_payload()
        payload["run_cost_usd"] = value

        assert ScoreSubmission.model_validate(payload).run_cost_usd == Decimal(value)


# --- OME-770 review pass: quantize inexact, reject unstorable (spec 2.2 revision) ---
#
# The earlier rule ("reject anything not storable exactly") over-rejected: it
# conflated a value BELOW representable precision, where rounding materially
# alters a money figure, with float noise on a value that IS representable,
# where rounding loses nothing. Spec 2.2 revision splits the two.


@pytest.mark.parametrize(
    ("submitted", "stored"),
    [
        # WHY: what a client summing per-call float costs actually sends. Rounding
        # to 6dp loses nothing here, so rejecting it would discard a valid score
        # over float noise once the upstream chain lands.
        (0.07 * 3, Decimal("0.210000")),
        ("1.23456789", Decimal("1.234568")),
        # ROUND_HALF_UP, not truncation.
        ("0.0000015", Decimal("0.000002")),
        # The boundary: exactly the smallest representable unit is storable as-is.
        ("0.000001", Decimal("0.000001")),
        # INVARIANT (D5): an explicit zero stays zero, distinct from absent.
        ("0", Decimal("0")),
    ],
)
def test_score_submission_quantizes_an_inexact_cost(
    submitted: float | str,
    stored: Decimal,
) -> None:
    payload = _valid_payload()
    payload["run_cost_usd"] = submitted

    submission = ScoreSubmission.model_validate(payload)

    assert submission.run_cost_usd == stored
    # Numeric equality is not enough — the point is the stored SCALE is pinned to
    # 6dp, which is what makes the wire form backend-independent (spec 2.4).
    assert submission.run_cost_usd is not None
    assert submission.run_cost_usd.as_tuple().exponent == -6


@pytest.mark.parametrize(
    "submitted",
    [
        # Above the column ceiling at any precision. These must be caught BEFORE
        # quantizing, which raises InvalidOperation on an absurd exponent.
        "1000000",
        "1e30",
        # Above the ceiling already, so the pre-quantize check rejects it. There is
        # deliberately NO post-quantize re-check — quantize is monotone and the ceiling
        # sits exactly on the 6dp grid, so nothing can round up past it.
        "999999.9999996",
        # Not a cost.
        "-0.01",
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
def test_score_submission_rejects_an_unstorable_cost(submitted: str) -> None:
    payload = _valid_payload()
    payload["run_cost_usd"] = submitted

    with pytest.raises(ValidationError):
        ScoreSubmission.model_validate(payload)


@pytest.mark.parametrize("submitted", ["0.0000009", "0.0000004", "0.0000001", "1e-9"])
def test_a_sub_quantum_cost_never_becomes_zero(submitted: str) -> None:
    """INVARIANT (D5): a positive cost must never be stored as zero.

    Rewritten alongside the rule change: the guard used to be a 422, and is now
    directional rounding. What it protects is unchanged -- a run that cost real
    money must never be published as free, which would also put it at the cheapest
    end of the Pareto frontier.
    """
    payload = _valid_payload()
    payload["run_cost_usd"] = submitted

    stored = ScoreSubmission.model_validate(payload).run_cost_usd

    assert stored == Decimal("0.000001")
    assert stored != 0


# --- OME-770 review pass 2: negative zero (spec 2.6) ---


@pytest.mark.parametrize("submitted", [-0.0, "-0.0", "-0", "-0.0000000"])
def test_score_submission_normalizes_negative_zero(submitted: float | str) -> None:
    """`-0.0` is a real thing to receive: 0.0 * -1 and round(-1e-9, 6) both make it.

    It passes ge=0 (-0 == 0) and quantize PRESERVES the sign, so it used to survive
    as Decimal('-0.000000') and serve the string "-0.000000" -- a negative dollar
    figure in the Cost column, and backend-dependent besides, since Postgres
    normalizes sign-zero while SQLite keeps it.
    """
    payload = _valid_payload()
    payload["run_cost_usd"] = submitted

    stored = ScoreSubmission.model_validate(payload).run_cost_usd

    assert stored == 0
    assert stored is not None
    # Decimal(0) == Decimal("-0"), so equality cannot catch this -- check the sign.
    assert stored.is_signed() is False
    assert str(stored) == "0.000000"


def test_a_json_number_below_the_float_floor_is_a_documented_residual() -> None:
    """A JSON *number* under ~1e-308 underflows to 0.0 before the validator sees it.

    Pinned rather than fixed: pydantic parses a JSON number through f64, so by the time
    _validate_run_cost runs the value IS zero and is indistinguishable from a genuine
    free run. The clamp therefore cannot fire. Quoting the same value keeps full
    precision and DOES clamp, so the accepted result depends on whether the client
    quotes it — recorded here so the asymmetry is visible rather than surprising.

    No real run cost is within 300 orders of magnitude of this, and closing it would
    mean refusing JSON numbers outright (found in review of OME-770).
    """
    payload = _valid_payload()
    payload["run_cost_usd"] = 1e-400  # a NUMBER, not a string
    assert ScoreSubmission.model_validate(payload).run_cost_usd == Decimal("0.000000")

    payload["run_cost_usd"] = "1e-400"  # the same value, quoted
    assert ScoreSubmission.model_validate(payload).run_cost_usd == Decimal("0.000001")
