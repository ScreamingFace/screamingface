"""The rebuild of a url4 as a chain of the new surface, and the chain repr (E4b surface unit 6).

FEATURE (rebuild-display §1, §2): ``screamingface._surface.rebuild.rebuild(url4)`` gives the chain
value a url4 describes and the code that builds it, with the steps named through the alias
``sf``. The rebuild reads today's url4 decode (one decode path) and converts today's values with
the inverse of the lowering table (lowering §2.2).
STORY: as a researcher, I take the url4 of a run and get back the ``Fanout >> ... >> Vote()`` code
I wrote, run it, and it compiles to the same url4.
INVARIANT defended (RB-1): the rebuilt value and the rebuilt code each compile to the same url4
bytes; a url4 that the new surface cannot express is refused with the "cannot rebuild" message.
RB-3: a chain repr joins its steps with ``>>``; a named or optional chain uses the explicit form;
a step shows only the arguments that differ from their defaults.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import COMBINE_CONTRACT
from _combine_flow_fixtures import flow_operators
from _fusion_doc_examples import EXAMPLES, compile_example
from test_narrow_contract_fixtures import FIXTURES
from test_surface_parity import _NEW_FORM, _NOTEBOOK, _STEPS

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.rebuild import rebuild

_EXAMPLES = {example.slug: example for example in EXAMPLES}
_ROUTES = ["prov/alpha", "prov/beta", "prov/gamma"]


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=flow_operators()).url4


def _executed(code: str) -> sf.Recipe:
    namespace: dict[str, object] = {"sf": sx}
    exec(code, namespace)  # the rebuilt code names every step through the alias sf
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Recipe)
    return candidate


def _round_trip(url4: str, compile_: Callable[[sf.Recipe], str]) -> None:
    rebuilt = rebuild(url4)

    assert rebuilt.python.startswith("candidate = ")
    assert compile_(rebuilt.value) == url4
    assert compile_(_executed(rebuilt.python)) == url4


# ---------------------------------------------------------------- RB-1: the parity rows


_ROWS: dict[str, Callable[[], sf.Recipe]] = {
    **{case: new for case, (new, _today) in _NOTEBOOK.items()},
    **{case: new for case, (new, _today) in _STEPS.items()},
}


@pytest.mark.parametrize("case", sorted(_ROWS))
def test_rb1_a_notebook_row_round_trips(case: str) -> None:
    _round_trip(_url4(_ROWS[case]()), _url4)


@pytest.mark.parametrize("slug", sorted(_NEW_FORM))
def test_rb1_a_doc_example_round_trips(slug: str) -> None:
    example = _EXAMPLES[slug]

    _round_trip(
        compile_example(example, _NEW_FORM[slug]()), lambda value: compile_example(example, value)
    )


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_rb1_a_narrow_fixture_round_trips(name: str) -> None:
    url4 = (COMBINE_CONTRACT / name).read_text(encoding="utf-8").removesuffix("\n")

    _round_trip(url4, _url4)


# The url4 pins every rule id, and the rebuild keeps the pins (rebuild-display §1): a vote over
# the default rule rebuilds as Vote(over="last_line@1", normalize="text@1").
_PINNED = {"over": "last_line@1", "normalize": "text@1"}
_JUDGED = ["prov/alpha", "prov/beta", "prov/gamma", "prov/delta"]
_REBUILT: dict[str, Callable[[], sf.Recipe]] = {
    "narrow_filter_mean_candidate.url4": FIXTURES["narrow_filter_mean_candidate.url4"],
    "narrow_rank_vote_candidate.url4": lambda: (
        sx.Fanout(_JUDGED)
        >> sx.Judge("prov/judge", rubric="Score each draft from 0 to 10.")
        >> sx.Rank(2, by="score:judge")
        >> sx.Vote(**_PINNED, weights="score:judge")
    ),
    "narrow_judge_rank_vote_candidate.url4": lambda: (
        sx.Fanout(_JUDGED)
        >> sx.Judge("prov/judge", rubric="Score each draft from 0 to 10.")
        >> sx.Rank(2, by="score:judge")
        >> sx.Vote(**_PINNED)
    ),
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_rb1_a_narrow_fixture_rebuilds_as_the_chain_it_was_compiled_from(name: str) -> None:
    url4 = (COMBINE_CONTRACT / name).read_text(encoding="utf-8").removesuffix("\n")

    assert rebuild(url4).value == _REBUILT[name]()


def test_rb1_the_code_names_the_steps_in_the_new_form() -> None:
    chain = (
        sx.Fanout(_ROUTES)
        >> sx.Judge("prov/judge", rubric="Score it.")
        >> sx.Rank(2, by="score:judge")
        >> sx.Vote(weights="score:judge")
    )

    assert rebuild(_url4(chain)).python == (
        "candidate = sf.Fanout(['prov/alpha', 'prov/beta', 'prov/gamma'])"
        " >> sf.Judge('prov/judge', rubric='Score it.')"
        " >> sf.Rank(2, by='score:judge')"
        " >> sf.Vote(over='last_line@1', normalize='text@1', weights='score:judge')"
    )


def test_rb1_a_gate_rebuilds_with_its_references() -> None:
    chain = sx.Fanout(_ROUTES, signals={"conf": sf.Verbalized("C: ([0-9]+)")}) >> sx.Gate(
        when=sx.signal("conf").mean() >= 3.0,
        then=sx.Vote(**_PINNED),
        otherwise=sx.Synthesize("prov/writer"),
        abstain_if=sx.signal("conf").mean().between(2.0, 4.0),
    )

    rebuilt = rebuild(_url4(chain))

    assert rebuilt.value == chain
    assert rebuilt.python == (
        "candidate = sf.Fanout(['prov/alpha', 'prov/beta', 'prov/gamma'], "
        "signals={'conf': sf.Verbalized('C: ([0-9]+)')}) >> sf.Gate(when=sf.signal('conf').mean() "
        ">= 3.0, then=sf.Vote(over='last_line@1', normalize='text@1'), "
        "otherwise=sf.Synthesize('prov/writer'), "
        "abstain_if=sf.signal('conf').mean().between(2.0, 4.0))"
    )


def test_rb1_an_optional_member_block_rebuilds_in_the_explicit_form() -> None:
    inner = sx.Pipeline([sx.Fanout(["prov/a", "prov/b"]), sx.Vote(**_PINNED)], optional=True)
    chain = sx.Fanout([inner, "prov/c"], quorum=1) >> sx.Vote(**_PINNED)

    rebuilt = rebuild(_url4(chain))

    assert rebuilt.value == chain
    assert (
        "sf.Pipeline([sf.Fanout(['prov/a', 'prov/b']), sf.Vote(over='last_line@1', "
        "normalize='text@1')], optional=True)"
    ) in rebuilt.python


def test_rb1_a_selection_and_its_writer_rebuild_as_one_block() -> None:
    chain = (
        sx.Fanout(_ROUTES)
        >> sx.Filter(where=sx.signal("cost_usd") < 1)
        >> sx.Rank(2, by="cost_usd", order="min")
        >> sx.Synthesize("prov/writer", prompt="Write it.")
    )

    rebuilt = rebuild(_url4(chain))

    assert rebuilt.value == chain
    assert rebuilt.python.endswith(
        " >> sf.Filter(where=sf.signal('cost_usd') < 1.0) >> sf.Rank(2, by='cost_usd', "
        "order='min') >> sf.Synthesize('prov/writer', prompt='Write it.')"
    )


def test_rb1_a_pinned_rule_rebuilds_as_its_rule_name() -> None:
    chain = sx.Fanout(_ROUTES) >> sx.Vote(over="json")

    # E2: the operator id json_object@1 rebuilds as the rule name, with its pin
    assert rebuild(_url4(chain)).python.endswith(" >> sf.Vote(over='json@1', normalize='text@1')")


@pytest.mark.parametrize(
    ("today", "name"),
    [
        (lambda: sf.Fusion(_ROUTES, synthesizer=sf.Pick("confidence", order="max")), "pick"),
        (
            lambda: sf.Pipeline(
                [sf.Fusion(_ROUTES, synthesizer=sf.Rank(2, by_field="score")), "prov/next"]
            ),
            "rank",
        ),
    ],
    ids=["field-pick", "rank-by-field"],
)
def test_rb1_a_url4_the_new_surface_cannot_express_is_refused(
    today: Callable[[], sf.Recipe], name: str
) -> None:
    # D3: a field pick reads a signal in the new surface, so today's json_field pick has no form
    with pytest.raises(
        ValueError, match=rf"^URL4 Candidate has a {name} spec this SDK version cannot rebuild$"
    ):
        rebuild(_url4(today()))


def test_rb1_a_url4_that_is_not_url4_is_refused() -> None:
    with pytest.raises(ValueError, match=r"^URL4 must be valid URL4"):
        rebuild("((")


# ---------------------------------------------------------------- RB-3: repr


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (
            lambda: (
                sx.Fanout(["p/a", "p/b"]) >> sx.Judge("p/j", rubric="r") >> sx.ArgMax("score:judge")
            ),
            "Fanout(['p/a', 'p/b']) >> Judge('p/j', rubric='r') >> ArgMax('score:judge')",
        ),
        (
            lambda: sx.Pipeline([sx.Fanout(["p/a", "p/b"]), sx.Vote()], name="x"),
            "Pipeline([Fanout(['p/a', 'p/b']), Vote()], name='x')",
        ),
        (
            lambda: sx.Pipeline([sx.Fanout(["p/a", "p/b"]), sx.Vote()], optional=True),
            "Pipeline([Fanout(['p/a', 'p/b']), Vote()], optional=True)",
        ),
        (
            lambda: sx.Pipeline([sf.Model("p/a"), sf.Model("p/b")]),
            "Pipeline([Model('p/a'), Model('p/b')])",
        ),
        (
            lambda: sf.Model("p/a") >> sx.Fanout(["p/b", "p/c"]) >> sx.Mean(),
            "Model('p/a') >> Fanout(['p/b', 'p/c']) >> Mean()",
        ),
        (lambda: sx.Fanout(["p/a"]), "Fanout(['p/a'])"),
    ],
    ids=["judge-argmax", "named", "optional", "two-models", "model-first", "open-block"],
)
def test_rb3_a_chain_repr_uses_the_chain_operator(value: Callable[[], object], text: str) -> None:
    assert repr(value()) == text


@pytest.mark.parametrize(
    ("step", "text"),
    [
        (lambda: sx.Vote(), "Vote()"),
        (
            lambda: sx.Vote(over="json", normalize="identity", weights="cost_usd"),
            "Vote(over='json', normalize='identity', weights='cost_usd')",
        ),
        (lambda: sx.Vote(weights=(1, 2)), "Vote(weights=(1.0, 2.0))"),
        (lambda: sx.Vote(over="benchmark"), "Vote(over='benchmark')"),
        (
            lambda: sx.Vote(over=sx.Extract("regex", pattern="A: (.*)")),
            "Vote(over=Extract('regex', pattern='A: (.*)'))",
        ),
        (lambda: sx.Median(), "Median()"),
        (
            lambda: sx.Median(over="field:answer", select="value"),
            "Median(over='field:answer', select='value')",
        ),
        (lambda: sx.Mean(select="nearest"), "Mean(select='nearest')"),
        (lambda: sx.Rank(2, by="cost_usd"), "Rank(2, by='cost_usd')"),
        (lambda: sx.Rank(1, by="p", order="min"), "Rank(1, by='p', order='min')"),
        (
            lambda: sx.Filter(where=sx.signal("p") >= 0.5),
            "Filter(where=signal('p') >= 0.5)",
        ),
        (
            lambda: sx.Filter(where=sx.matches("^A"), over="last_line"),
            "Filter(where=matches('^A'), over=Extract('last_line'))",
        ),
        (lambda: sx.Concat(), "Concat()"),
        (lambda: sx.Concat(" | ", label=False), "Concat(' | ', label=False)"),
        (lambda: sx.ArgMin("cost_usd", output="answer"), "ArgMin('cost_usd', output='answer')"),
        (
            lambda: sx.First(where=sx.field("ok", normalize="text") == "yes"),
            "First(where=field('ok', normalize='text') == 'yes')",
        ),
        (
            lambda: sx.JudgePick("p/j", rubric="r", params={"temperature": 0}),
            "JudgePick('p/j', rubric='r', params={'temperature': 0})",
        ),
        (lambda: sx.Synthesize("p/w"), "Synthesize('p/w')"),
        (
            lambda: sx.Synthesize("p/w", prompt="Write it."),
            "Synthesize('p/w', prompt='Write it.')",
        ),
        (
            lambda: sx.Gate(when=sx.agreement() >= 0.7, then=sx.Vote()),
            "Gate(when=agreement() >= 0.7, then=Vote())",
        ),
        (
            lambda: sx.Merge({"answer": sx.FieldRule.from_member(1)}),
            "Merge({'answer': FieldRule.from_member(1)})",
        ),
    ],
)
def test_rb3_a_step_repr_shows_only_the_arguments_that_differ(
    step: Callable[[], object], text: str
) -> None:
    assert repr(step()) == text


def test_rb3_a_member_with_options_shows_as_a_model() -> None:
    fanout = sx.Fanout([sf.Model("p/a", prompt="Be brief."), "p/b"], quorum=1, name="pair")

    assert (
        repr(fanout) == "Fanout([Model('p/a', prompt='Be brief.'), 'p/b'], quorum=1, name='pair')"
    )


def test_rb3_today_to_python_keeps_its_output() -> None:
    # The swap (unit 7) switches Url4.to_python to the new rebuild; until then it is today's.
    url4 = _url4(sf.Fusion(_ROUTES, synthesizer=sf.Vote()))

    assert "sf.Fusion(" in sf.Url4(url4).to_python()


def test_rb3_today_to_python_still_refuses_a_narrow_url4() -> None:
    # U5d: today's classes cannot spell a narrow step, so to_python keeps its refusal until the swap
    url4 = (COMBINE_CONTRACT / "narrow_filter_mean_candidate.url4").read_text(encoding="utf-8")

    with pytest.raises(ValueError, match=r"narrow steps before its reducer"):
        sf.Url4(url4.removesuffix("\n")).to_python()
