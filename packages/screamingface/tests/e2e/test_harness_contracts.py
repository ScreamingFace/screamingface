"""Contract tests for the replay-harness data models (OME-961).

These run in the DEFAULT test lane — no docker, no subprocesses. They pin the two
contracts the whole e2e harness stands on:

- ``harness.tape``: a recorded exchange validates on READ, keeps the provider
  response as RAW bytes, and carries provenance (board, revision, expression_sha,
  authored flag) so a fixture can never be mistaken for a real recording.
- ``harness.goldens``: golden comparison checks the expression SHA FIRST — a
  changed expression must fail as "goldens stale", never as a score mismatch —
  and compares the final score as a decimal string, never float-to-float.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from harness.goldens import (
    GOLDEN_SCHEMA,
    ActualOutcome,
    GoldenMismatch,
    GoldenReport,
    canonical_score,
    compare_outcome,
    load_golden,
)
from harness.tape import TAPE_SCHEMA, NormalizedRequest, load_tape

_SHA = hashlib.sha256(b"rendered expression").hexdigest()


def _tape_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": TAPE_SCHEMA,
        "provenance": {
            "board": "synthetic",
            "revision": "synthetic-2026-08",
            "expression_sha": _SHA,
            "engine_sha": "0" * 40,
            "recorded_at": "2026-08-24T00:00:00Z",
            "run_ref": "authored-by-hand",
            "authored": True,
        },
        "exchanges": [
            {
                "normalized": {
                    "provider": "openrouter",
                    "model": "openrouter/openai/gpt-5.5",
                    "fingerprint": "a" * 64,
                },
                "request": {
                    "method": "POST",
                    "path": "/v1/chat/completions",
                    "body": {"model": "openrouter/openai/gpt-5.5", "messages": []},
                },
                "response": {
                    "status": 200,
                    "media_type": "application/json",
                    "body_b64": base64.b64encode(b'{"choices": []}').decode(),
                },
            }
        ],
    }
    document.update(overrides)
    return document


def _golden_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": GOLDEN_SCHEMA,
        "board": "synthetic",
        "revision": "synthetic-2026-08",
        "expression_sha": _SHA,
        "final_score": "0.5",
        "case_count": 2,
        "gradeable_count": 1,
        "case_statuses": {"case_1": "scored", "case_2": "refused"},
    }
    document.update(overrides)
    return document


# ---- Tape validation on read ----
def test_a_valid_tape_round_trips_with_raw_response_bytes(tmp_path) -> None:
    # WHY raw bytes: the gateway serves cached provider payloads byte-identical
    # (OME-951 invariant 4), so the tape must not re-serialize them either.
    path = tmp_path / "tape.json"
    path.write_text(json.dumps(_tape_document()))

    tape = load_tape(path)

    assert tape.provenance.board == "synthetic"
    assert tape.provenance.authored is True
    (exchange,) = tape.exchanges()
    assert exchange.response.body == b'{"choices": []}'


def test_lookup_finds_an_exchange_by_its_normalized_identity(tmp_path) -> None:
    path = tmp_path / "tape.json"
    path.write_text(json.dumps(_tape_document()))
    tape = load_tape(path)

    hit = tape.lookup(
        NormalizedRequest(
            provider="openrouter",
            model="openrouter/openai/gpt-5.5",
            fingerprint="a" * 64,
        )
    )
    miss = tape.lookup(
        NormalizedRequest(
            provider="openrouter",
            model="openrouter/openai/gpt-5.5",
            fingerprint="b" * 64,
        )
    )

    assert hit is not None and hit.response.status == 200
    assert miss is None


def test_an_unknown_schema_is_refused_on_read(tmp_path) -> None:
    # WHY: validation on READ is the tape contract — a stale or foreign file
    # must fail loudly at load, not surface later as a silent replay miss.
    path = tmp_path / "tape.json"
    path.write_text(json.dumps(_tape_document(schema="something.else.v9")))

    with pytest.raises(ValueError, match="schema"):
        load_tape(path)


def test_a_malformed_fingerprint_is_refused_on_read(tmp_path) -> None:
    document = _tape_document()
    exchanges = document["exchanges"]
    assert isinstance(exchanges, list)
    exchanges[0]["normalized"]["fingerprint"] = "not-hex"
    path = tmp_path / "tape.json"
    path.write_text(json.dumps(document))

    with pytest.raises(ValueError):
        load_tape(path)


def test_duplicate_exchange_identities_are_refused_on_read(tmp_path) -> None:
    # WHY: a dict index would silently keep the LAST duplicate, so row order —
    # not content — would decide what replays. Ambiguity must fail at load.
    document = _tape_document()
    exchanges = document["exchanges"]
    assert isinstance(exchanges, list)
    exchanges.append(json.loads(json.dumps(exchanges[0])))
    path = tmp_path / "tape.json"
    path.write_text(json.dumps(document))

    with pytest.raises(ValueError, match="duplicate"):
        load_tape(path)


def test_the_authored_flag_must_be_stated_not_defaulted(tmp_path) -> None:
    # WHY: an authored fixture presented as a real recording is the one lie
    # this harness must make impossible; absence is not honesty.
    document = _tape_document()
    provenance = document["provenance"]
    assert isinstance(provenance, dict)
    del provenance["authored"]
    path = tmp_path / "tape.json"
    path.write_text(json.dumps(document))

    with pytest.raises(ValueError):
        load_tape(path)


# ---- Golden compare order ----
def test_a_changed_expression_fails_as_stale_goldens_never_as_scores(tmp_path) -> None:
    # THE invariant (R11): when the rendered expression drifts, every score
    # downstream is measuring a different experiment. The compare must say
    # "expression changed, goldens stale" and must NOT mention scores.
    golden = GoldenReport.model_validate(_golden_document())
    actual = ActualOutcome(
        rendered_url4="a DIFFERENT rendered expression",
        final_score=0.0,  # also wrong on purpose — must not be reported
        case_statuses={"case_1": "failed", "case_2": "failed"},
        coverage=0.0,
    )

    with pytest.raises(GoldenMismatch) as failure:
        compare_outcome(golden, actual)

    assert failure.value.stage == "expression"
    assert "goldens stale" in str(failure.value)
    assert "score" not in str(failure.value).lower()


def test_matching_outcome_passes() -> None:
    golden = GoldenReport.model_validate(_golden_document())
    actual = ActualOutcome(
        rendered_url4="rendered expression",
        final_score=0.5,
        case_statuses={"case_1": "scored", "case_2": "refused"},
        coverage=0.5,
    )

    compare_outcome(golden, actual)  # must not raise


def test_case_statuses_are_checked_before_the_score() -> None:
    golden = GoldenReport.model_validate(_golden_document())
    actual = ActualOutcome(
        rendered_url4="rendered expression",
        final_score=0.0,  # wrong, but the status drift must be named first
        case_statuses={"case_1": "failed", "case_2": "refused"},
        coverage=0.0,
    )

    with pytest.raises(GoldenMismatch) as failure:
        compare_outcome(golden, actual)

    assert failure.value.stage == "cases"


def test_a_coverage_figure_that_contradicts_the_statuses_is_caught() -> None:
    # Stage 3 cross-checks the REPORT'S OWN coverage figure against what the
    # golden's counters imply. Statuses can match perfectly while the report's
    # aggregation math drifted — that is the one thing stage 2 cannot see.
    golden = GoldenReport.model_validate(_golden_document())
    actual = ActualOutcome(
        rendered_url4="rendered expression",
        final_score=0.5,
        case_statuses={"case_1": "scored", "case_2": "refused"},
        coverage=1.0,  # the report claims full coverage; its statuses say half
    )

    with pytest.raises(GoldenMismatch) as failure:
        compare_outcome(golden, actual)

    assert failure.value.stage == "coverage"


def test_a_score_drift_is_reported_as_decimal_strings() -> None:
    golden = GoldenReport.model_validate(_golden_document())
    actual = ActualOutcome(
        rendered_url4="rendered expression",
        final_score=0.75,
        case_statuses={"case_1": "scored", "case_2": "refused"},
        coverage=0.5,
    )

    with pytest.raises(GoldenMismatch) as failure:
        compare_outcome(golden, actual)

    assert failure.value.stage == "score"
    assert "0.75" in str(failure.value) and "0.5" in str(failure.value)


# ---- Golden validation on read ----
def test_load_golden_reads_a_valid_document(tmp_path) -> None:
    path = tmp_path / "synthetic.golden.json"
    path.write_text(json.dumps(_golden_document()))

    golden = load_golden(path)

    assert golden.board == "synthetic"
    assert golden.final_score == "0.5"


def test_unknown_fields_are_refused(tmp_path) -> None:
    # The parent contract says NO progress/stream fields — extra keys are a
    # symptom of a golden authored from the wrong surface.
    path = tmp_path / "synthetic.golden.json"
    path.write_text(json.dumps(_golden_document(progress=[1, 2, 3])))

    with pytest.raises(ValueError):
        load_golden(path)


def test_counters_must_agree_with_the_statuses(tmp_path) -> None:
    # gradeable_count is DERIVED truth (scored cases); a golden that
    # disagrees with its own statuses was hand-edited and must be refused.
    path = tmp_path / "synthetic.golden.json"
    path.write_text(json.dumps(_golden_document(gradeable_count=2)))

    with pytest.raises(ValueError, match="gradeable_count"):
        load_golden(path)


def test_an_unknown_case_status_is_refused(tmp_path) -> None:
    path = tmp_path / "synthetic.golden.json"
    path.write_text(
        json.dumps(_golden_document(case_statuses={"case_1": "scored", "case_2": "maybe"}))
    )

    with pytest.raises(ValueError):
        load_golden(path)


# ---- canonical_score ----
def test_floats_render_as_shortest_round_trip_decimal_strings() -> None:
    assert canonical_score(0.5) == "0.5"
    # Pinned literal, not repr(x) == repr(x): the golden file stores THIS string.
    assert canonical_score(1 / 3) == "0.3333333333333333"


def test_the_rendered_string_round_trips_to_the_exact_float() -> None:
    # The invariant that makes decimal-as-string safe: no precision is lost, so
    # two runs producing the same float always author the same golden string.
    for value in (0.1, 2 / 3, 0.8000000000000001):
        rendered = canonical_score(value)
        assert rendered is not None and float(rendered) == value


def test_absent_scores_stay_absent() -> None:
    assert canonical_score(None) is None
