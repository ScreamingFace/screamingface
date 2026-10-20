"""Logprob and entropy Fusions run end to end in the Engine world (E4b part 3, unit 4).

FEATURE: a Candidate that the SDK compiles with ``sf.Logprob`` or ``sf.Entropy`` runs offline with
a mocked gateway; each member's reply logprobs (unit 3) become the declared value that Pick, Rank,
Filter and a weighted Vote read, and the evidence records it.
STORY: as a researcher, I keep the member answer its model was surest of, with no extra call.
INVARIANT defended: each member call asks for ``logprobs`` (and ``top_logprobs`` for entropy);
the signal costs no model call; one reply feeds both a logprob and an entropy name (EN-D4).
The fixtures are the SDK compiles of ``ST/test_logprob_entropy_url4_fixtures.py`` (drift guard).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _logprob_world import LN, Position, by_model, logprobs_object, run_logprob_candidate
from _signal_world import operation

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import run_combine
from screamingface_engine.combine.ports import (
    REPLY_ENTROPY_MEAN,
    REPLY_LOGPROB_SUM,
    REPLY_TOKENS,
    MemberSources,
)

_DATA = Path(__file__).parent / "data" / "combine_contract"
_ALPHA = "openrouter/acme/alpha"
_BETA = "openrouter/acme/beta"
_GAMMA = "openrouter/acme/gamma"
_WRITER = "openrouter/acme/writer"
_ABC = {_ALPHA: "A", _BETA: "B", _GAMMA: "C"}
# one token each: the mean is the value itself
_LP_TABLE: dict[str, list[Position]] = {
    _ALPHA: [(-0.9, [])],
    _BETA: [(-0.2, [])],
    _GAMMA: [(-0.5, [])],
}
# H = ln 2, 0, ln 4
_ENT_TABLE: dict[str, list[Position]] = {
    _ALPHA: [(-0.7, [LN(0.5), LN(0.5)])],
    _BETA: [(0.0, [0.0])],
    _GAMMA: [(-1.4, [LN(0.25)] * 4)],
}
_LN2 = 0.6931471805599453
_LN4 = 1.3862943611198906


def _candidate(name: str) -> str:
    # WHY read here and not at import: a missing fixture must fail the test (RED), not collection.
    path = _DATA / name
    assert path.exists(), f"combine_contract/{name} is missing - write it with the SDK"
    return path.read_text(encoding="utf-8").removesuffix("\n")


def _combine(record: dict[str, Any]) -> dict[str, Any]:
    combine: dict[str, Any] = operation(record, "op_synthesis_1")["combine"]
    return combine


def _envelope_ids(bodies: list[dict[str, Any]]) -> list[str]:
    writer = next(body for body in bodies if body["model"] == _WRITER)
    envelope = json.loads(writer["messages"][-1]["content"])
    return [item["id"] for item in envelope["selected"]]


# --- LP#7: Pick by the mean logprob ----------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_max_by_logprob_mean() -> None:
    bodies: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _candidate("logprob_pick_mean_candidate.url4"),
        _ABC,
        by_model(_LP_TABLE),
        on_request=bodies.append,
    )

    assert record["status"] == "completed"
    assert record["output"] == "B"
    combine = _combine(record)
    assert combine["chosen"] == ["member_2"]
    assert [m["signals"] for m in combine["members"]] == [{"lp": -0.9}, {"lp": -0.2}, {"lp": -0.5}]
    assert combine["declared"] == {"lp": {"source": "logprob", "form": "mean"}}
    assert combine["signal"] == {"key": "lp", "order": "max"}
    assert len(bodies) == 3
    for body in bodies:
        assert body["logprobs"] is True
        assert "top_logprobs" not in body


# --- LP#8: a vote weighted by prob ----------------------------------------------------------


@pytest.mark.asyncio
async def test_vote_weighted_by_logprob_prob() -> None:
    record = await run_logprob_candidate(
        _candidate("logprob_vote_prob_candidate.url4"),
        {_ALPHA: "A", _BETA: "B", _GAMMA: "A"},
        by_model({_ALPHA: [(LN(0.8), [])], _BETA: [(LN(0.7), [])], _GAMMA: [(LN(0.1), [])]}),
    )

    assert record["status"] == "completed"
    assert record["output"] == "A"  # A = 0.8 + 0.1 = 0.9 > B = 0.7
    combine = _combine(record)
    probs = [m["signals"]["p"] for m in combine["members"]]
    assert probs == pytest.approx([0.8, 0.7, 0.1], rel=1e-12)
    assert all(0 < p <= 1 for p in probs)  # LP-D1
    assert [m["weight"] for m in combine["members"]] == pytest.approx([0.8, 0.7, 0.1], rel=1e-12)
    assert combine["signal"] == {"key": "p", "order": None}


# --- LP#9: Filter by a threshold, and the one-member steer --------------------------------------


@pytest.mark.asyncio
async def test_filter_by_logprob_threshold_records_the_values() -> None:
    bodies: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _candidate("logprob_filter_mean_candidate.url4"),
        {**_ABC, _WRITER: "final"},
        by_model(_LP_TABLE),
        on_request=bodies.append,
    )

    assert record["status"] == "completed"
    assert record["output"] == "final"
    combine = _combine(record)
    assert combine["chosen"] == ["member_2", "member_3"]  # -0.5 >= -0.5 passes
    assert [m["score"] for m in combine["members"]] == [0.0, 1.0, 1.0]
    assert [m["signals"] for m in combine["members"]] == [{"lp": -0.9}, {"lp": -0.2}, {"lp": -0.5}]
    assert _envelope_ids(bodies) == ["member_2", "member_3"]


@pytest.mark.asyncio
async def test_steer_filter_records_the_member_mean_and_its_pass() -> None:
    replies = {_ALPHA: "A", _WRITER: "final"}
    kept_bodies: list[dict[str, Any]] = []
    kept = await run_logprob_candidate(
        _candidate("logprob_steer_filter_candidate.url4"),
        replies,
        by_model({_ALPHA: [(-0.2, [])]}),
        on_request=kept_bodies.append,
    )
    dropped_bodies: list[dict[str, Any]] = []
    dropped = await run_logprob_candidate(
        _candidate("logprob_steer_filter_candidate.url4"),
        replies,
        by_model({_ALPHA: [(-0.9, [])]}),
        on_request=dropped_bodies.append,
    )

    first = _combine(kept)
    assert first["chosen"] == ["member_1"]
    assert [m["score"] for m in first["members"]] == [1.0]
    assert [m["signals"] for m in first["members"]] == [{"lp": -0.2}]
    assert _envelope_ids(kept_bodies) == ["member_1"]
    second = _combine(dropped)
    assert second["chosen"] == []
    assert [m["score"] for m in second["members"]] == [0.0]
    assert [m["signals"] for m in second["members"]] == [{"lp": -0.9}]
    assert dropped["output"] == "final"  # the writer still runs (the skip is E4c, N2)
    assert len(dropped_bodies) == 2


# --- LP#10: each sample member gets its own logprob ---------------------------------------------


@pytest.mark.asyncio
async def test_samples_members_get_their_own_logprob() -> None:
    by_seed: dict[int, list[Position]] = {0: [(-0.9, [])], 1: [(-0.2, [])], 2: [(-0.5, [])]}
    bodies: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _candidate("logprob_samples_pick_candidate.url4"),
        {_ALPHA: "S"},
        lambda body: logprobs_object(by_seed[body["seed"]]),
        on_request=bodies.append,
    )

    assert record["status"] == "completed"
    assert sorted(body["seed"] for body in bodies) == [0, 1, 2]
    assert all(body["logprobs"] is True for body in bodies)
    combine = _combine(record)
    assert [m["signals"] for m in combine["members"]] == [{"lp": -0.9}, {"lp": -0.2}, {"lp": -0.5}]
    assert combine["chosen"] == ["member_2"]


# --- LP#12: Rank by the mean logprob keeps the top k --------------------------------------------


@pytest.mark.asyncio
async def test_rank_by_logprob_mean_keeps_the_top_k() -> None:
    bodies: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _candidate("logprob_rank_mean_candidate.url4"),
        {**_ABC, _WRITER: "final"},
        by_model(_LP_TABLE),
        on_request=bodies.append,
    )

    assert record["status"] == "completed"
    assert record["output"] == "final"
    combine = _combine(record)
    assert combine["chosen"] == ["member_2", "member_3"]  # rank order: -0.2, then -0.5
    assert [m["signals"] for m in combine["members"]] == [{"lp": -0.9}, {"lp": -0.2}, {"lp": -0.5}]
    assert _envelope_ids(bodies) == ["member_2", "member_3"]


# --- LP#13 (engine half): Pick by sum, Filter by prob -------------------------------------------


@pytest.mark.asyncio
async def test_pick_and_filter_accept_sum_and_prob_in_the_engine() -> None:
    # alpha: sum -1.0, mean -0.25; beta: sum -0.5, mean -0.5. A mean would pick member_1.
    summed = await run_logprob_candidate(
        _candidate("logprob_pick_sum_candidate.url4"),
        {_ALPHA: "A", _BETA: "B"},
        by_model({_ALPHA: [(-0.25, [])] * 4, _BETA: [(-0.5, [])]}),
    )
    assert summed["output"] == "B"
    pick = _combine(summed)
    assert pick["chosen"] == ["member_2"]
    assert [m["signals"] for m in pick["members"]] == [{"lp": -1.0}, {"lp": -0.5}]

    # prob: exp(-0.2), exp(-0.9), exp(-0.2); the threshold is 0.8
    filtered = await run_logprob_candidate(
        _candidate("logprob_filter_prob_candidate.url4"),
        {**_ABC, _WRITER: "final"},
        by_model(
            {
                _ALPHA: [(-0.1, []), (-0.2, []), (-0.3, [])],
                _BETA: [(-0.9, [])],
                _GAMMA: [(-0.2, [])],
            }
        ),
    )
    kept = _combine(filtered)
    assert kept["chosen"] == ["member_1", "member_3"]
    assert [m["signals"]["p"] for m in kept["members"]] == pytest.approx(
        [0.8187307530779818, 0.4065696597405991, 0.8187307530779818], rel=1e-12
    )


# --- EN#9: Pick the lowest entropy ---------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_min_by_entropy() -> None:
    bodies: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _candidate("entropy_pick_min_candidate.url4"),
        _ABC,
        by_model(_ENT_TABLE),
        on_request=bodies.append,
    )

    assert record["status"] == "completed"
    assert record["output"] == "B"
    combine = _combine(record)
    assert combine["chosen"] == ["member_2"]
    assert [m["signals"]["ent"] for m in combine["members"]] == pytest.approx(
        [_LN2, 0.0, _LN4], rel=1e-12
    )
    assert combine["declared"] == {"ent": {"source": "entropy", "top_logprobs": 5}}
    assert combine["signal"] == {"key": "ent", "order": "min"}
    assert len(bodies) == 3
    for body in bodies:
        assert body["logprobs"] is True
        assert body["top_logprobs"] == 5


# --- EN#10: one reply feeds a logprob name and an entropy name ---------------------------------


@pytest.mark.asyncio
async def test_logprob_and_entropy_share_one_reply() -> None:
    bodies: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _candidate("logprob_entropy_shared_candidate.url4"),
        _ABC,
        by_model(
            {
                _ALPHA: [(-0.9, [LN(0.5), LN(0.5)])],
                _BETA: [(-0.2, [0.0])],
                _GAMMA: [(-0.5, [LN(0.25)] * 4)],
            }
        ),
        on_request=bodies.append,
    )

    assert record["status"] == "completed"
    assert len(bodies) == 3
    for body in bodies:
        assert body["logprobs"] is True
        assert body["top_logprobs"] == 5
    combine = _combine(record)
    assert [m["signals"]["lp"] for m in combine["members"]] == [-0.9, -0.2, -0.5]
    assert [m["signals"]["ent"] for m in combine["members"]] == pytest.approx(
        [_LN2, 0.0, _LN4], rel=1e-12
    )
    assert combine["chosen"] == ["member_2"]
    assert combine["declared"] == {
        "lp": {"source": "logprob", "form": "mean"},
        "ent": {"source": "entropy", "top_logprobs": 5},
    }


# --- support (no PRD row): ONE member reader call feeds every reply name and the accounting key -


def test_one_reader_call_feeds_the_reply_names_and_the_accounting_key() -> None:
    spec = {
        "extract": None,
        "members": ["member_1", "member_2"],
        "normalize": None,
        "reduce": {"args": {"key": "cost_usd", "order": "min"}, "op": "by_signal@1"},
        "reducer": "pick",
        "schema": "screamingface.combine-spec.v1",
        "select": {"args": {"order": "min"}, "op": "best_holder@1"},
        "signals": {
            "ent": {"source": "entropy", "top_logprobs": 5},
            "lp": {"form": "mean", "source": "logprob"},
        },
        "weights": None,
    }
    asked = "logprobs=true&top_logprobs=5"
    context = {
        "input": "q",
        "outputs": {"member_1": "A", "member_2": "B"},
        "sources": {
            "member_1": {"model_1": {"path": "/openrouter/acme/alpha", "params": asked}},
            "member_2": {"model_2": {"path": "/openrouter/acme/beta", "params": asked}},
        },
    }
    calls: list[MemberSources] = []

    def reader(sources: MemberSources) -> dict[str, dict[str, float | None]]:
        calls.append(sources)
        return {
            "member_1": {
                "cost_usd": 0.002,
                REPLY_TOKENS: 2.0,
                REPLY_LOGPROB_SUM: -1.0,
                REPLY_ENTROPY_MEAN: 0.5,
            },
            "member_2": {
                "cost_usd": 0.001,
                REPLY_TOKENS: 1.0,
                REPLY_LOGPROB_SUM: -0.1,
                REPLY_ENTROPY_MEAN: 0.25,
            },
        }

    outcome = run_combine(
        BUILTIN_OPERATORS,
        {"binding": "synthesis_1"},
        json.dumps(context),
        json.dumps(spec),
        accounting=reader,
    )

    assert len(calls) == 1
    assert outcome.output == "B"
    assert [m.signals for m in outcome.evidence.members] == [
        {"cost_usd": 0.002, "ent": 0.5, "lp": -0.5},
        {"cost_usd": 0.001, "ent": 0.25, "lp": -0.1},
    ]
