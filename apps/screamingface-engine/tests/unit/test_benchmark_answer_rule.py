"""A Benchmark may publish how its grader reads an answer, as pinned operator ids (OME-1289).

FEATURE: `answer_rule` in the benchmark catalog, so a combine vote can group answers the way the
grade does (E4a erd section 7).
STORY: as the SDK, I read the rule from the catalog; a benchmark without a rule publishes no key.
INVARIANT defended: the rule changes the catalog ETag (a client cache never serves a stale rule)
and stays out of every other byte (a benchmark with no rule is byte-identical to before).
"""

from __future__ import annotations

import dataclasses

import httpx
import pytest
from fastapi import FastAPI
from test_benchmark_display_metadata import _benchmark

from screamingface_engine.app import create_app
from screamingface_engine.benchmarks import AnswerRule, Benchmark, BenchmarkRegistry
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

_GRADER = "inspect_ai.scorer:match(numeric=True)@0.3.263"
_RULE = AnswerRule("inspect_number@1", "inspect_numeric@1", _GRADER)


async def _get(
    benchmark: Benchmark, path: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    app: FastAPI = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BenchmarkRegistry((benchmark,)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        return await client.get(path, headers=headers)


@pytest.mark.parametrize(
    ("extract", "normalize", "grader"),
    [
        ("Inspect@1", None, _GRADER),
        ("x@0", None, _GRADER),
        ("x", None, _GRADER),
        ("inspect_number@1", "Bad@1", _GRADER),
        ("inspect_number@1", None, ""),
        ("inspect_number@1", None, "   "),
        ("inspect_number@1", None, "has space@1"),
        ("inspect_number@1", None, "inspect_ai.scorer:match"),
        ("inspect_number@1", None, "inspect_ai.scorer:match@"),
    ],
)
def test_answer_rule_validates_ids_and_grader(
    extract: str, normalize: str | None, grader: str
) -> None:
    with pytest.raises(ValueError, match="AnswerRule"):
        AnswerRule(extract, normalize, grader)


def test_answer_rule_accepts_a_lone_extract_and_a_pinned_grader() -> None:
    rule = AnswerRule("inspect_number@1", None, _GRADER)

    assert rule.as_block() == {
        "extract": {"op": "inspect_number@1", "args": {}},
        "normalize": None,
        "grader": _GRADER,
    }


def test_a_benchmark_answer_rule_must_be_an_answer_rule() -> None:
    with pytest.raises(TypeError, match="answer_rule"):
        dataclasses.replace(_benchmark(), answer_rule={"extract": "x@1"})  # type: ignore[arg-type]


def test_a_benchmark_without_a_rule_publishes_no_key() -> None:
    for benchmark in BUILTIN_BENCHMARKS:
        if benchmark.answer_rule is None:
            assert "answer_rule" not in benchmark.catalog_entry()
            assert "answer_rule" not in benchmark.resource(1)


@pytest.mark.asyncio
async def test_answer_rule_changes_benchmark_catalog_etag() -> None:
    plain = _benchmark()
    ruled = dataclasses.replace(plain, answer_rule=_RULE)

    for path in ("/v1/benchmarks", "/v1/benchmarks/example-smoke"):
        plain_response = await _get(plain, path)
        ruled_response = await _get(ruled, path)
        assert plain_response.content != ruled_response.content
        assert plain_response.headers["etag"] != ruled_response.headers["etag"]
        repeated = await _get(
            ruled, path, headers={"If-None-Match": ruled_response.headers["etag"]}
        )
        assert repeated.status_code == 304

    expected_block = {
        "extract": {"op": "inspect_number@1", "args": {}},
        "normalize": {"op": "inspect_numeric@1", "args": {}},
        "grader": _GRADER,
    }
    listed = (await _get(ruled, "/v1/benchmarks")).json()["data"][0]
    resource = (await _get(ruled, "/v1/benchmarks/example-smoke")).json()
    assert listed["answer_rule"] == expected_block
    assert resource["answer_rule"] == expected_block
    assert "answer_rule" not in (await _get(plain, "/v1/benchmarks")).json()["data"][0]
