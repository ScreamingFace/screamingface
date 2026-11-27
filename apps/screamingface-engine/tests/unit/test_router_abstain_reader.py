"""C10: the Engine reads a Router ``no_selection`` abstention before any writer exists.

FEATURE: Router Recipe extension (Unit 6, C10). A Router that selects no candidate and has no
default abstains with the ``answer.v1`` reason ``no_selection``. Readers accept the word first,
as E4c did for ``budget_refused``; the Router writer comes later.
STORY: as a researcher replaying a Router run, a case whose Router selected nothing reads as one
more abstention, not as a broken record.

INVARIANT (C10): the word is read only with status ``abstain`` and refused everywhere else: a
failed member refuses every abstain word, as the SDK answer row does, and a Router synthesis, which
runs only after a selection, refuses this word. No Gate, Band, Pick, budget or ``NoVotes`` writer
can emit it. Every legacy word keeps its bytes and its enum position, and both schema IDs stay as
they are.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError
from router_decision_support import EXACT_ALL, attempts, llm_evidence, record_document

from screamingface_engine.combine import ports
from screamingface_engine.combine.decision import GateResult
from screamingface_engine.combine.evidence import (
    COMBINE_EVIDENCE_SCHEMA,
    AnswerRecord,
    ResultRecord,
)
from screamingface_engine.combine.ports import (
    ABSTAIN_REASONS,
    AbstainReason,
    AnswerReason,
    NoVotes,
)
from screamingface_engine.router_decision import RouterDecisionError, parse_router_decision
from screamingface_engine.router_record_parts import ModelSynthesis, VoteSynthesis

# The one synthetic Router abstention; the SDK twin test reads the same bytes.
SYNTHETIC = b'{"member_id":null,"value":null,"status":"abstain","reason":"no_selection"}'
_LEGACY_ABSTAIN = (
    "no_votes",
    "cut_not_met",
    "output_missing",
    "gate_not_met",
    "in_band",
    "budget_refused",
)
_FAILURE = (
    "empty",
    "not_numeric",
    "not_json",
    "field_missing",
    "too_large",
    "no_match",
    "missing",
)
_LEGACY_ANSWER = (*_FAILURE, *_LEGACY_ABSTAIN)
_SCHEMAS = Path(__file__).parent / "data" / "combine_contract" / "schemas"
_SOURCE = Path(ports.__file__).parents[1]


def _record(**changes: object) -> bytes:
    body: dict[str, object] = {
        "member_id": None,
        "value": None,
        "status": "abstain",
        "reason": "no_selection",
    }
    body.update(changes)
    return json.dumps(body, separators=(",", ":")).encode()


# --- the reader ---------------------------------------------------------------------------------


def test_the_synthetic_abstention_reads_and_writes_back_the_same_bytes() -> None:
    record = ResultRecord.model_validate_json(SYNTHETIC)

    assert (record.member_id, record.value, record.status, record.reason) == (
        None,
        None,
        "abstain",
        "no_selection",
    )
    assert record.model_dump_json().encode() == SYNTHETIC


def test_a_gate_result_reads_the_word_as_an_abstention() -> None:
    # WHY: C10 widens the reader vocabulary the Gate record shares; no Gate writes the word.
    result = GateResult.model_validate_json(b'{"status":"abstain","reason":"no_selection"}')

    assert (result.status, result.reason) == ("abstain", "no_selection")


_REFUSED = {
    "answered": _record(status="answered"),
    "answered-with-value": _record(status="answered", value="A"),
    "fail": _record(status="fail"),
    "excluded": _record(status="excluded"),
    "with-member": _record(member_id="member_1"),
    "with-value": _record(value="A"),
    "reversed": _record(status="no_selection", reason="abstain"),
    "extra-key": _record(text=None),
    "missing-key": b'{"member_id":null,"status":"abstain","reason":"no_selection"}',
    "other-case": _record(reason="No_Selection"),
    "padded": _record(reason="no_selection "),
    "abstain-without-reason": _record(reason=None),
    "reason-not-text": _record(reason=["no_selection"]),
}


@pytest.mark.parametrize("body", list(_REFUSED.values()), ids=list(_REFUSED))
def test_any_other_shape_is_refused(body: bytes) -> None:
    with pytest.raises(ValidationError):
        ResultRecord.model_validate_json(body)


@pytest.mark.parametrize("status", ["answered", "fail_closed"])
def test_a_gate_result_refuses_the_word_without_an_abstention(status: str) -> None:
    body = json.dumps({"status": status, "reason": "no_selection"}).encode()

    with pytest.raises(ValidationError):
        GateResult.model_validate_json(body)


# --- a failed member ----------------------------------------------------------------------------


def _member(**changes: object) -> bytes:
    body: dict[str, object] = {
        "member_id": "member_1",
        "raw": None,
        "value": None,
        "status": "fail",
        "reason": "no_selection",
        "signals": {},
        "weight": None,
        "score": None,
    }
    body.update(changes)
    return json.dumps(body, separators=(",", ":")).encode()


@pytest.mark.parametrize("reason", ABSTAIN_REASONS)
def test_a_failed_member_never_carries_an_abstain_word(reason: str) -> None:
    # INVARIANT (C10 parity): the SDK combine answer row and Answer refuse the same record, so on
    # both sides the word reads only on an abstain result.
    with pytest.raises(ValidationError, match="a failure reason, not an abstain reason"):
        AnswerRecord.model_validate_json(_member(reason=reason))


@pytest.mark.parametrize("reason", _FAILURE)
def test_a_failed_member_keeps_every_failure_word_and_its_bytes(reason: str) -> None:
    body = _member(reason=reason)

    assert AnswerRecord.model_validate_json(body).model_dump_json().encode() == body


# --- a Router synthesis -------------------------------------------------------------------------

_SYNTHESES: dict[str, dict[str, object]] = {
    "model": {
        "kind": "model",
        "status": "abstained",
        "reason": "no_selection",
        "code": None,
        **attempts(),
    },
    "vote": {"kind": "vote", "status": "abstained", "reason": "no_selection", "code": None},
}
_SYNTHESIS_MODELS = {"model": ModelSynthesis, "vote": VoteSynthesis}


@pytest.mark.parametrize("kind", _SYNTHESES)
def test_a_synthesis_never_abstains_with_the_word(kind: str) -> None:
    # WHY: a synthesis exists only once a non-empty subset was selected; no_selection is the C6
    # outcome of selecting none, so reading it here would merge the two phases (C5).
    with pytest.raises(ValidationError, match="never no_selection"):
        _SYNTHESIS_MODELS[kind].model_validate_json(json.dumps(_SYNTHESES[kind]))


@pytest.mark.parametrize("reason", _LEGACY_ABSTAIN)
@pytest.mark.parametrize("kind", _SYNTHESES)
def test_a_synthesis_keeps_every_legacy_abstain_word(kind: str, reason: str) -> None:
    body = json.dumps({**_SYNTHESES[kind], "reason": reason})

    assert _SYNTHESIS_MODELS[kind].model_validate_json(body).reason == reason


@pytest.mark.parametrize(("status", "code"), [("answered", None), ("failed", "upstream_error")])
@pytest.mark.parametrize("kind", _SYNTHESES)
def test_a_synthesis_without_an_abstention_still_reads(kind: str, status: str, code: str) -> None:
    body = json.dumps({**_SYNTHESES[kind], "status": status, "reason": None, "code": code})

    assert _SYNTHESIS_MODELS[kind].model_validate_json(body).status == status


def _subset_record(reason: str) -> str:
    member = {"role": "candidate", "status": "answered", "code": None, **attempts()}
    selected = [
        {"index": 1, "label": "math", "model": "acme/math"},
        {"index": 0, "label": "code", "model": "acme/coder"},
    ]
    synthesis = {**_SYNTHESES["model"], "reason": reason}
    return json.dumps(
        record_document(
            policy=EXACT_ALL,
            evidence=llm_evidence(["math", "code"], [], "ok"),
            reason="exact",
            selected=selected,
            unknown_labels=[],
            classifier_call={"binding": "selector_1", "cost": 0.0001, **attempts()},
            branches=[{**member, **entry} for entry in selected],
            quorum={"floor": 1, "selected": 2, "answered": 2},
            synthesis=synthesis,
            status="abstained",
        )
    )


def test_the_completed_router_record_keeps_its_synthesis_words() -> None:
    # The C5 record JOIN publishes reads a legacy synthesis abstention and refuses this word.
    assert parse_router_decision(_subset_record("no_votes")).status == "abstained"
    with pytest.raises(RouterDecisionError, match="never no_selection"):
        parse_router_decision(_subset_record("no_selection"))


# --- the writers --------------------------------------------------------------------------------


def test_no_votes_cannot_carry_the_word() -> None:
    # INVARIANT (C10): NoVotes is the one writer that takes a reason; it keeps the legacy six.
    with pytest.raises(ValueError, match="unknown abstain reason"):
        NoVotes(reason="no_selection")


@pytest.mark.parametrize("reason", _LEGACY_ABSTAIN)
def test_no_votes_still_carries_every_legacy_word(reason: AbstainReason) -> None:
    assert NoVotes(reason=reason).reason == reason


def _writer_sources() -> list[Path]:
    combine = sorted((_SOURCE / "combine").rglob("*.py"))
    return [path for path in combine if path.name != "ports.py"] + [_SOURCE / "world" / "branch.py"]


def test_no_gate_band_pick_or_budget_writer_names_the_word() -> None:
    # WHY a source check: those writers emit fixed words; a new literal here would be a writer.
    sources = _writer_sources()

    assert len(sources) > 10
    assert [path.name for path in sources if "no_selection" in path.read_text("utf-8")] == []


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_the_public_words_do_not_borrow_the_private_router_vocabulary() -> None:
    # INVARIANT: answer.v1 words live in combine.ports; the Router's own Outcome stays private.
    imported = _imported_modules(Path(ports.__file__))

    assert imported
    assert not [name for name in imported if "router" in name or ".world" in name]


# --- legacy identity ----------------------------------------------------------------------------


def test_the_word_is_appended_after_every_legacy_word() -> None:
    assert get_args(AbstainReason) == (*_LEGACY_ABSTAIN, "no_selection")
    assert ABSTAIN_REASONS == (*_LEGACY_ABSTAIN, "no_selection")
    assert get_args(AnswerReason) == (*_LEGACY_ANSWER, "no_selection")


@pytest.mark.parametrize("reason", _LEGACY_ABSTAIN)
def test_a_legacy_abstention_keeps_its_bytes(reason: str) -> None:
    body = _record(reason=reason)

    assert ResultRecord.model_validate_json(body).model_dump_json().encode() == body


def test_an_answered_result_keeps_its_bytes() -> None:
    body = _record(member_id="member_2", value="B", status="answered", reason=None)

    assert ResultRecord.model_validate_json(body).model_dump_json().encode() == body


def test_the_pinned_evidence_schema_keeps_its_id_and_appends_the_word() -> None:
    assert COMBINE_EVIDENCE_SCHEMA == "screamingface.combine-evidence.v1"
    pinned = json.loads((_SCHEMAS / f"{COMBINE_EVIDENCE_SCHEMA}.json").read_text("utf-8"))
    result = pinned["$defs"]["ResultRecord"]["properties"]["reason"]["anyOf"][0]["enum"]
    answer = pinned["$defs"]["AnswerRecord"]["properties"]["reason"]["anyOf"][0]["enum"]

    assert result == [*_LEGACY_ABSTAIN, "no_selection"]
    assert answer == [*_LEGACY_ANSWER, "no_selection"]
