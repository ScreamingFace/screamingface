"""A long imported run's memory grows by a small, fixed amount per Case in both phases.

FEATURE: memory fix 2 for the MMLU-Pro ``memory_budget_exceeded`` kill (spec
``docs/spec/2026-11-05-case-result-store.md``). Before the fix, every Case's ~12.5 KB
case-execution row stayed in url4's per-Case gather until the end. The rows were then joined
into one aggregate context and decoded all at once, so a 12,032-Case run peaked near 3 GiB.

How it is measured: a synthetic MMLU-Pro bundle of N Cases runs through the hosted run path
(``build_executor`` -> ``lifecycle.run``) against a stub gateway, under tracemalloc.

- Case phase: the traced peak from the start of the run until the last Case's model call.
- Aggregate: the traced peak after that call, above what was live at that call.

Each is divided by N, at N=500 and at N=2,000, and the Case phase's marginal slope between
the two sizes is bounded too. A per-Case cost that grows with N, such as a
row decoded twice or an index of every row, breaks the bound at N=2,000 even if it passes
at 500.

INVARIANT: the bound is per Case, so it holds whatever N is. The 12,032-Case repro is the
same measurement, run outside CI (ledger ``docs/work/2026-11-05-case-result-store.md``).
"""

from __future__ import annotations

import gc
import hashlib
import json
import tracemalloc
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks import link_candidate  # noqa: E402
from screamingface_engine.benchmarks.board_store import encode_board  # noqa: E402
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS  # noqa: E402
from screamingface_engine.runner.main import build_executor  # noqa: E402
from screamingface_engine.subjects import RUN_ROOT_NODE  # noqa: E402
from screamingface_engine.world.config import (  # noqa: E402
    AigatewaySection,
    ModelSpec,
    WorldConfig,
)
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from url4.streaming.interfaces.stream import EventPublisher  # noqa: E402
from url4.streaming.lifecycle import run  # noqa: E402
from url4.streaming.protocol import OutboundFrame  # noqa: E402

_KIB = 1024
_MODEL = "prov/member-a~v1"
_LETTERS = "ABCDEFGHIJ"
_RECIPE = (
    '{"recipe":{"binding":"model_1","kind":"model","name":"member-a","named":false,'
    '"role":"model"},"schema":"screamingface.recipe.v1"}'
)
_CANDIDATE = (
    f"(model_1:0.0:/{_MODEL}($input)!'Answer the request accurately.', "
    f"_sf_recipe:0.0:'{_RECIPE}')!'$model_1'"
)

#: Per-Case bounds, in KiB, with headroom over what was measured after the fix (OME-1833).
#: Measured before the fix: aggregate ~92 KiB per Case, marginal Case-phase slope ~6.3 KiB
#: per Case. Measured after: aggregate ~14.5, slope ~1.6. What the aggregate still holds per
#: Case is the report itself (each CaseResult and its JSON), which the run must return whole.
_CASE_PHASE_KIB_PER_CASE = 12.0
_CASE_PHASE_SLOPE_KIB_PER_CASE = 3.5
_AGGREGATE_KIB_PER_CASE = 24.0


def _write_bundle(root: Path, cases: int) -> None:
    """A synthetic MMLU-Pro bundle: ten-option questions, a key, and the board index."""

    bundle = root / imported_benchmark("mmlu_pro").benchmark.id
    (bundle / "targets").mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    for case_id in range(1, cases + 1):
        choices = [f"option {case_id}-{letter}" for letter in _LETTERS]
        options = "\n".join(f"{_LETTERS[i]}) {choice}" for i, choice in enumerate(choices))
        prompt = (
            "Answer the following multiple choice question. The last line of your response "
            "should be of the following format: 'ANSWER: $LETTER'. Think step by step.\n\n"
            f"Question:\nSynthetic question number {case_id}?\nOptions:\n{options}"
        )
        rows.append({"id": case_id, "case_id": str(case_id), "input": prompt})
        target = {"target": _LETTERS[case_id % 10], "choices": choices}
        (bundle / "targets" / f"{case_id}.json").write_text(json.dumps(target), encoding="utf-8")
    files = encode_board(rows)
    (bundle / "board.json").write_bytes(files.board)
    (bundle / "cases.offsets").write_bytes(files.offsets)
    (bundle / "cases.json").write_bytes(files.cases)


