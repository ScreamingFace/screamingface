# pyright: reportMissingImports=false
# WHY file-level: assembling a row touches the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""OME-1527, R13 — a Benchmark row may declare the web-search rule its exam sets.

FEATURE: an imported (or local) Benchmark's Candidate call is retrieval-free, unless its row
declares a retrieval policy: search on, a named list of domains never reached. draco's exam
says "web search on, seven domains banned", and it moves to a local Task next.

STORY: a row declares ``draco/reproduction`` banning arxiv.org and huggingface.co. Its
Candidate call says ``web_search=true&web_search_exclude=arxiv.org:huggingface.co``, the
Candidate adapter turns that into the ceiling every nested model call runs under, and the
model request carries both banned domains although the Candidate's own call named none.

INVARIANT: a row without a policy sends exactly the Candidate call it always sent
(``web_search=false``) and keeps its revision; with one, the id and the sorted domains are
Benchmark identity. A malformed declaration is refused when the row is declared.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE  # noqa: E402
from screamingface_engine.world.candidate_adapter import (  # noqa: E402
    install_candidate_invocation,
)
from screamingface_engine.world.config import ModelSpec  # noqa: E402
from screamingface_engine.world.connector import (  # noqa: E402
    AigatewayConfig,
    build_aigateway_world,
)
from screamingface_engine_inspect import benchmarks, single_shot  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, BenchmarkSpec  # noqa: E402
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    ImportedBenchmark,
    RetrievalPolicyDeclaration,
)
from url4 import RelExpr, expr, render, src, text  # noqa: E402

#: A provider-side searching route: the gateway runs the search, so the request body shows
#: the ceiling directly (``web_search`` and the banned domains) with no Tavily loop to fake.
_NATIVE: str = "openrouter/anthropic/claude-opus-4.8"
_POLICY: RetrievalPolicyDeclaration = RetrievalPolicyDeclaration(
    policy_id="draco/reproduction", excluded_domains=("huggingface.co", "arxiv.org")
)


def _assembled(spec: BenchmarkSpec, monkeypatch: pytest.MonkeyPatch) -> ImportedBenchmark:
    """Assemble one row through the real table path, with the caches emptied per test."""

    monkeypatch.setattr(benchmarks, "BENCHMARKS", (spec,))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    return benchmarks.imported_benchmark(spec.key)


def _gsm8k(**overrides: Any) -> BenchmarkSpec:
    """gsm8k's real row with overrides. Stand-in: it simulates a row that declares a
    retrieval policy; it does not prove draco's own Task, nor any provider's search."""

    row: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == "gsm8k")
    return replace(row, **overrides)


def _candidate_params(imported: ImportedBenchmark) -> tuple[tuple[str, str], ...]:
    """The retrieval params the row's built protocol puts on its Candidate call, in order."""

    rendered: str = render(imported.benchmark.protocol(2))
    found: re.Match[str] | None = re.search(r"/benchmarks/candidate\?([^(]*?)&q=", rendered)
    assert found is not None, rendered
    # WHY drop context_format: it names the Case envelope the iteration fills in, which this
    # test replaces with plain text; only the retrieval params are under test.
    return tuple(pair for pair in parse_qsl(found.group(1)) if pair[0] != "context_format")


