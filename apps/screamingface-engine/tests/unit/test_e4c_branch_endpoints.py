"""The sf.Gate branch endpoints: DECIDE writes one record, OPEN gates, JOIN copies the result.

FEATURE: E4c (OME-1291) branch-core rows BC#3, #4, #5, #6, #9, #20, #24, #31, #32, #37, #39.
STORY: as the compiled Gate, I send DECIDE its spec and inputs and get one gate-decision record;
OPEN gives a one-item collection only for the chosen branch; JOIN gives back the taken branch's
text verbatim and copies how that branch ended, so an abstain deep inside still marks the Case.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

import pytest
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.combine.evidence import GateRecord
from screamingface_engine.operation_calls import (
    OperationCall,
    capture_operation_calls,
    record_combine_call,
    record_operation_call,
    record_pending_combine_call,
)
from screamingface_engine.world import branch
from url4.core.errors import ResolutionError
from url4.peer.server import Request

_SHA = "0123456789abcdef"
_SUMMARY = {"chars": 12, "sha256": _SHA}


def _spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "schema": "screamingface.gate-spec.v1",
        "kind": "input",
        "when": {"observe": "label:sel_1", "cmp": "eq", "value": "math"},
        "then": "recipe",
        "otherwise": "recipe",
        "panel": None,
        "calls": {"then": {"min": 3, "max": 3}, "otherwise": {"min": 1, "max": 2}},
        "selectors": {
            "sel_1": {
                "kind": "keywords",
                "multi": False,
                "labels": ["math", "code"],
                "binding": None,
                "rules": [
                    {"label": "math", "pattern": "math"},
                    {"label": "code", "pattern": "code"},
                ],
            }
        },
        "reads": {"then": [], "otherwise": []},
        "estimate": {"then": None, "otherwise": None},
        "ancestors": [],
        "terminal": {"then": "model_1", "otherwise": "model_2"},
    }
    spec.update(overrides)
    return spec


def _keywords(**results: list[str]) -> str:
    return json.dumps(
        {
            "summary": _SUMMARY,
            **{key: {"labels": value, "matched": value} for key, value in results.items()},
        }
    )


def _decide(
    spec: Mapping[str, Any],
    *,
    keywords: str | None = None,
    selectors: Mapping[str, str] | None = None,
    gate: str = "gate_1",
    extra: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[OperationCall]]:
    context: dict[str, Any] = {"after": ""}
    if keywords is not None:
        context["keywords"] = keywords
    if selectors is not None:
        context["selectors"] = dict(selectors)
    context.update(extra or {})
    with capture_operation_calls() as calls:
        text = branch._decide(
            Request(
                path=branch.DECIDE_ROUTE,
                context=json.dumps(context),
                intent=json.dumps(spec),
                params={"gate": gate},
            )
        )
    return json.loads(text), list(calls)


def _join(
    spec: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    then: list[str] | None = None,
    otherwise: list[str] | None = None,
    prior: tuple[OperationCall, ...] = (),
) -> tuple[str, dict[str, Any] | None, Exception | None]:
    context: dict[str, Any] = {"decision": json.dumps(record)}
    if then is not None:
        context["then"] = json.dumps(then)
    if otherwise is not None:
        context["otherwise"] = json.dumps(otherwise)
    request = Request(
        path=branch.JOIN_ROUTE,
        context=json.dumps(context),
        intent=json.dumps(spec),
        params={"binding": record["gate_id"]},
    )
    with capture_operation_calls() as calls:
        calls.extend(prior)
        try:
            text, error = branch._join(request), None
        except ResolutionError as exc:
            text, error = "", exc
    joined = [call.decision for call in calls if call.decision is not None]
    published = None if not joined else joined[-1].model_dump(mode="json", by_alias=True)
    return text, published, error


def _model_call(binding: str, output: str) -> OperationCall:
    return OperationCall("/prov/m", (("binding", binding),), output, "stop", None)


# --- OPEN (BC#3) ---------------------------------------------------------------------------------


@pytest.mark.parametrize("taken", ["then", "otherwise"])
@pytest.mark.parametrize("intent", ["then", "otherwise"])
def test_open_returns_one_item_only_for_the_taken_branch(taken: str, intent: str) -> None:
    record, _ = _decide(_spec(), keywords=_keywords(sel_1=["math"] if taken == "then" else []))
    reply = branch._open(
        Request(path=branch.OPEN_ROUTE, context=json.dumps(record), intent=intent, params={})
    )
    assert json.loads(reply) == ([{}] if intent == taken else [])


def test_open_refuses_an_unknown_intent_and_a_non_record() -> None:
    record, _ = _decide(_spec(), keywords=_keywords(sel_1=["math"]))
    with pytest.raises(ResolutionError, match="open intent"):
        branch._open(
            Request(path=branch.OPEN_ROUTE, context=json.dumps(record), intent="both", params={})
        )
    with pytest.raises(ResolutionError) as caught:
        branch._open(
            Request(
                path=branch.OPEN_ROUTE,
                context='{"gate_id": "secret value"}',
                intent="then",
                params={},
            )
        )
    assert caught.value.code == "benchmark_contract_error"
    assert "secret value" not in str(caught.value)


# --- DECIDE (BC#4, #24, #32) ---------------------------------------------------------------------


def test_decide_writes_one_record_with_every_field() -> None:
    record, calls = _decide(_spec(), keywords=_keywords(sel_1=["math"]))

    assert record == {
        "schema": "screamingface.gate-decision.v1",
        "gate_id": "gate_1",
        "kind": "input",
        "when": {"observe": "label:sel_1", "cmp": "eq", "value": "math"},
        "observed": "math",
        "passed": True,
        "wanted": "then",
        "branch": "then",
        "selectors": [
            {
                "id": "sel_1",
                "kind": "keywords",
                "status": "computed",
                "labels": ["math"],
                "parse": "ok",
                "raw": None,
                "parse_error": None,
                "input_chars": 12,
                "input_sha256": _SHA,
            }
        ],
        "not_run": [
            {"branch": "otherwise", "reason": "not_selected", "model_calls": {"min": 1, "max": 2}}
        ],
        "budget": None,
        "result": None,
        "panel": None,
    }
    # D3: published once, under the JOIN fingerprint, with DECIDE's record (result unset).
    assert [(call.path, call.params) for call in calls] == [
        (branch.JOIN_ROUTE, (("binding", "gate_1"),))
    ]
    assert calls[0].decision is not None and calls[0].decision.result is None


@pytest.mark.parametrize(
    ("label", "cmp", "labels", "passed"),
    [
        ("math", "eq", ["math"], True),
        ("math", "eq", [], False),
        ("math", "ne", ["code"], True),
        ("math", "ne", [], True),  # a null label is "not math" (SL-15)
        ("math", "ne", ["math"], False),
    ],
)
def test_label_conditions_compare_the_first_label(label, cmp, labels, passed) -> None:
    spec = _spec(when={"observe": "label:sel_1", "cmp": cmp, "value": label})
    record, _ = _decide(spec, keywords=_keywords(sel_1=labels))
    assert record["passed"] is passed
    assert record["branch"] == ("then" if passed else "otherwise")


@pytest.mark.parametrize(
    ("when", "labels", "passed"),
    [
        ({"observe": "labels:sel_1", "cmp": "has", "value": "code"}, ["math", "code"], True),
        ({"observe": "labels:sel_1", "cmp": "has", "value": "code"}, ["math"], False),
        ({"observe": "labels:sel_1", "cmp": "empty", "value": None}, [], True),
        ({"observe": "labels:sel_1", "cmp": "empty", "value": None}, ["math"], False),
    ],
)
def test_label_set_conditions(when, labels, passed) -> None:
    spec = _spec(
        when=when,
        selectors={
            "sel_1": {
                "kind": "keywords",
                "multi": True,
                "labels": ["math", "code"],
                "binding": None,
                "rules": [
                    {"label": "math", "pattern": "math"},
                    {"label": "code", "pattern": "code"},
                ],
            }
        },
    )
    record, _ = _decide(spec, keywords=_keywords(sel_1=labels))
    assert (record["observed"], record["passed"]) == (labels, passed)


def _label_model_spec(**overrides: Any) -> dict[str, Any]:
    return _spec(
        selectors={
            "sel_1": {
                "kind": "label_model",
                "multi": False,
                "labels": ["math", "code"],
                "binding": "selector_1",
            }
        },
        **overrides,
    )


@pytest.mark.parametrize(
    ("reply", "status", "labels", "parse", "raw", "passed"),
    [
        ("Math.", "computed", ["math"], "ok", None, True),
        ("physics", "computed", [], "unrecognized", "physics", False),
        ("   ", "computed", [], "unparsed", None, False),
        ("$selector_1", "failed", None, None, None, False),
    ],
)
def test_label_model_reply_parses_into_the_selector_record(
    reply, status, labels, parse, raw, passed
) -> None:
    record, _ = _decide(_label_model_spec(), keywords=_keywords(), selectors={"sel_1": reply})
    selector = record["selectors"][0]
    assert (selector["status"], selector["labels"], selector["parse"], selector["raw"]) == (
        status,
        labels,
        parse,
        raw,
    )
    assert selector["parse_error"] is None
    assert record["passed"] is passed


def test_a_not_run_body_lists_its_selectors_keywords_computed_label_model_not_run() -> None:
    # GU-5 / SL-16 / SL-17: the otherwise body (not run) reads a Keywords and a LabelModel selector.
    spec = _spec(
        selectors={
            "sel_1": {
                "kind": "keywords",
                "multi": False,
                "labels": ["jailbreak"],
                "binding": None,
                "rules": [{"label": "jailbreak", "pattern": "ignore"}],
            },
            "sel_2": {
                "kind": "keywords",
                "multi": False,
                "labels": ["math"],
                "binding": None,
                "rules": [{"label": "math", "pattern": "integral"}],
            },
            "sel_3": {
                "kind": "label_model",
                "multi": False,
                "labels": ["safe", "unsafe"],
                "binding": "selector_1",
            },
        },
        when={"observe": "label:sel_1", "cmp": "eq", "value": "jailbreak"},
        then="fail_closed",
        calls={"then": {"min": 0, "max": 0}, "otherwise": {"min": 2, "max": 4}},
        reads={"then": [], "otherwise": ["sel_3", "sel_2"]},
        terminal={"then": None, "otherwise": "gate_2"},
    )
    record, _ = _decide(spec, keywords=_keywords(sel_1=["jailbreak"], sel_2=["math"]))

    assert [(s["id"], s["status"], s["labels"]) for s in record["selectors"]] == [
        ("sel_1", "computed", ["jailbreak"]),
        ("sel_3", "not_run", None),
        ("sel_2", "computed", ["math"]),
    ]


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"extra": {"surprise": "x"}}, "'surprise'"),
        ({"spec_patch": {"schema": "screamingface.gate-spec.v9"}}, "schema"),
        ({"spec_patch": {"when": {"observe": "label:sel_1", "cmp": ">=", "value": 1}}}, "when"),
        ({"spec_patch": {"reads": {"then": ["sel_9"], "otherwise": []}}}, "the root"),
        ({"keywords": None}, "keywords"),
    ],
)
def test_decide_refuses_malformed_context_without_echo(change, field) -> None:
    spec = {**_spec(), **change.get("spec_patch", {})}
    keywords = change["keywords"] if "keywords" in change else _keywords(sel_1=["math"])
    with pytest.raises(ResolutionError) as caught:
        _decide(spec, keywords=keywords, extra=change.get("extra"))
    assert caught.value.code == "benchmark_contract_error"
    assert caught.value.permanent is True
    assert field in str(caught.value)
    assert "math" not in str(caught.value)


def test_decide_refuses_a_context_over_1_mib() -> None:
    # BC-22
    with pytest.raises(ResolutionError, match="1 MiB"):
        _decide(_spec(), keywords=_keywords(sel_1=["math"]), extra={"after": "x" * (1024 * 1024)})


def test_decide_context_stays_under_the_cap_with_8_mib_ancestor_answers() -> None:
    # BC-34 (#32): the answers sit behind AFTER (which returns ""), so DECIDE's context holds only
    # ids, labels and numbers, whatever the ancestors answered.
    huge = "a" * (8 * 1024 * 1024)
    assert (
        branch._after(Request(path=branch.AFTER_ROUTE, context=huge, intent="after", params={}))
        == ""
    )
    spec = _spec()
    context = json.dumps({"after": "", "keywords": _keywords(sel_1=["math"])})
    assert len(context.encode()) < 1024 * 1024
    record, _ = _decide(spec, keywords=_keywords(sel_1=["math"]))
    assert record["branch"] == "then"


# --- panel gates (BC#9, #31) ----------------------------------------------------------------------


def _vote(member_count: int = 3, **overrides: Any) -> dict[str, Any]:
    return vote_spec(
        member_count,
        extract={"op": "last_line@1", "args": {}},
        normalize={"op": "text@1", "args": {}},
        reduce={"op": "mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
        **overrides,
    )


def _decision_call(texts: list[str], gate: Mapping[str, Any]) -> OperationCall:
    outcome = run(
        spec_text({**_vote(), "gate": dict(gate)}), context_text(texts), registry=BUILTIN_OPERATORS
    )
    assert outcome.evidence is not None
    with capture_operation_calls() as calls:
        record_combine_call(
            COMBINE_ROUTE, {"binding": "synthesis_1"}, outcome.output, outcome.evidence
        )
    return calls[0]


def _panel_spec(otherwise: str, *, then: str = "step", band: bool = False) -> dict[str, Any]:
    return _spec(
        kind="panel",
        when={"observe": "agreement", "cmp": ">=", "value": 0.7},
        then=then,
        otherwise=otherwise,
        panel={"binding": "synthesis_1"},
        selectors={},
        calls={
            "then": {"min": 0, "max": 0} if then == "step" else {"min": 2, "max": 2},
            "otherwise": {"min": 1, "max": 1}
            if otherwise in ("recipe", "step")
            else {"min": 0, "max": 0},
        },
        terminal={
            "then": "synthesis_1" if then == "step" else "model_4",
            "otherwise": {"recipe": "model_5", "step": "synthesis_2"}.get(otherwise),
        },
    )


_AGREE = ["A", "A", "A"]
_SPLIT = ["A", "B", "C"]
_NONE = ["", "", ""]


@pytest.mark.parametrize(
    ("texts", "otherwise", "band", "wanted", "result"),
    [
        (_AGREE, "recipe", False, "then", {"status": "answered", "reason": None}),
        (_SPLIT, "recipe", False, "otherwise", {"status": "answered", "reason": None}),
        # 2026-11-12: no voters is an abstain, not an escalation: the Case abstains no_votes.
        (_NONE, "recipe", False, None, {"status": "abstain", "reason": "no_votes"}),
        (_NONE, "abstain", False, None, {"status": "abstain", "reason": "no_votes"}),
        (_NONE, "fail_closed", False, None, {"status": "fail_closed", "reason": None}),
        (_SPLIT, "abstain", False, "otherwise", {"status": "abstain", "reason": "gate_not_met"}),
        (["A", "A", "B"], "recipe", True, None, {"status": "abstain", "reason": "in_band"}),
    ],
    ids=[
        "majority",
        "fallback",
        "no_votes_recipe",
        "no_votes_word",
        "no_votes_fail_closed",
        "fallback_word",
        "band",
    ],
)
def test_panel_branch_rule(texts, otherwise, band, wanted, result) -> None:
    # BC#9 (D4): the decision call's gate record branch maps to the Gate's branch.
    gate = {"observe": "agreement", "cmp": ">=", "threshold": 0.7, "otherwise": "abstain"}
    if band:
        gate["abstain_band"] = [0.5, 0.7]
    decision_call = _decision_call(texts, gate)
    spec = _panel_spec(otherwise, then="recipe")
    with capture_operation_calls() as calls:
        calls.append(decision_call)
        text = branch._decide(
            Request(
                path=branch.DECIDE_ROUTE,
                context=json.dumps({"after": ""}),
                intent=json.dumps(spec),
                params={"gate": "gate_1"},
            )
        )
    record = json.loads(text)
    assert record["wanted"] == wanted == record["branch"]
    assert record["panel"]["operation_id"] == "op_synthesis_1"
    prior = (decision_call, _model_call("model_4", "BIG"), _model_call("model_5", "LARGE"))
    rows = {
        "then": ["BIG"] if wanted == "then" else [],
        "otherwise": ["LARGE"] if wanted == "otherwise" else [],
    }
    if otherwise != "recipe":
        rows.pop("otherwise")
    _text, published, error = _join(spec, record, prior=prior, **rows)
    assert published is not None and published["result"] == result
    assert (error is not None) is (result["status"] == "fail_closed")


def test_decide_reads_a_pending_gate_record_from_the_recorded_calls() -> None:
    # BC-35 (#31): a phase=decide pending outcome carries the gate record on the call (D11).
    gate = GateRecord(
        observe="agreement",
        observed=0.34,
        cmp=">=",
        threshold=0.7,
        passed=False,
        branch="fallback",
        otherwise="judge",
    )
    spec = _panel_spec("step")
    with capture_operation_calls() as calls:
        record_pending_combine_call(
            COMBINE_ROUTE, {"binding": "synthesis_1", "phase": "decide"}, gate, "A"
        )
        text = branch._decide(
            Request(
                path=branch.DECIDE_ROUTE,
                context=json.dumps({"after": ""}),
                intent=json.dumps(spec),
                params={"gate": "gate_1"},
            )
        )
    record = json.loads(text)
    assert (record["observed"], record["passed"], record["branch"]) == (0.34, False, "otherwise")
    assert record["panel"] == {"operation_id": "op_synthesis_1", "branch": "fallback"}
    assert len(calls) == 2  # the pending call and DECIDE's record; nothing else kept


# --- JOIN (BC#5, #6, #20, #37) --------------------------------------------------------------------


def test_join_returns_the_taken_branch_text_and_its_terminal_result() -> None:
    answer = 'The answer is {"x": 1}\né line two'
    record, _ = _decide(_spec(), keywords=_keywords(sel_1=["math"]))
    text, published, error = _join(
        _spec(), record, then=[answer], otherwise=[], prior=(_model_call("model_1", answer),)
    )
    assert error is None
    assert text == answer
    assert published is not None and published["result"] == {"status": "answered", "reason": None}


def test_join_copies_the_decision_call_result_on_a_step_slot() -> None:
    # BC#6: a then step slot is the decision call's own reducer: JOIN gives its text and result.
    gate = {"observe": "agreement", "cmp": ">=", "threshold": 0.7, "otherwise": "abstain"}
    decision_call = _decision_call(_AGREE, gate)
    spec = _panel_spec("recipe")
    record = {
        **_decide(_spec(), keywords=_keywords(sel_1=["math"]))[0],
        "kind": "panel",
        "when": {"observe": "agreement", "cmp": ">=", "value": 0.7},
        "observed": 1.0,
        "selectors": [],
        "not_run": [
            {"branch": "otherwise", "reason": "not_selected", "model_calls": {"min": 1, "max": 1}}
        ],
        "panel": {"operation_id": "op_synthesis_1", "branch": "majority"},
    }
    text, published, _ = _join(spec, record, otherwise=[], prior=(decision_call,))
    assert text == "A"
    assert published is not None and published["result"] == {"status": "answered", "reason": None}


def test_recipe_body_ending_in_an_abstaining_vote_copies_the_abstain() -> None:
    # BC-37 (#6b, unit half): the then terminal is the body's own combine call, which abstained.
    outcome = run(spec_text(_vote()), context_text(["", "", ""]), registry=BUILTIN_OPERATORS)
    assert outcome.evidence is not None
    with capture_operation_calls() as recorded:
        record_combine_call(
            COMBINE_ROUTE, {"binding": "synthesis_3"}, outcome.output, outcome.evidence
        )
    spec = _spec(terminal={"then": "synthesis_3", "otherwise": "model_2"})
    record, _ = _decide(spec, keywords=_keywords(sel_1=["math"]))
    text, published, _ = _join(spec, record, then=[""], otherwise=[], prior=tuple(recorded))
    assert text == ""
    assert published is not None and published["result"] == {
        "status": "abstain",
        "reason": "no_votes",
    }


def test_an_inner_gate_result_reaches_the_outer_join() -> None:
    # BC-36 (unit half): the otherwise terminal is an inner Gate whose JOIN abstained.
    inner_spec = _spec(
        otherwise="abstain",
        calls={"then": {"min": 1, "max": 1}, "otherwise": {"min": 0, "max": 0}},
        terminal={"then": "model_3", "otherwise": None},
    )
    inner, _ = _decide(inner_spec, keywords=_keywords(sel_1=[]), gate="gate_2")
    _text, inner_record, _ = _join(inner_spec, inner, then=[])
    assert inner_record is not None and inner_record["result"] == {
        "status": "abstain",
        "reason": "gate_not_met",
    }
    with capture_operation_calls() as recorded:
        _join(inner_spec, inner, then=[])
    outer_spec = _spec(terminal={"then": "model_1", "otherwise": "gate_2"})
    outer, _ = _decide(outer_spec, keywords=_keywords(sel_1=[]))
    text, published, _ = _join(outer_spec, outer, then=[], otherwise=[""], prior=tuple(recorded))
    assert text == ""
    assert published is not None and published["result"] == {
        "status": "abstain",
        "reason": "gate_not_met",
    }


@pytest.mark.parametrize(
    ("word", "status", "reason"),
    [("abstain", "abstain", "gate_not_met"), ("fail_closed", "fail_closed", None)],
)
def test_words_end_the_gate(word, status, reason) -> None:
    # BC-8, BC-9: no iterate for a word; fail_closed raises after the record is published.
    spec = _spec(
        then=word,
        calls={"then": {"min": 0, "max": 0}, "otherwise": {"min": 1, "max": 1}},
        terminal={"then": None, "otherwise": "model_2"},
    )
    record, _ = _decide(spec, keywords=_keywords(sel_1=["math"]))
    text, published, error = _join(spec, record, otherwise=[])
    assert text == ""
    assert published is not None and published["result"] == {"status": status, "reason": reason}
    if word == "fail_closed":
        assert isinstance(error, ResolutionError)
        assert (error.code, error.permanent) == ("fail_closed", True)
        assert str(error) == "a guard refused the Case: sf.Gate gate_1 took fail_closed"
    else:
        assert error is None


def test_join_refuses_two_results() -> None:
    record, _ = _decide(_spec(), keywords=_keywords(sel_1=["math"]))
    _text, _published, error = _join(_spec(), record, then=["A"], otherwise=["B"])
    assert isinstance(error, ResolutionError)
    assert "a gate ran both branches" in str(error)


def test_two_sibling_gates_decide_independently() -> None:
    # BC-20: each DECIDE reads only its own context; the records share no state.
    first, _ = _decide(_spec(), keywords=_keywords(sel_1=["math"]), gate="gate_1")
    second, _ = _decide(_spec(), keywords=_keywords(sel_1=["code"]), gate="gate_2")
    assert (first["gate_id"], first["branch"]) == ("gate_1", "then")
    assert (second["gate_id"], second["branch"]) == ("gate_2", "otherwise")


# --- layering (BC#39) -----------------------------------------------------------------------------


def test_combine_package_never_imports_world() -> None:
    # C12: E/combine/* imports with screamingface_engine.world blocked.
    code = (
        "import sys, importlib, pkgutil\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[:2] == ['screamingface_engine', 'world']:\n"
        "            raise ImportError('blocked ' + name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "import screamingface_engine.combine as c\n"
        "for m in pkgutil.walk_packages(c.__path__, 'screamingface_engine.combine.'):\n"
        "    importlib.import_module(m.name)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr[-2000:]


def test_record_operation_call_is_not_a_join_claimant() -> None:
    # A model call never carries a decision: only record_gate_call writes one.
    with capture_operation_calls() as calls:
        record_operation_call("x", "stop")
    assert all(call.decision is None for call in calls)