def _reply(seed: str) -> str:
    """~1.3 KB of chain of thought ending in a letter, like a real MMLU-Pro reply."""

    digest = hashlib.sha256(seed.encode()).hexdigest()
    steps = (f"Step {i}: weigh {digest[i % 60 : i % 60 + 4]} and drop one." for i in range(25))
    return f"{' '.join(steps)}\nANSWER: {_LETTERS[int(digest[:2], 16) % 10]}"


class _Publisher(EventPublisher):
    """Drops every frame, like a remote JetStream the run never waits on."""

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        return None

    async def flush(self) -> None:
        return None


class _StubGateway:
    """Answers every chat call; at the last Case's call, marks the end of the Case phase."""

    def __init__(self, cases: int) -> None:
        self.cases = cases
        self.calls = 0
        self.case_peak = 0
        self.at_last_case = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls += 1
        if self.calls == self.cases:
            self.at_last_case, self.case_peak = tracemalloc.get_traced_memory()
            tracemalloc.reset_peak()
        message = {"role": "assistant", "content": _reply(json.dumps(body["messages"])[-200:])}
        return httpx.Response(
            200,
            json={
                "id": f"x{self.calls}",
                "model": body["model"],
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 600, "completion_tokens": 350},
            },
        )


async def _measure(tmp_path: Path, cases: int) -> tuple[float, float, list[str]]:
    """Run N Cases; return (Case-phase KiB per Case, aggregate KiB per Case, outcomes)."""

    _write_bundle(tmp_path, cases)
    gateway = _StubGateway(cases)
    url4 = link_candidate(_CANDIDATE, imported_benchmark("mmlu_pro").benchmark.build(cases))
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.respond), base_url="http://aigateway.test"
    )
    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test", default_model=_MODEL, models=(ModelSpec(id=_MODEL),)
        )
    )
    executor = build_executor(
        {"URL4_CLOUD_TOPIC": "case-result-memory"},
        config,
        client=client,
        benchmarks=BUILTIN_BENCHMARKS,
        benchmark_assets_root=tmp_path,
    )
    gc.collect()
    tracemalloc.start(1)
    try:
        baseline = tracemalloc.get_traced_memory()[0]
        await run(_Publisher(), executor, "case-result-memory", url4, node=RUN_ROOT_NODE)
        aggregate_peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
        await client.aclose()
    assert gateway.calls == cases, "every Case's model call must have been answered"
    case_phase = (gateway.case_peak - baseline) / cases / _KIB
    aggregate = (aggregate_peak - gateway.at_last_case) / cases / _KIB
    return case_phase, aggregate, [str(getattr(executor.last_summary(), "outcome", None))]


@pytest.mark.asyncio
async def test_memory_per_case_stays_bounded_in_both_phases(tmp_path: Path) -> None:
    measured: dict[int, tuple[float, float]] = {}
    for cases in (500, 2000):
        case_phase, aggregate, outcomes = await _measure(tmp_path / str(cases), cases)
        print(f"N={cases} case_phase={case_phase:.2f} KiB/Case aggregate={aggregate:.2f} KiB/Case")
        assert outcomes == ["succeeded"]
        assert case_phase < _CASE_PHASE_KIB_PER_CASE, f"N={cases}: Case phase {case_phase:.2f}"
        assert aggregate < _AGGREGATE_KIB_PER_CASE, f"N={cases}: aggregate {aggregate:.2f}"
        measured[cases] = (case_phase, aggregate)
    # WHY the marginal slope too: at N=500 the run's fixed cost dominates the Case phase, so
    # what the 1,500 extra Cases add is the honest per-Case cost of keeping a Case's row.
    slope = (2000 * measured[2000][0] - 500 * measured[500][0]) / 1500
    print(f"Case phase marginal slope={slope:.2f} KiB/Case")
    assert slope < _CASE_PHASE_SLOPE_KIB_PER_CASE, f"Case phase slope {slope:.2f} KiB per Case"