async def _bodies(params: tuple[tuple[str, str], ...], inner_params: str = "") -> list[dict]:
    """Run one Candidate call with ``params`` through the real adapter; return each model
    request body. The Candidate is a stand-in: one model call, asking nothing about search
    unless ``inner_params`` says so."""

    captured: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}], "usage": {}})

    call: RelExpr = RelExpr(
        path=CANDIDATE_ROUTE,
        context="What is 6 times 7?",
        intent=text(f"/{_NATIVE}('What is 6 times 7?')!'answer'{inner_params}"),
        params=params,
    )
    expression: str = render(expr(src(call, name="answer", weight=0.0), intent=text("$answer")))
    config: AigatewayConfig = AigatewayConfig(
        default_model=_NATIVE, models=(ModelSpec(id=_NATIVE),)
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(config, client=client)
        install_candidate_invocation(world.node)
        try:
            await world.node.evaluate(expression)
        finally:
            await world.aclose()
    return captured


def test_a_row_without_a_policy_sends_the_candidate_call_it_always_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain: ImportedBenchmark = _assembled(_gsm8k(), monkeypatch)

    assert _candidate_params(plain) == (("web_search", "false"),)
    assert "web_search_exclude" not in render(plain.benchmark.protocol(2))


def test_a_declared_policy_rides_the_candidate_call_sorted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    searching: ImportedBenchmark = _assembled(_gsm8k(retrieval_policy=_POLICY), monkeypatch)

    assert _candidate_params(searching) == (
        ("web_search", "true"),
        ("web_search_exclude", "arxiv.org:huggingface.co"),
    )


@pytest.mark.asyncio
async def test_the_ceiling_bans_the_rows_domains_on_a_call_that_names_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: the Candidate's recipe is the participant's, not the exam's; the ban must hold
    on its model calls whatever they ask, which only the adapter's ceiling guarantees."""

    params = _candidate_params(_assembled(_gsm8k(retrieval_policy=_POLICY), monkeypatch))

    body: dict = (await _bodies(params))[0]

    assert body["web_search"] is True
    assert body["web_search_excluded_domains"] == ["arxiv.org", "huggingface.co"]


@pytest.mark.asyncio
async def test_without_a_policy_a_candidate_that_asks_to_search_is_held_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    params = _candidate_params(_assembled(_gsm8k(), monkeypatch))

    body: dict = (await _bodies(params, inner_params=";web_search=true"))[0]

    assert "web_search" not in body
    assert "tools" not in body


def test_the_policy_is_benchmark_identity_only_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    plain: str = _assembled(_gsm8k(), monkeypatch).benchmark.revision
    searching: str = _assembled(_gsm8k(retrieval_policy=_POLICY), monkeypatch).benchmark.revision
    reordered: str = _assembled(
        _gsm8k(
            retrieval_policy=RetrievalPolicyDeclaration(
                policy_id="draco/reproduction", excluded_domains=("ArXiv.org", "huggingface.co")
            )
        ),
        monkeypatch,
    ).benchmark.revision
    other_domain: str = _assembled(
        _gsm8k(
            retrieval_policy=RetrievalPolicyDeclaration(
                policy_id="draco/reproduction", excluded_domains=("arxiv.org",)
            )
        ),
        monkeypatch,
    ).benchmark.revision

    assert searching != plain
    # WHY equal: the domains are sorted and lowercased before hashing, so writing the same
    # ban in another order or case cannot fork the Benchmark.
    assert reordered == searching
    assert other_domain not in {plain, searching}


@pytest.mark.parametrize(
    ("policy_id", "excluded_domains", "complaint"),
    [
        ("", ("arxiv.org",), "must be lowercase words"),
        ("Draco Reproduction", ("arxiv.org",), "must be lowercase words"),
        ("draco/reproduction\n", ("arxiv.org",), "must be lowercase words"),
        ("draco/reproduction", (), "excluded_domains is empty"),
        ("draco/reproduction", ("arxiv.org/abs/2602.11685",), "must be bare domains"),
        ("draco/reproduction", ("*.arxiv.org",), "must be bare domains"),
        ("draco/reproduction", "arxiv.org", "must be bare domains"),
    ],
)
def test_a_malformed_declaration_is_refused_when_declared(
    policy_id: str, excluded_domains: tuple[str, ...], complaint: str
) -> None:
    """WHY at declaration: a path or wildcard is a provider 400 on every answering call, a
    run that finishes with a zero score; the row is the last place it is still loud."""

    with pytest.raises(ValueError, match=complaint):
        RetrievalPolicyDeclaration(policy_id=policy_id, excluded_domains=excluded_domains)


def _frontierscience(**overrides: Any) -> BenchmarkSpec:
    """frontierscience's real judged row with overrides. Stand-in: it simulates a judged row
    that declares a retrieval policy; it does not prove draco's own judge."""

    row: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == "frontierscience")
    return replace(row, **overrides)


def test_a_searching_rows_judge_that_pins_search_off_assembles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judged: ImportedBenchmark = _assembled(_frontierscience(retrieval_policy=_POLICY), monkeypatch)

    assert judged.judge is not None
    assert ("web_search", "false") in judged.judge.params


@pytest.mark.parametrize(
    "judge_params",
    [(("max_tokens", "4096"),), (("web_search", "true"), ("max_tokens", "4096"))],
)
def test_a_searching_rows_judge_that_can_search_is_refused(
    judge_params: tuple[tuple[str, str], ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHY: the policy turns search on for the Candidate only; a judge call with no
    web_search=false searches on its route's default, so it could look the answer up."""

    row: BenchmarkSpec = _frontierscience(retrieval_policy=_POLICY)
    assert row.judge is not None
    searching_judge: BenchmarkSpec = replace(row, judge=replace(row.judge, params=judge_params))

    with pytest.raises(ValueError, match="must pin its judge's web search off"):
        _assembled(searching_judge, monkeypatch)
