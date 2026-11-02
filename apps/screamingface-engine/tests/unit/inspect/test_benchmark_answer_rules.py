"""GSM8K and AIME publish the answer rule their Inspect scorer is copied from (OME-1289).

FEATURE: `answer_rule` in the benchmark catalog, so `sf.Vote(extract="benchmark")` groups answers
the way the benchmark's grade does (E4a erd section 7).
STORY: as the SDK, I read GSM8K's rule from the catalog and compile it to combine operator ids.
INVARIANT defended: a rule names operators that resolve at their stage, and its pinned grader is
the scorer the row declares at the version the vendored operators copy. Every other row has none.

Runs only with the `inspect` extra installed (`uv run --extra inspect pytest ...`).
"""

from __future__ import annotations

import httpx
import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.app import create_app  # noqa: E402
from screamingface_engine.benchmarks import BenchmarkRegistry  # noqa: E402
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS  # noqa: E402
from screamingface_engine.combine.operators import _inspect_vendor  # noqa: E402
from screamingface_engine.config import Settings  # noqa: E402
from screamingface_engine.testing import InMemoryEventStream  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    benchmark_registrations,
    imported_benchmark,
)

_INSPECT_AI = _inspect_vendor.INSPECT_AI_VERSION
_INSPECT_EVALS = _inspect_vendor.INSPECT_EVALS_VERSION

#: OME-1701 PR 7: the AIME rows grade with the eval's v0.20.0 scorer behind a
#: cut-off guard (inspect_evals issue #2701), so their rule pins that scorer; the answer it
#: reads off a finished reply, the one the combine operators copy, is the eval's own.
_AIME_GRADER: str = (
    "screamingface_engine_inspect.named_deviations.aime.aime:aime_cut_off_scorer@0.20.0"
)

_RULES: dict[str, dict[str, object]] = {
    "gsm8k": {
        "extract": {"op": "inspect_number@1", "args": {}},
        "normalize": {"op": "inspect_numeric@1", "args": {}},
        "grader": "inspect_ai.scorer:match(numeric=True)@0.3.263",
    },
    "aime24": {
        "extract": {"op": "inspect_aime@1", "args": {}},
        "normalize": {"op": "inspect_numeric@1", "args": {}},
        "grader": _AIME_GRADER,
    },
    "aime25": {
        "extract": {"op": "inspect_aime@1", "args": {}},
        "normalize": {"op": "inspect_numeric@1", "args": {}},
        "grader": _AIME_GRADER,
    },
    # OME-1602: aime2026 imports the same shared aime_scorer as aime2025.
    "aime26": {
        "extract": {"op": "inspect_aime@1", "args": {}},
        "normalize": {"op": "inspect_numeric@1", "args": {}},
        "grader": _AIME_GRADER,
    },
}


@pytest.mark.parametrize("key", sorted(_RULES))
def test_each_rule_resolves_and_pins_the_scorer_its_row_declares(key: str) -> None:
    spec = next(row for row in BENCHMARKS if row.key == key)
    rule = imported_benchmark(key).benchmark.answer_rule

    assert rule is not None
    assert BUILTIN_OPERATORS.resolve(rule.extract, "extract").id == rule.extract
    assert rule.normalize is not None
    assert BUILTIN_OPERATORS.resolve(rule.normalize, "normalize").id == rule.normalize
    assert rule.grader.startswith(spec.scorer)
    version = _INSPECT_AI if key == "gsm8k" else _INSPECT_EVALS
    assert rule.grader.endswith(f"@{version}")


@pytest.mark.asyncio
async def test_the_served_catalog_shows_the_rule_on_exactly_those_ids() -> None:
    app = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BenchmarkRegistry(tuple(item.benchmark for item in benchmark_registrations())),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        listed = (await client.get("/v1/benchmarks")).json()["data"]

    assert {entry["id"] for entry in listed if "answer_rule" in entry} == {
        f"inspect-{key}" for key in _RULES
    }
    assert {entry["id"]: entry["answer_rule"] for entry in listed if "answer_rule" in entry} == {
        f"inspect-{key}": rule for key, rule in _RULES.items()
    }
