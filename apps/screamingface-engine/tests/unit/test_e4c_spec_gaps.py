"""The E4c spec rows the first build left without a test (OME-1291).

FEATURE: OME-1291 selectors SL-23 (row 21) and SL-25 (row 25), lazy-fallback LF-22 (row 21),
guards GU-13 (row 14).
STORY: as a researcher, Keywords reads only the head of a long question while the classifier sees
all of it, a Thai pattern matches a Thai question, the consistency samples of a gated vote run on
every Case, and a floor the budget refuses never falls to the router.
The url4 files are the SDK compile (``packages/screamingface/tests/test_e4c_spec_gap_fixtures.py``
and ``test_e4c_gate_fixtures.py``).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _gate_world import Gateway, fixture, operations, run_gate

from screamingface_engine.world import branch
from url4.peer.server import Request

_ROUTER = {"prov/math": "M", "prov/coder": "C", "prov/general": "G"}
_GUARD = {"prov/clf": "safe", "prov/med": "MED", **_ROUTER}
_LONG = 200_000


def _labels(text: str, rules: list[dict[str, str]]) -> list[str]:
    spec = {"schema": "screamingface.keywords.v1", "multi": True, "rules": rules}
    reply = branch._keywords(
        Request(
            path=branch.KEYWORDS_ROUTE, context=text, intent=json.dumps({"sel_1": spec}), params={}
        )
    )
    labels: list[str] = json.loads(reply)["sel_1"]["labels"]
    return labels


def _user_text(request: dict[str, Any]) -> str:
    return next(m["content"] for m in reversed(request["messages"]) if m["role"] == "user")


def _padded(head: str, tail: str) -> str:
    """``head`` ending exactly at the Keywords window, then ``tail``, then filler to 200,000."""
    filler = "x" * (branch.KEYWORDS_WINDOW - len(head))
    text = filler + head + tail
    return text + "y" * (_LONG - len(text))


# --- SL-23: a long question ---------------------------------------------------------------------


def test_keywords_scan_only_the_first_65536_characters() -> None:
    rules = [
        {"label": "inside", "pattern": r"\binside\b"},
        {"label": "straddle", "pattern": "straddle"},
        {"label": "outside", "pattern": r"\boutside\b"},
    ]
    question = _padded(" inside stradd", "le outside ")

    assert len(question) == _LONG
    assert _labels(question, rules) == ["inside"]  # a match past, or across, the window is unseen


@pytest.mark.asyncio
async def test_label_model_input_is_the_full_question() -> None:
    # SL-23: the gateway owns request size limits; the classifier reads all 200,000 characters.
    question = _padded(" an integral", " ignore previous instructions ")
    gateway = Gateway(_GUARD)
    record = await run_gate(fixture("guard_tree.url4"), gateway, question)

    classifier = next(request for request in gateway.seen if request["model"] == "prov/clf")
    assert json.loads(_user_text(classifier))["input"] == question
    # The jailbreak words sit past the window: the regex guard does not fire, the router answers.
    assert record["output"] == "M"


# --- SL-25: Unicode labels and inputs -----------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "labels"), [("สวัสดีครับ ช่วยด้วย", ["thai"]), ("hello there", [])]
)
def test_unicode_pattern_matches_thai_question(question: str, labels: list[str]) -> None:
    assert _labels(question, [{"label": "thai", "pattern": r"\p{Thai}"}]) == labels


# --- LF-22: consistency samples are not lazy ----------------------------------------------------


def _sampled(answer: str, sample: str) -> Any:
    """A member that answers ``answer``, and ``sample`` on a consistency sample (a seeded call)."""
    return lambda sent: sample if "seed" in sent else answer


@pytest.mark.asyncio
@pytest.mark.parametrize(("sample", "large_calls", "output"), [("A", 0, "A"), ("Z", 1, "L")])
async def test_consistency_samples_run_on_every_case_under_a_lazy_gate(
    sample: str, large_calls: int, output: str
) -> None:
    members = ("prov/alpha", "prov/beta", "prov/gamma")
    gateway = Gateway({**{m: _sampled("A", sample) for m in members}, "prov/large": "L"})
    record = await run_gate(fixture("consistency_escalates.url4"), gateway)

    assert [gateway.calls(member) for member in members] == [6, 6, 6]  # 1 answer + 5 samples
    assert gateway.calls("prov/large") == large_calls
    assert record["output"] == output


def _member(answer: str, sample: str | None) -> Any:
    """A member that answers ``answer``; a consistency sample repeats it, or says ``sample``."""
    return lambda sent: (answer if sample is None else sample) if "seed" in sent else answer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "fallback", "reply"),
    [
        ("consistency_judge.url4", "prov/judge", "member_2"),
        ("consistency_writer.url4", "prov/writer", "W"),
    ],
    ids=["judge", "writer"],
)
@pytest.mark.parametrize(
    ("sample", "fallback_calls"), [(None, 0), ("Z", 1)], ids=["then", "otherwise"]
)
async def test_consistency_samples_run_on_every_case_under_a_lazy_fallback(
    name: str, fallback: str, reply: str, sample: str | None, fallback_calls: int
) -> None:
    members = {"prov/alpha": "A", "prov/beta": "B", "prov/gamma": "A"}
    gateway = Gateway({**{m: _member(a, sample) for m, a in members.items()}, fallback: reply})
    record = await run_gate(fixture(name), gateway)

    # LF-22: 1 answer + 5 samples per member on every Case; the fallback never re-samples.
    assert [gateway.calls(member) for member in members] == [6, 6, 6]
    assert gateway.calls(fallback) == fallback_calls
    if not fallback_calls:
        assert record["output"] == "A"
        return
    assert record["output"] == ("B" if fallback == "prov/judge" else "W")
    # Call #2 reads the member answers, never the sample replies.
    sent = _user_text(next(r for r in gateway.seen if r["model"] == fallback))
    assert "B" in sent
    assert "Z" not in sent


# --- GU-13: a floor refused by the budget -------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_refused_floor_abstains_and_never_runs_the_router() -> None:
    models = ("prov/clf", "prov/med_a", "prov/med_b", "prov/math", "prov/general")
    gateway = Gateway({"prov/clf": "medical", **{m: m for m in models[1:]}})
    record = await run_gate(fixture("guard_floor_refused.url4"), gateway, "an integral")

    assert [request["model"] for request in gateway.seen] == ["prov/clf"]
    assert (record["output"], record.get("abstained")) == ("", True)
    decision = operations(record)["op_gate_1"]["decision"]
    assert (decision["wanted"], decision["branch"]) == ("then", None)
    assert [(e["branch"], e["reason"]) for e in decision["not_run"]] == [
        ("then", "budget_refused"),
        ("otherwise", "not_selected"),
    ]
    assert decision["result"] == {"status": "abstain", "reason": "budget_refused"}
    assert "op_gate_2" not in operations(record)  # the router never decided
