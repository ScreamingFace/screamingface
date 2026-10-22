"""sf.Budget on the Engine world: DECIDE folds the ancestors' charges and refuses optional calls.

FEATURE: E4c (OME-1291) budget rows BU#4 - #11, #13 - #17, #21, #23, #25, #28 (the CHAR rows #1
and #2 are ``test_budget.py::test_cache_hit_charges_original_cost`` and
``::test_unpriced_charge_counts_but_does_not_spend``).
STORY: as a researcher whose result is a saving, the cap is real money the provider never bills: a
branch that would pass the cap is not sent, the calls that always run are never refused, and the
decision record shows the spend against the cap.
The url4 files are the SDK compile (``packages/screamingface/tests/test_e4c_budget_fixtures.py``).
The fake gateway charges 0.001 USD and 14 tokens (10 in + 4 out) per call.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, get_args

import httpx
import pytest
from _gate_world import Gateway, fixture, operations, run_gate
from _signal_world import _body

from screamingface_engine.benchmarks.invocation import candidate_budgets
from screamingface_engine.budget import (
    Budget,
    BudgetCharge,
    BudgetStage,
    budget_schemas,
    case_budgets,
    current_case_budgets,
)
from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from screamingface_engine.world import branch
from url4.core.errors import ResolutionError
from url4.peer.server import Request

_CASCADE = {"prov/a": "A", "prov/b": "B", "prov/c": "C", "prov/d": "D", "prov/large": "L"}


class _Priced(Gateway):
    """The fake gateway with a cache status, or a reply with no price (``usd``) or no usage."""

    cache: str = "miss"
    drop: tuple[str, ...] = ()

    async def handle(self, request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        self.seen.append(sent)
        reply = self.replies[sent["model"]]
        body = _body(reply(sent) if callable(reply) else reply, "0.001", self.cache)
        if "usd" in self.drop:
            del body["_aigw"]
        if "usage" in self.drop:
            del body["usage"]
        return httpx.Response(200, headers={"X-AIGW-Cache": self.cache}, json=body)


def _priced(replies: Mapping[str, str], *, cache: str = "miss", drop: Sequence[str] = ()) -> Any:
    gateway = _Priced(replies)
    gateway.cache, gateway.drop = cache, tuple(drop)
    return gateway


def _decisions(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: op["decision"] for key, op in operations(record).items() if op.get("decision")}


# --- unit: the refusal rule on DECIDE (BU#4, #5, #7, #8, #21, #28) -----------------------------


def _ancestor(binding: str) -> list[Any]:
    return [f"/prov/{binding}", [["binding", binding]]]


def _spec(
    *,
    estimate: Mapping[str, float] | None = None,
    ancestors: Sequence[str] = ("model_1",),
    otherwise: str = "abstain",
    unit: str = "usd",
) -> dict[str, Any]:
    word = otherwise in ("abstain", "fail_closed")
    return {
        "schema": "screamingface.gate-spec.v1",
        "kind": "input",
        "when": {"observe": f"budget.remaining:{unit}", "cmp": ">=", "value": 0.0},
        "then": "recipe",
        "otherwise": otherwise,
        "panel": None,
        "calls": {
            "then": {"min": 1, "max": 1},
            "otherwise": {"min": 0, "max": 0} if word else {"min": 1, "max": 1},
        },
        "selectors": {},
        "reads": {"then": [], "otherwise": []},
        "estimate": {"then": None if estimate is None else dict(estimate), "otherwise": None},
        "ancestors": [_ancestor(name) for name in ancestors],
        "terminal": {"then": "model_9", "otherwise": None if word else "model_8"},
    }


def _call(binding: str, signals: SignalAccounting | None) -> OperationCall:
    return OperationCall(
        f"/prov/{binding}", (("binding", binding),), "x", "stop", None, signal_accounting=signals
    )


def _usd(amount: float) -> SignalAccounting:
    return SignalAccounting(cost_usd=amount, tokens_in=10, tokens_out=4)


def _decide(
    spec: Mapping[str, Any], budgets: Sequence[Budget], prior: Sequence[OperationCall]
) -> dict[str, Any]:
    with case_budgets(budgets), capture_operation_calls() as calls:
        calls.extend(prior)
        text = branch._decide(
            Request(
                path=branch.DECIDE_ROUTE,
                context=json.dumps({"after": ""}),
                intent=json.dumps(spec),
                params={"gate": "gate_1"},
            )
        )
    record: dict[str, Any] = json.loads(text)
    return record


_USD = [Budget(unit="usd", cap=0.05)]


@pytest.mark.parametrize(
    ("spent", "estimate", "refused"),
    [
        (0.01, 0.03, False),  # BU-3
        (0.02, 0.03, False),  # BU-17: spent + estimate == cap is allowed
        (0.03, 0.03, True),  # BU-4
        (0.049, None, False),  # BU-16: no estimate, cap not spent
        (0.05, None, True),  # BU-17: spent == cap with no estimate is refused
        (0.07, None, True),
    ],
)
def test_refuse_when_spent_plus_estimate_exceeds_cap(
    spent: float, estimate: float | None, refused: bool
) -> None:
    # BU#4
    spec = _spec(estimate=None if estimate is None else {"usd": estimate})
    record = _decide(spec, _USD, [_call("model_1", _usd(spent))])

    assert record["budget"] == [
        {
            "unit": "usd",
            "cap": 0.05,
            "spent": spent,
            "unpriced": 0,
            "estimate": estimate,
            "refused": refused,
        }
    ]
    assert record["wanted"] == "then"
    assert record["branch"] == (None if refused else "then")


@pytest.mark.parametrize(
    ("spent", "estimate", "refused"), [(60, 40, False), (60, 41, True), (100, None, True)]
)
def test_tokens_refuse_on_the_same_rule(spent: int, estimate: int | None, refused: bool) -> None:
    # BU#4 per unit: a tokens charge is tokens_in + tokens_out.
    spec = _spec(estimate=None if estimate is None else {"tokens": estimate}, unit="tokens")
    signals = SignalAccounting(cost_usd=0.001, tokens_in=spent - 10, tokens_out=10)
    record = _decide(spec, [Budget(unit="tokens", cap=100)], [_call("model_1", signals)])

    assert record["budget"][0] | {"spent": spent} == record["budget"][0]
    assert record["budget"][0]["refused"] is refused


@pytest.mark.parametrize("word", ["abstain", "fail_closed"])
def test_refused_input_gate_never_falls_back_to_a_word(word: str) -> None:
    # BU#5 / BU-5, BU-10: an input gate has no current answer, and a word is none: no branch
    # runs, so a refusal never fails the Case closed nor reads as gate_not_met.
    spec = _spec(estimate={"usd": 0.03}, otherwise=word)
    record = _decide(spec, _USD, [_call("model_1", _usd(0.03))])

    assert (record["wanted"], record["branch"]) == ("then", None)
    assert [(e["branch"], e["reason"]) for e in record["not_run"]] == [
        ("then", "budget_refused"),
        ("otherwise", "not_selected"),
    ]


def test_refused_branch_with_a_calling_other_branch_runs_no_branch() -> None:
    # BU#5 / BU-5: both branches call: neither runs.
    spec = _spec(estimate={"usd": 0.03}, otherwise="recipe")
    record = _decide(spec, _USD, [_call("model_1", _usd(0.03))])

    assert (record["wanted"], record["branch"]) == ("then", None)
    assert [(e["branch"], e["reason"]) for e in record["not_run"]] == [
        ("then", "budget_refused"),
        ("otherwise", "not_selected"),
    ]


def test_spent_folds_only_listed_ancestors() -> None:
    # BU#7 / BU-7, BU-19: a recorded call that is not an ancestor (a sibling) never enters spent.
    prior = [_call(name, _usd(0.01)) for name in ("model_1", "model_2", "model_3")]
    record = _decide(_spec(ancestors=("model_1", "model_3")), _USD, prior)

    assert record["budget"][0]["spent"] == 0.02


def test_either_unit_refuses() -> None:
    # BU#8 / BU-2: usd allows the estimate, tokens refuse it: the branch is refused.
    spec = _spec(estimate={"usd": 0.001, "tokens": 100})
    budgets = [Budget(unit="usd", cap=0.05), Budget(unit="tokens", cap=50)]
    record = _decide(spec, budgets, [_call("model_1", _usd(0.001))])

    assert [(view["unit"], view["refused"]) for view in record["budget"]] == [
        ("usd", False),
        ("tokens", True),
    ]
    assert record["branch"] is None


def test_ancestor_without_record_charges_nothing() -> None:
    # BU#21 / BU-20: no record = no charge, not unpriced; a record with no numbers is unpriced.
    spec = _spec(ancestors=("model_1", "model_2", "model_3"))
    prior = [_call("model_1", _usd(0.01)), _call("model_2", None)]
    record = _decide(spec, _USD, prior)

    assert (record["budget"][0]["spent"], record["budget"][0]["unpriced"]) == (0.01, 1)


def test_fold_is_one_pass_over_256_ancestors(monkeypatch: pytest.MonkeyPatch) -> None:
    # BU#28 / BU-26: one index of the recorded calls for every unit, never one scan per ancestor.
    names = [f"model_{index}" for index in range(1, 257)]
    passes: list[int] = []
    index = branch.provider_calls_by_fingerprint

    def counted(calls: Any) -> Any:
        passes.append(1)
        return index(calls)

    monkeypatch.setattr(branch, "provider_calls_by_fingerprint", counted)
    budgets = [Budget(unit="usd", cap=1.0), Budget(unit="tokens", cap=10_000)]
    record = _decide(_spec(ancestors=names), budgets, [_call(n, _usd(0.001)) for n in names])

    assert len(passes) == 1
    assert [view["spent"] for view in record["budget"]] == [0.256, 256 * 14]


# --- integration: compiled candidates on the fake gateway --------------------------------------


@pytest.mark.asyncio
async def test_refused_with_no_current_answer_abstains_budget_refused() -> None:
    # BU#6 / BU-5: prep spends 0.001; then (estimate 0.03) is refused and otherwise also calls.
    gateway = Gateway({"prov/prep": "P", "prov/big": "B", "prov/small": "S"})
    record = await run_gate(fixture("budget_refuse_both.url4"), gateway)

    assert [request["model"] for request in gateway.seen] == ["prov/prep"]
    assert (record["output"], record.get("abstained")) == ("", True)
    decision = _decisions(record)["op_gate_1"]
    assert (decision["wanted"], decision["branch"]) == ("then", None)
    assert [(e["branch"], e["reason"]) for e in decision["not_run"]] == [
        ("then", "budget_refused"),
        ("otherwise", "not_selected"),
    ]
    assert decision["result"] == {"status": "abstain", "reason": "budget_refused"}


@pytest.mark.asyncio
async def test_replay_from_cache_gives_identical_budget_views() -> None:
    # BU#9 / BU-8: a cache hit is charged its reference cost, so replay takes the same branches.
    live = _priced(_CASCADE)
    replay = _priced(_CASCADE, cache="hit")
    captured = await run_gate(fixture("budget_cascade.url4"), live)
    replayed = await run_gate(fixture("budget_cascade.url4"), replay)

    assert _decisions(replayed) == _decisions(captured)
    assert [r["model"] for r in replay.seen] == [r["model"] for r in live.seen]
    assert _decisions(captured)["op_gate_1"]["budget"][0]["spent"] == 0.002


@pytest.mark.asyncio
async def test_unknown_usd_counts_zero_and_is_counted_unpriced() -> None:
    # BU#10 / BU-9 (usd): the decision proceeds; each priceless ancestor is one unpriced call.
    gateway = _priced(_CASCADE, drop=("usd",))
    record = await run_gate(fixture("budget_cascade.url4"), gateway)

    views = {key: d["budget"][0] for key, d in _decisions(record).items()}
    assert (views["op_gate_1"]["spent"], views["op_gate_1"]["unpriced"]) == (0.0, 2)
    assert (views["op_gate_2"]["spent"], views["op_gate_2"]["unpriced"]) == (0.0, 4)
    assert record["output"] == "L"


@pytest.mark.asyncio
async def test_unknown_tokens_count_zero_and_are_counted_unpriced() -> None:
    # BU#10 / BU-9 (tokens): a reply with no usage leaves tokens unknown.
    gateway = _priced({"prov/prep": "P", "prov/big": "B"}, drop=("usd", "usage"))
    record = await run_gate(fixture("budget_two_units.url4"), gateway)

    views = {view["unit"]: view for view in _decisions(record)["op_gate_1"]["budget"]}
    assert (views["tokens"]["spent"], views["tokens"]["unpriced"]) == (0, 1)
    assert (views["usd"]["spent"], views["usd"]["unpriced"]) == (0.0, 1)


@pytest.mark.asyncio
async def test_mandatory_stage_over_cap_runs_and_is_reported() -> None:
    # BU#11 / BU-10: stage 1 spends 0.002 over a 0.001 cap; it runs in full, the escalation is
    # refused, and the kept step slot's abstain is the Gate's result (never "" answered).
    gateway = Gateway({"prov/a": "A", "prov/b": "B", "prov/large": "L"})
    record = await run_gate(fixture("budget_cascade_tight.url4"), gateway)

    assert record["status"] == "completed"
    assert sorted(request["model"] for request in gateway.seen) == ["prov/a", "prov/b"]
    decision = _decisions(record)["op_gate_1"]
    assert decision["budget"] == [
        {"unit": "usd", "cap": 0.001, "spent": 0.002, "unpriced": 0, "estimate": None,
         "refused": True}
    ]  # fmt: skip
    assert (decision["wanted"], decision["branch"]) == ("otherwise", "then")
    assert decision["result"] == {"status": "abstain", "reason": "gate_not_met"}
    assert record.get("abstained") is True


@pytest.mark.asyncio
async def test_kept_answer_is_the_result_when_the_escalation_is_refused() -> None:
    # BU#11 / BU-4: stage 1 agrees, so it answers under a spent cap; nothing is refused.
    gateway = Gateway({"prov/a": "A", "prov/b": "A", "prov/large": "L"})
    record = await run_gate(fixture("budget_cascade_tight.url4"), gateway)

    assert record["output"] == "A"
    assert _decisions(record)["op_gate_1"]["budget"][0]["refused"] is False


@pytest.mark.asyncio
async def test_engine_binds_candidate_budget_once_per_case() -> None:
    # BU#13 / BU-1: the cap reaches DECIDE from the candidate's _sf_budget source.
    assert candidate_budgets(fixture("budget_two_units.url4")) == (
        Budget(unit="usd", cap=0.05),
        Budget(unit="tokens", cap=50),
    )
    record = await run_gate(fixture("budget_choice.url4"), Gateway({"prov/big": "B"}))
    assert _decisions(record)["op_gate_1"]["budget"][0]["cap"] == 0.05
    assert current_case_budgets() == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "model"), [("budget_choice.url4", "prov/big")])
async def test_budget_remaining_is_observed_in_an_input_gate(name: str, model: str) -> None:
    # BU#14 / BU-6: nothing spent yet, so remaining is the cap and the large model fits.
    gateway = Gateway({"prov/big": "B", "prov/small": "S"})
    record = await run_gate(fixture(name), gateway)

    decision = _decisions(record)["op_gate_1"]
    assert decision["when"] == {"observe": "budget.remaining:usd", "cmp": ">=", "value": 0.02}
    assert (decision["observed"], decision["passed"], decision["branch"]) == (0.05, True, "then")
    assert [request["model"] for request in gateway.seen] == [model]


@pytest.mark.asyncio
async def test_tokens_only_cap_refuses_an_estimate_over_the_cap() -> None:
    # BU#14 / BU-2 (tokens only): estimate 100 > cap 50, and the other branch also calls.
    gateway = Gateway({"prov/big": "B", "prov/small": "S"})
    record = await run_gate(fixture("budget_tokens.url4"), gateway)

    assert gateway.seen == []
    decision = _decisions(record)["op_gate_1"]
    assert (
        decision["budget"][0] | {"unit": "tokens", "estimate": 100, "refused": True}
        == (decision["budget"][0])
    )
    assert decision["result"] == {"status": "abstain", "reason": "budget_refused"}


@pytest.mark.asyncio
async def test_two_units_refuse_when_tokens_refuse() -> None:
    # BU#14 / BU-2: usd allows (0.001 + 0.001 <= 0.05), tokens refuse (14 + 100 > 50).
    gateway = Gateway({"prov/prep": "P", "prov/big": "B"})
    record = await run_gate(fixture("budget_two_units.url4"), gateway)

    decision = _decisions(record)["op_gate_1"]
    assert [(v["unit"], v["spent"], v["refused"]) for v in decision["budget"]] == [
        ("usd", 0.001, False),
        ("tokens", 14, True),
    ]
    assert gateway.calls("prov/big") == 0


@pytest.mark.asyncio
async def test_step_fallback_is_checked_as_an_optional_call() -> None:
    # BU#15 / BU-18: the judge fallback is refused (0.003 + 0.01 > 0.005); no judge call.
    gateway = Gateway(
        {"prov/alpha": "A", "prov/beta": "A", "prov/gamma": "B", "prov/judge": "member_3"}
    )
    record = await run_gate(fixture("budget_lazy_judge.url4"), gateway)

    assert gateway.calls("prov/judge") == 0
    decision = _decisions(record)["op_gate_1"]
    assert decision["budget"] == [
        {"unit": "usd", "cap": 0.005, "spent": 0.003, "unpriced": 0, "estimate": 0.01,
         "refused": True}
    ]  # fmt: skip
    assert (decision["wanted"], decision["branch"]) == ("otherwise", "then")
    assert decision["not_run"][0]["reason"] == "budget_refused"


@pytest.mark.asyncio
async def test_refused_step_fallback_answers_with_the_majority() -> None:
    # BU#15 / BU-18: the majority branch (a Vote, no call) is the current answer.
    gateway = Gateway(
        {"prov/alpha": "A", "prov/beta": "A", "prov/gamma": "B", "prov/judge": "member_3"}
    )
    record = await run_gate(fixture("budget_lazy_judge.url4"), gateway)

    assert record["output"] == "A"
    assert _decisions(record)["op_gate_1"]["result"] == {"status": "answered", "reason": None}


@pytest.mark.asyncio
async def test_parallel_skip_members_can_jointly_pass_the_cap() -> None:
    # BU#16 / BU-19 (ans:Q20): each member counts only its own ancestors (none): all three run,
    # 3 x 0.001 > 0.0015. The report shows the overspend.
    gateway = Gateway({"prov/a": "X", "prov/b": "X", "prov/c": "X"})
    record = await run_gate(fixture("budget_skip_members.url4"), gateway, "a b c")

    assert sorted(request["model"] for request in gateway.seen) == ["prov/a", "prov/b", "prov/c"]
    views = [d["budget"][0] for d in _decisions(record).values()]
    assert len(views) == 3
    assert all((v["spent"], v["refused"]) == (0.0, False) for v in views)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "gate_1_after:0.0:",
            "gate_1_after:0.0:usd=0.01:",
            "a candidate budget sits only on the candidate's _sf_budget source",
        ),
        pytest.param(
            "model_1:0.0:/prov/big",
            "model_1:0.0:usd=0.01:/prov/big",
            "a candidate budget sits only on the candidate's _sf_budget source",
            id="inside-a-branch-body",
        ),
        ("usd=0.05:'budget'", "influence=0.05:'budget'", "unknown key 'influence'"),
        ("usd=0.05:'budget'", "usd=0:'budget'", "the candidate budget usd is not a valid cap"),
    ],
)
async def test_engine_refuses_budget_on_inner_source_or_unknown_key(
    old: str, new: str, message: str
) -> None:
    # BU#17 / BU-15: a permanent benchmark_definition_error before any call.
    edited = fixture("budget_choice.url4").replace(old, new, 1)
    assert edited != fixture("budget_choice.url4")
    with pytest.raises(ResolutionError) as caught:
        candidate_budgets(edited)
    assert caught.value.code == "benchmark_definition_error"
    assert message in str(caught.value)
    gateway = Gateway({"prov/big": "B", "prov/small": "S"})
    with pytest.raises(ResolutionError) as ran:
        await run_gate(edited, gateway)
    assert (ran.value.code, gateway.seen) == ("benchmark_definition_error", [])


@pytest.mark.asyncio
async def test_nested_decisions_see_growing_spend() -> None:
    # BU#23 / BU-22: stage 2's spent holds stage 1 too; its remaining is never larger.
    gateway = Gateway(_CASCADE)
    record = await run_gate(fixture("budget_cascade.url4"), gateway)

    first, second = (_decisions(record)[key]["budget"][0] for key in ("op_gate_1", "op_gate_2"))
    assert (first["spent"], second["spent"]) == (0.002, 0.004)
    assert first["estimate"] == 0.0025
    assert record["output"] == "L"


@pytest.mark.asyncio
async def test_each_attempt_starts_with_the_full_cap() -> None:
    # BU#25 / BU-28: two Attempts of one Case see the same spend; one never reduces the other.
    first = await run_gate(fixture("budget_cascade.url4"), Gateway(_CASCADE))
    second = await run_gate(fixture("budget_cascade.url4"), Gateway(_CASCADE))
    assert _decisions(first) == _decisions(second)

    outer, inner = [Budget(unit="usd", cap=0.05)], [Budget(unit="usd", cap=0.01)]
    with case_budgets(outer):
        with case_budgets(inner):
            assert current_case_budgets() == tuple(inner)
        assert current_case_budgets() == tuple(outer)
    assert current_case_budgets() == ()


def test_budget_stage_gains_selector() -> None:
    # BU#22 / BU-21 (PIN: the screamingface.budget.v1 freeze snapshot): a LabelModel selector call
    # is charged with stage selector, on the Engine record and in its schema.
    assert get_args(BudgetStage) == ("model", "synthesis", "judge", "writer", "selector")
    charge = BudgetCharge(
        operation_id="op_model_1",
        member_id=None,
        stage="selector",
        amount=0.001,
        source="live",
        remaining_after=0.049,
    )
    assert charge.stage == "selector"
    stages = budget_schemas()["BudgetCharge"]["properties"]["stage"]["enum"]
    assert stages[-1] == "selector"
