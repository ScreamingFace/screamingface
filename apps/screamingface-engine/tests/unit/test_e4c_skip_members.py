"""Skip-Gate Fanout members: an unselected member makes zero calls and the combine leaves it out.

FEATURE: E4c (OME-1291) skip-members rows SM#3, #4, #6 - #14, #16, #17, #20, #22, #25 and the
SM-11 / SM-18 floor tables.
STORY: as a researcher who reproduces a manager-style method, the agents the selector did not pick
make no model call, the block's reducer joins only the picked members, and the evidence lists
the members that were not selected apart from the members that failed.
The url4 files are the SDK compile (``packages/screamingface/tests/test_e4c_gate_fixtures.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _gate_world import FAIL, Gateway, fixture, operations, run_gate
from combine_support import run, spec_text, vote_spec
from pydantic import ValidationError

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.evidence import CombineEvidence
from screamingface_engine.combine.ports import QuorumNotMet
from url4.core.errors import ResolutionError

_MEMBERS = {"prov/math": "A", "prov/code": "C", "prov/web": "A"}


def _combine(record: dict[str, Any]) -> dict[str, Any]:
    return next(op["combine"] for op in operations(record).values() if op.get("combine"))


# --- Engine world (SM#3, #4, #6, #8, #11 - #14, #16, #17, #22) --------------------------------


@pytest.mark.asyncio
async def test_unselected_skip_member_makes_zero_calls() -> None:
    # SM#3 / SM-1
    gateway = Gateway({"prov/sel": "math, web", **_MEMBERS})
    await run_gate(fixture("skip_vote.url4"), gateway)
    assert gateway.calls("prov/code") == 0
    assert gateway.calls("prov/math") == gateway.calls("prov/web") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["skip_vote.url4", "skip_vote_quorum.url4"])
async def test_unselected_slot_gives_an_empty_row_that_the_combine_excludes(name: str) -> None:
    # SM#4 / SM-10: no failure reaches the Case; the skipped row is never a voter.
    record = await run_gate(fixture(name), Gateway({"prov/sel": "math, web", **_MEMBERS}))
    assert record["status"] == "completed"
    assert record["output"] == "A"
    combine = _combine(record)
    assert combine["skipped"] == ["member_2"]
    assert "member_2" not in [row for tally in combine["tally"] for row in tally["holders"]]


@pytest.mark.asyncio
async def test_selected_members_vote_and_the_skipped_member_is_excluded_not_selected() -> None:
    # SM#6 / SM-2, SM#20 / SM-13
    record = await run_gate(
        fixture("skip_vote.url4"), Gateway({"prov/sel": "math, web", **_MEMBERS})
    )
    combine = _combine(record)
    skipped = next(row for row in combine["members"] if row["member_id"] == "member_2")
    assert (skipped["status"], skipped["reason"]) == ("excluded", "not_selected")
    assert (skipped["raw"], skipped["value"], skipped["score"], skipped["weight"]) == (None,) * 4
    assert all(value is None for value in skipped["signals"].values())
    assert combine["dropped"] == 0
    assert list(combine)[-1] == "skipped"  # the last key
    assert operations(record)["op_gate_2"]["decision"]["result"] is None


@pytest.mark.asyncio
async def test_selected_member_failure_under_quorum_all_fails_with_its_own_code() -> None:
    # SM#8 / SM-7 (ans:Q23)
    gateway = Gateway({"prov/sel": "math, web", **_MEMBERS, "prov/math": FAIL})
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture("skip_vote.url4"), gateway)
    assert caught.value.code == "aigateway_http_400"


@pytest.mark.asyncio
async def test_multi_selector_runs_once_before_the_panel() -> None:
    # SM#11 / SM-3, SM-9
    gateway = Gateway({"prov/sel": "math, code, web", **_MEMBERS})
    record = await run_gate(fixture("skip_vote.url4"), gateway)
    assert gateway.calls("prov/sel") == 1
    assert gateway.seen[0]["model"] == "prov/sel"
    records = [operations(record)[f"op_gate_{n}"]["decision"]["selectors"] for n in (1, 2, 3)]
    assert records[0] == records[1] == records[2]


@pytest.mark.asyncio
async def test_nothing_selected_abstains_no_votes() -> None:
    # SM#12 / SM-6
    gateway = Gateway({"prov/sel": "physics", **_MEMBERS})
    record = await run_gate(fixture("skip_vote.url4"), gateway)
    assert record.get("abstained") is True
    assert [request["model"] for request in gateway.seen] == ["prov/sel"]
    assert _combine(record)["result"]["reason"] == "no_votes"


@pytest.mark.asyncio
async def test_writer_block_gets_the_joined_text_of_the_selected_members() -> None:
    # SM#13 / SM-4, SM-23. Deviation (ledger): an implicit labelled sf.Concat, not the envelope.
    seen: list[str] = []

    def writer(request: dict[str, Any]) -> str:
        seen.append(request["messages"][-1]["content"])
        return "W"

    gateway = Gateway({"prov/math": "M", "prov/code": "C", "prov/writer": writer})
    record = await run_gate(fixture("skip_writer.url4"), gateway, "an integral please")
    assert record["output"] == "W"
    assert seen == ["[member_1]\nM"]
    assert gateway.calls("prov/code") == 0


@pytest.mark.asyncio
async def test_replay_skips_the_same_members() -> None:
    # SM#14 / SM-21
    runs = []
    for _ in range(2):
        gateway = Gateway({"prov/sel": "math, web", **_MEMBERS})
        record = await run_gate(fixture("skip_vote.url4"), gateway)
        runs.append((sorted(r["model"] for r in gateway.seen), json.dumps(_combine(record))))
    assert runs[0] == runs[1]


@pytest.mark.asyncio
async def test_rank_after_skip_members_ranks_selected_members_only() -> None:
    # SM#16 / SM-14, SM#17 / SM-16: the skipped member's declared value is null.
    gateway = Gateway(
        {
            "prov/sel": "math, code",
            "prov/math": "Confidence: 10\nM",
            "prov/code": "Confidence: 90\nC",
            "prov/web": "Confidence: 99\nW",
            "prov/writer": "OUT",
        }
    )
    record = await run_gate(fixture("skip_rank.url4"), gateway)
    combine = _combine(record)
    assert gateway.calls("prov/web") == 0
    assert combine["chosen"] == ["member_2"]
    web = next(row for row in combine["members"] if row["member_id"] == "member_3")
    assert web["signals"] == dict.fromkeys(web["signals"])


@pytest.mark.asyncio
async def test_two_members_with_the_same_label_both_run() -> None:
    # SM#22 / SM-19: skip_mixed's one skip member and the vote_quorum members share labels with
    # the selector; here the selector names math and web, each one member, both run.
    gateway = Gateway({"prov/sel": "math, web", **_MEMBERS})
    await run_gate(fixture("skip_vote.url4"), gateway)
    assert gateway.calls("prov/math") == gateway.calls("prov/web") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sel", "replies", "code"),
    [
        ("math", {}, None),  # quorum 1, one selected that answers: min(1, 1) = 1, met
        ("math, web", {"prov/math": FAIL, "prov/web": FAIL}, "quorum_not_met"),
        ("math, web", {"prov/math": FAIL}, None),  # one of two answered: quorum 1 met
    ],
)
async def test_quorum_counts_selected_members_with_min_floor(sel, replies, code) -> None:
    # SM-11 floor table on the Engine world (numeric quorum: optional slots, panel quorum 0).
    gateway = Gateway({"prov/sel": sel, **_MEMBERS, **replies})
    if code is None:
        record = await run_gate(fixture("skip_vote_quorum.url4"), gateway)
        assert record["status"] == "completed"
        return
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture("skip_vote_quorum.url4"), gateway)
    assert caught.value.code == code


@pytest.mark.asyncio
@pytest.mark.parametrize(("plain_b", "code"), [("A", None), (FAIL, "aigateway_http_400")])
async def test_mixed_plain_and_skip_members_floor(plain_b: str, code: str | None) -> None:
    # SM-18: quorum 2 counts the plain members and the selected skip member (none selected
    # here). A plain member stays a required slot, as today: its failure fails with its code.
    gateway = Gateway(
        {"prov/sel": "math", "prov/plain_a": "A", "prov/plain_b": plain_b, "prov/web": "W"}
    )
    if code is None:
        record = await run_gate(fixture("skip_mixed.url4"), gateway)
        assert record["output"] == "A"
        assert gateway.calls("prov/web") == 0
        return
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture("skip_mixed.url4"), gateway)
    assert caught.value.code == code


# --- the combine call (SM#7, #9, #10, #20, #25) -------------------------------------------------


def _record(branch: str) -> str:
    """A whole DECIDE record of an input gate that took ``branch`` (the combine validates it)."""

    other = "otherwise" if branch == "then" else "then"
    return json.dumps(
        {
            "schema": "screamingface.gate-decision.v1",
            "gate_id": "gate_1",
            "kind": "input",
            "when": {"observe": "budget.remaining:usd", "cmp": ">=", "value": 0.0},
            "observed": 1.0,
            "passed": branch == "then",
            "wanted": branch,
            "branch": branch,
            "selectors": [],
            "not_run": [
                {"branch": other, "reason": "not_selected", "model_calls": {"min": 0, "max": 0}}
            ],
            "budget": None,
            "result": None,
            "panel": None,
        }
    )


def _context(outputs: dict[str, str], selection: dict[str, str], floor: int | None = None) -> str:
    """A quorum panel context: ``outputs`` are the members that answered (one row each)."""
    rows = [
        {"source_position": int(member.rsplit("_", 1)[1]), "source_name": member, "result": text}
        for member, text in outputs.items()
    ]
    body: dict[str, Any] = {"input": "q", "panel": json.dumps(rows), "selection": selection}
    if floor is not None:
        body["floor"] = floor
    return json.dumps(body)


def _vote() -> str:
    return spec_text(
        vote_spec(
            3,
            extract={"op": "last_line@1", "args": {}},
            normalize={"op": "text@1", "args": {}},
            reduce={"op": "mode@1", "args": {}},
            select={"op": "first_holder@1", "args": {}},
        )
    )


@pytest.mark.parametrize(
    ("outputs", "selection", "floor", "met"),
    [
        ({"member_1": "A", "member_2": "", "member_3": "A"}, {"member_2": "otherwise"}, 2, True),
        (
            {"member_1": "A", "member_2": "", "member_3": ""},
            {"member_2": "otherwise", "member_3": "otherwise"},
            2,
            True,
        ),
        (
            {"member_2": "", "member_3": "A"},
            {"member_2": "otherwise", "member_1": "then"},
            2,
            False,
        ),
    ],
    ids=["two_of_two", "floor_min_selected_answered", "below_floor"],
)
def test_quorum_counts_selected_members_with_min_floor_at_the_combine(
    outputs, selection, floor, met
) -> None:
    # SM#7: N <= selected, N > selected (min floor), below the floor -> quorum_not_met.
    context = _context(
        outputs, {member: _record(branch) for member, branch in selection.items()}, floor
    )
    if met:
        assert run(_vote(), context, registry=BUILTIN_OPERATORS).output == "A"
        return
    with pytest.raises(QuorumNotMet) as caught:
        run(_vote(), context, registry=BUILTIN_OPERATORS)
    assert caught.value.code == "quorum_not_met"


def test_skip_and_failure_are_told_apart_by_the_selection_context() -> None:
    # SM#9 / SM-12: member_2 is skipped (empty row), member_3 left the panel (failed).
    context = json.dumps(
        {
            "input": "q",
            "panel": json.dumps(
                [
                    {"source_position": 1, "source_name": "member_1", "result": "A"},
                    {"source_position": 2, "source_name": "member_2", "result": ""},
                ]
            ),
            "selection": {"member_2": _record("otherwise")},
        }
    )
    outcome = run(_vote(), context, registry=BUILTIN_OPERATORS)
    assert outcome.evidence is not None
    rows = {row.member_id: (row.status, row.reason) for row in outcome.evidence.members}
    assert rows == {
        "member_1": ("answered", None),
        "member_2": ("excluded", "not_selected"),
        "member_3": ("fail", "missing"),
    }
    assert outcome.evidence.skipped == ["member_2"]
    assert outcome.evidence.dropped == 1


def test_evidence_not_selected_without_narrow_needs_skipped() -> None:
    # SM#10 / SM-13: NR-I4 extended, both directions.
    outcome = run(
        _vote(),
        _context(
            {"member_1": "A", "member_2": "", "member_3": "A"}, {"member_2": _record("otherwise")}
        ),
        registry=BUILTIN_OPERATORS,
    )
    assert outcome.evidence is not None
    wire = outcome.evidence.model_dump(by_alias=True)
    CombineEvidence.model_validate(wire)  # valid with `skipped`
    without = {key: value for key, value in wire.items() if key != "skipped"}
    with pytest.raises(ValidationError, match="not_selected goes with a narrow record"):
        CombineEvidence.model_validate(without)
    valued = json.loads(json.dumps(wire))
    valued["members"][1]["raw"] = "x"
    with pytest.raises(ValidationError, match="a skipped member is excluded, not_selected"):
        CombineEvidence.model_validate(valued)


def test_combine_evidence_schema_snapshot_has_skipped() -> None:
    # SM#25 (the owner-approved snapshot edit is the regenerated file).
    schema = json.loads(
        (
            Path(__file__).parent
            / "data"
            / "combine_contract"
            / "schemas"
            / "screamingface.combine-evidence.v1.json"
        ).read_text(encoding="utf-8")
    )
    assert "skipped" in schema["properties"]
