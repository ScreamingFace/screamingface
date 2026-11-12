"""Drift guard for the url4 fixtures of the README router and cascade recipes (E4c, docs, C9).

FEATURE: OME-1291 plan unit 15 — the README section "Choose whether a model runs" assigns the
recipes ``d1_keyword_router`` ... ``d10_adaptive_sampling``. The Engine world runs each
``gate_contract/d*.url4`` verbatim on a fake gateway
(``apps/screamingface-engine/tests/unit/test_e4c_docs_recipes_run.py``), and
``test_routers_cascades_docs.py`` checks that the README block compiles to the same bytes. This
file keeps each fixture byte-identical to what the SDK compiles today.
STORY: as a reader who copies a README recipe, the code I copy is the code the Engine proves.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import test_e4c_docs_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import ENGINE_APP, engine_operators, requires_engine_app

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

GATE_CONTRACT = ENGINE_APP / "tests" / "unit" / "data" / "gate_contract"

# The README names, in the same words as the README code block.
PANEL = ["prov/alpha", "prov/beta", "prov/gamma"]
LARGE, SMALL, CODER, GENERAL = "prov/large", "prov/small", "prov/coder", "prov/general"
ROUTER = "prov/router"
TOPIC = sf.RegexClassifier([("math", r"(?i)\b(integral|equation)\b"), ("code", r"(?i)\bpython\b")])
KIND = sf.LLMClassifier(ROUTER, labels=["math", "code", "other"])
JAILBREAK = sf.RegexClassifier([("jailbreak", r"(?i)ignore (all|previous) instructions")])
DOMAIN = sf.LLMClassifier(ROUTER, labels=["medical", "other"])
EXPERTS = sf.LLMClassifier(ROUTER, labels=["law", "medicine", "finance"], multi=True)


def _math_panel() -> sf.Recipe:
    return sf.Fanout(PANEL) >> sf.Vote()


def d1_keyword_router() -> sf.Recipe:
    return sf.Gate(
        when=sf.label(TOPIC) == "math",
        then=_math_panel(),
        otherwise=sf.Gate(when=sf.label(TOPIC) == "code", then=CODER, otherwise=GENERAL),
    )


def d2_label_router() -> sf.Recipe:
    return sf.Gate(
        when=sf.label(KIND) == "math",
        then=_math_panel(),
        otherwise=sf.Gate(when=sf.label(KIND) == "code", then=CODER, otherwise=GENERAL),
    )


def d3_guarded_router() -> sf.Recipe:
    return sf.Gate(
        when=sf.label(JAILBREAK) == "jailbreak",
        then=sf.fail(),
        otherwise=sf.Gate(
            when=sf.label(DOMAIN) == "medical", then=LARGE, otherwise=d2_label_router()
        ),
    )


def d4_cope_cascade() -> sf.Recipe:
    return sf.Cascade(sf.Fanout(PANEL) >> sf.Vote(), sf.escalate_if(sf.agreement() < 0.8), LARGE)


def d5_steer_answer_cascade() -> sf.Recipe:
    return sf.Cascade(
        sf.Fanout(["openrouter/openai/gpt-4o-mini"], signals={"lp": sf.Logprob("prob")})
        >> sf.Vote(),
        sf.escalate_if(sf.signal("lp") < 0.7),
        "openrouter/openai/gpt-4.1",
    )


def d6_first_success() -> sf.Recipe:
    return sf.Cascade(
        "prov/alpha",
        sf.escalate_if(sf.unanswered()),
        "prov/beta",
        sf.escalate_if(sf.unanswered()),
        "prov/gamma",
    )


def d7_manager_subset() -> sf.Recipe:
    return sf.Fanout(
        [
            sf.Gate(when=sf.labels(EXPERTS).has("law"), then="prov/law"),
            sf.Gate(when=sf.labels(EXPERTS).has("medicine"), then="prov/medicine"),
            sf.Gate(when=sf.labels(EXPERTS).has("finance"), then="prov/finance"),
        ]
    ) >> sf.Synthesize("prov/writer")


def d8_budget_choice() -> sf.Recipe:
    return sf.WithBudget(
        sf.Gate(when=sf.budget.remaining() >= 0.02, then=LARGE, otherwise=SMALL), budget_usd=0.05
    )


def d9_budget_cap() -> sf.Recipe:
    return sf.WithBudget(d4_cope_cascade(), budget_usd=0.05)


def d10_adaptive_sampling() -> sf.Recipe:
    return sf.Cascade(
        sf.Fanout(sf.samples(SMALL, 2)) >> sf.Vote(),
        sf.escalate_if(sf.agreement() < 1.0),
        sf.Fanout(sf.samples(SMALL, 5, seeds=range(2, 7))) >> sf.Vote(),
    )


# The README recipe name -> its builder, in README order.
RECIPES: dict[str, Callable[[], sf.Recipe]] = {
    build.__name__: build
    for build in (
        d1_keyword_router,
        d2_label_router,
        d3_guarded_router,
        d4_cope_cascade,
        d5_steer_answer_cascade,
        d6_first_success,
        d7_manager_subset,
        d8_budget_choice,
        d9_budget_cap,
        d10_adaptive_sampling,
    )
}


def compile_url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4


def _url4(build: Callable[[], sf.Recipe]) -> Callable[[], str]:
    return lambda: compile_url4(build())


BUILDERS: dict[str, Callable[[], str]] = {
    f"{name}.url4": _url4(build) for name, build in RECIPES.items()
}


def write_fixture(name: str) -> None:
    GATE_CONTRACT.mkdir(parents=True, exist_ok=True)
    # WHY "\n": the end-of-file-fixer wants one final newline; every reader strips exactly one.
    (GATE_CONTRACT / name).write_text(BUILDERS[name]() + "\n", encoding="utf-8")


def read_fixture(name: str) -> str:
    fixture = GATE_CONTRACT / name
    assert fixture.exists(), f"gate_contract/{name} is missing - run write_fixture({name!r})"
    return fixture.read_text(encoding="utf-8").removesuffix("\n")


@requires_engine_app
@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_docs_url4_fixtures_match_the_sdk_compile(name: str) -> None:
    assert read_fixture(name) == BUILDERS[name]()
