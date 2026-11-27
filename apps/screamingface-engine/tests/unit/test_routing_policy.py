"""The pure routing policy, version 1: every row of contracts C6 (Unit 5.2).

FEATURE: Router Recipe extension. One pure decision serves the Router DAG (``router-policy``) and
named profiles (``unique-argmax-v1``). It never sorts, normalizes or invents scores, never promotes
a runner-up and never retries; a classifier failure never runs the default.

INVARIANT: the policy module imports no HTTP, url4, configuration or recorder module.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path
from types import ModuleType

import pytest

from screamingface_engine import router_decision, router_vocabulary
from screamingface_engine.world import routing_policy
from screamingface_engine.world.routing_policy import (
    ROUTER_EVIDENCE_INVALID,
    ROUTING_AMBIGUOUS,
    ROUTING_INVALID_SCORES,
    ClassifierFailure,
    Evidence,
    Parse,
    PolicyFailure,
    PolicyResult,
    PolicyRule,
    ScoringEvidence,
    SelectorEvidence,
    decide,
)

_LABELS = ("code", "general", "math")
_BEST = PolicyRule(kind="router-policy", match="best", select="one")
_EXACT_ONE = PolicyRule(kind="router-policy", match="exact", select="one")
_EXACT_ALL = PolicyRule(kind="router-policy", match="exact", select="all")
_ARGMAX = PolicyRule(kind="unique-argmax-v1")


def _scores(*pairs: tuple[str, object]) -> ScoringEvidence:
    return ScoringEvidence(model="laya/router", contract="classification-scores-v1", scores=pairs)


def _llm(labels: tuple[str, ...], unknown: tuple[str, ...], parse: Parse) -> SelectorEvidence:
    return SelectorEvidence(source="llm", labels=labels, unknown=unknown, parse=parse)


def _regex(labels: tuple[str, ...], parse: Parse) -> SelectorEvidence:
    return SelectorEvidence(source="regex", labels=labels, unknown=(), parse=parse)


def _run(rule: PolicyRule, evidence: Evidence, *, default: bool = False) -> PolicyResult:
    return decide(rule, evidence, labels=_LABELS, has_default=default)


def _failure(result: PolicyResult) -> PolicyFailure:
    assert result.outcome == "failed"
    assert result.failure is not None
    assert (result.reason, result.selected) == (None, ())
    return result.failure


@pytest.mark.parametrize("rule", [_BEST, _EXACT_ONE, _EXACT_ALL, _ARGMAX])
@pytest.mark.parametrize("default", [True, False])
def test_a_classifier_failure_fails_at_classify_and_never_runs_the_default(
    rule: PolicyRule, default: bool
) -> None:
    result = _run(
        rule, ClassifierFailure(code="aigateway_http_503", permanent=False), default=default
    )

    failure = _failure(result)
    assert (failure.phase, failure.code, failure.permanent) == (
        "classify",
        "aigateway_http_503",
        False,
    )
    assert result.unknown_labels == ()


@pytest.mark.parametrize(
    "evidence",
    [
        _scores(("code", 0.9), ("general", 0.1)),  # a candidate label missing
        _scores(("code", 0.9), ("general", 0.1), ("math", 0.2), ("code", 0.3)),  # duplicate
        _scores(("code", True), ("general", 0.1), ("math", 0.2)),  # boolean
        _scores(("code", math.nan), ("general", 0.1), ("math", 0.2)),
        _scores(("code", math.inf), ("general", 0.1), ("math", 0.2)),
        _scores(("code", 1.5), ("general", 0.1), ("math", 0.2)),
        _scores(("code", -0.1), ("general", 0.1), ("math", 0.2)),
        _scores(("code", "0.5"), ("general", 0.1), ("math", 0.2)),
        _scores(),
        _llm(("code",), (), "ok"),  # a selector's evidence under match="best"
    ],
)
def test_best_one_refuses_invalid_evidence(evidence: Evidence) -> None:
    result = _run(_BEST, evidence, default=True)

    failure = _failure(result)
    assert (failure.phase, failure.code, failure.permanent) == (
        "decide",
        ROUTER_EVIDENCE_INVALID,
        True,
    )


def test_best_one_selects_the_unique_maximum_on_a_candidate() -> None:
    result = _run(_BEST, _scores(("math", 0.2), ("code", 0.7), ("other", 0.5), ("general", 0.1)))

    assert (result.outcome, result.reason, result.selected) == ("selected", "unique_max", (0,))
    assert result.unknown_labels == ("other",)
    assert result.failure is None


@pytest.mark.parametrize(("default", "outcome"), [(True, "default"), (False, "no_selection")])
def test_best_one_unique_maximum_on_an_unknown_label(default: bool, outcome: str) -> None:
    evidence = _scores(("code", 0.2), ("bonus", 0.9), ("general", 0.1), ("math", 0.3))
    result = _run(_BEST, evidence, default=default)

    assert (result.outcome, result.reason, result.selected) == (outcome, "unknown_selected", ())
    assert result.unknown_labels == ("bonus",)


@pytest.mark.parametrize(("default", "outcome"), [(True, "default"), (False, "no_selection")])
def test_best_one_tie_at_the_maximum(default: bool, outcome: str) -> None:
    result = _run(_BEST, _scores(("code", 0.4), ("general", 0.4), ("math", 0.2)), default=default)

    assert (result.outcome, result.reason, result.selected) == (outcome, "tie", ())


def test_best_one_tie_with_an_unknown_label_is_a_tie() -> None:
    result = _run(_BEST, _scores(("code", 0.4), ("x", 0.4), ("general", 0.1), ("math", 0.1)))

    assert (result.outcome, result.reason, result.unknown_labels) == ("no_selection", "tie", ("x",))


def test_exact_one_ok_one_label() -> None:
    result = _run(_EXACT_ONE, _llm(("general",), (), "ok"), default=True)

    assert (result.outcome, result.reason, result.selected) == ("selected", "exact", (1,))


def test_exact_one_unrecognized_one_label_keeps_the_unknown() -> None:
    result = _run(_EXACT_ONE, _llm(("math",), ("poetry",), "unrecognized"))

    assert (result.outcome, result.reason, result.selected) == ("selected", "exact", (2,))
    assert result.unknown_labels == ("poetry",)


@pytest.mark.parametrize(("default", "outcome"), [(True, "default"), (False, "no_selection")])
def test_exact_one_more_than_one_label(default: bool, outcome: str) -> None:
    result = _run(_EXACT_ONE, _regex(("math", "code"), "ok"), default=default)

    assert (result.outcome, result.reason, result.selected) == (outcome, "multiple_selected", ())


def test_exact_all_selects_every_recognized_label_in_classifier_order() -> None:
    result = _run(_EXACT_ALL, _llm(("math", "code"), ("poetry",), "unrecognized"))

    assert (result.outcome, result.reason, result.selected) == ("selected", "exact", (2, 0))
    assert result.unknown_labels == ("poetry",)
    regex = _run(_EXACT_ALL, _regex(("general", "code"), "ok"))
    assert regex.selected == (1, 0)


@pytest.mark.parametrize(("default", "outcome"), [(True, "default"), (False, "no_selection")])
def test_exact_one_unrecognized_with_no_label(default: bool, outcome: str) -> None:
    result = _run(_EXACT_ONE, _llm((), ("poetry",), "unrecognized"), default=default)

    assert (result.outcome, result.reason) == (outcome, "unknown_selected")
    assert result.unknown_labels == ("poetry",)


@pytest.mark.parametrize(("default", "outcome"), [(True, "default"), (False, "no_selection")])
def test_exact_all_unrecognized_with_no_label(default: bool, outcome: str) -> None:
    result = _run(_EXACT_ALL, _llm((), ("poetry", "art"), "unrecognized"), default=default)

    assert (result.outcome, result.reason) == (outcome, "unknown_only")
    assert result.unknown_labels == ("poetry", "art")


@pytest.mark.parametrize("rule", [_EXACT_ONE, _EXACT_ALL])
@pytest.mark.parametrize(
    "evidence", [_regex((), "no_match"), _llm((), (), "unparsed")], ids=["no_match", "unparsed"]
)
@pytest.mark.parametrize(("default", "outcome"), [(True, "default"), (False, "no_selection")])
def test_exact_empty(
    rule: PolicyRule, evidence: SelectorEvidence, default: bool, outcome: str
) -> None:
    result = _run(rule, evidence, default=default)

    assert (result.outcome, result.reason, result.selected) == (outcome, "empty", ())


@pytest.mark.parametrize(
    "evidence",
    [
        _llm(("poetry",), (), "ok"),  # a recognized label with no candidate
        _llm(("code", "code"), (), "ok"),  # repeated
        _llm((), (), "ok"),  # ok names a label
        _llm(("code",), ("x",), "ok"),  # ok has no unknown
        _llm(("code",), (), "unrecognized"),  # unrecognized has an unknown
        _llm((), (), "no_match"),  # no_match is regex only
        _regex((), "unparsed"),  # unparsed is llm only
        _regex(("code",), "no_match"),  # no_match has no label
        _scores(("code", 1.0), ("general", 0.0), ("math", 0.0)),  # scores under exact
    ],
)
def test_exact_refuses_inconsistent_evidence(evidence: Evidence) -> None:
    result = _run(_EXACT_ONE, evidence, default=True)

    failure = _failure(result)
    assert (failure.phase, failure.code) == ("decide", ROUTER_EVIDENCE_INVALID)


def test_unique_argmax_selects_the_profile_route() -> None:
    result = _run(_ARGMAX, _scores(("general", 0.1), ("math", 0.6), ("code", 0.3)))

    assert (result.outcome, result.selected, result.failure) == ("selected", (2,), None)


def test_unique_argmax_tie_is_routing_ambiguous() -> None:
    result = _run(_ARGMAX, _scores(("general", 0.4), ("math", 0.4), ("code", 0.2)))

    assert _failure(result).code == ROUTING_AMBIGUOUS


@pytest.mark.parametrize(
    "evidence",
    [
        _scores(("general", 0.4), ("math", 0.6)),
        _scores(("general", 0.1), ("math", 0.6), ("code", 0.2), ("extra", 0.1)),
        _scores(("general", 0.5), ("math", 0.5), ("extra", 0.1)),  # mismatch wins over a tie
    ],
)
def test_unique_argmax_label_mismatch_is_routing_invalid_scores(evidence: ScoringEvidence) -> None:
    result = _run(_ARGMAX, evidence)

    assert _failure(result).code == ROUTING_INVALID_SCORES


def test_the_policy_never_reorders_or_rescales() -> None:
    evidence = _scores(("math", 0.30000000000000004), ("code", 0.3), ("general", 0.0))

    assert _run(_BEST, evidence).selected == (2,)


def _imports(module: ModuleType) -> set[str]:
    imported: set[str] = set()
    assert module.__file__ is not None
    for node in ast.walk(ast.parse(Path(module.__file__).read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


_VOCABULARY = {"screamingface_engine.router_decision", "screamingface_engine.router_vocabulary"}


def test_the_policy_module_is_pure() -> None:
    imported = _imports(routing_policy)
    engine = {name for name in imported if name.startswith("screamingface_engine")}

    # INVARIANT: the only Engine imports are the C5 vocabulary leaves, which reach no I/O either.
    assert engine <= _VOCABULARY
    assert {name.split(".")[0] for name in imported - engine} <= {
        "__future__",
        "dataclasses",
        "math",
        "typing",
        "collections",
    }
    forbidden = (
        "httpx",
        "url4",
        "screamingface_engine.operation_calls",
        "screamingface_engine.world",
    )
    for module in (routing_policy, router_decision, router_vocabulary):
        assert not [name for name in _imports(module) if name.startswith(forbidden)]
