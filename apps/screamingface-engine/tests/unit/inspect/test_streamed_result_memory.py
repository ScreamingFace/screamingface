"""After streamed delivery, a 5-member Fusion's end-of-run memory is the CaseResult list only.

FEATURE: memory fix 3 (OME-1835), unit 1.
Spec: ``docs/spec/2026-11-16-streamed-candidate-result.md``.
Before the fix, the aggregate built the whole result three more times after the CaseResult list:
a dict tree (``as_payload``), one str (``compact_json``) and its UTF-8 bytes (``build_result``).
One wide character in one answer made the str 4 bytes per character, so the whole str grew
about four times. After the fix, the result is written one Case at a time into the run spool.

How it is measured: the harness of ``test_case_result_memory.py`` (synthetic MMLU-Pro bundle,
hosted run path, stub gateway, tracemalloc), with the 5-member Fusion Candidate of
``scripts/bench/report_memory.py`` (six model calls per Case).

- Aggregate: the traced peak after the last model call, above what was live at that call.
- Held: what is still live when the run ends, above what was live at that call.

Each is divided by N. This file does not change the bound of ``test_case_result_memory.py``
(append-only tests); it adds tighter bounds for the two variants that the fix targets.

INVARIANT: the bound is per Case, so it holds whatever N is.
"""

from __future__ import annotations

import gc
import importlib.util
import json
import tracemalloc
from pathlib import Path

import httpx
import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_case_result_memory import (  # noqa: E402
    _CANDIDATE,
    _KIB,
    _MODEL,
    _Publisher,
    _reply,
    _write_bundle,
)

from screamingface_engine.benchmarks import link_candidate  # noqa: E402
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS  # noqa: E402
from screamingface_engine.runner.main import build_executor  # noqa: E402
from screamingface_engine.subjects import RUN_ROOT_NODE  # noqa: E402
from screamingface_engine.world.config import (  # noqa: E402
    AigatewaySection,
    ModelSpec,
    WorldConfig,
)
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from url4.streaming.lifecycle import run  # noqa: E402

_CASES = 300
#: The 5-member Fusion (member-a..e~v1 and synth~v1) of the probe script. One owner, so this
#: bound and the probe's stage table always measure the same Candidate.
_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "bench" / "report_memory.py"
_spec = importlib.util.spec_from_file_location("report_memory_for_bounds", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_report_memory = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_report_memory)
_FUSION_CANDIDATE: str = _report_memory._FUSION_CANDIDATE
_FUSION_MODELS: tuple[str, ...] = _report_memory._FUSION_MODELS

#: Per-Case bounds, in KiB: the highest of 3 local runs at N=300, x1.25, rounded up to 0.5.
#: BEFORE the fix (spec, Fusion N=1,000): aggregate peak 39.1 KiB/Case at the dict stage,
#: 77.6 with one emoji; held until the run ends 7.3, and 37.0 with one emoji. The same
#: harness at N=300 with the spool unbound (the old path): aggregate 49.0, one emoji 83.5;
#: held 7.1, one emoji 36.3. So each bound below fails the old path.
#: AFTER the fix (3 runs, N=300): Fusion aggregate 31.95 to 32.08; one emoji 31.27 to 31.45;
#: held -3.26 to -2.39 (below what was live at the last call: the Case phase is freed).
#: WHY the held bound is 1.0 and not 1.25 x a negative value: a negative bound would pin how
#: much of the Case phase is freed, not that no result-sized object is held. 1.0 KiB/Case is
#: far below one Case of the result (~10 KiB for this Fusion), so a held result breaks it.
#: What the aggregate still holds per Case is the CaseResult list itself and one Case
#: fragment at a time; a whole-result str, bytes or dict tree breaks the bound.
_FUSION_AGGREGATE_KIB_PER_CASE = 40.5
_WIDE_AGGREGATE_KIB_PER_CASE = 39.5
_HELD_KIB_PER_CASE = 1.0


class _CountingGateway:
    """Answers every chat call; at call ``expected_calls``, marks the end of the Case phase.

    With ``emoji_call``, that one reply ends in one emoji, so one answer of the run is wide.
    """

    def __init__(self, expected_calls: int, *, emoji_call: int | None) -> None:
        self.expected_calls = expected_calls
        self.emoji_call = emoji_call
        self.calls = 0
        self.at_last_call = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls += 1
        if self.calls == self.expected_calls:
            self.at_last_call = tracemalloc.get_traced_memory()[0]
            tracemalloc.reset_peak()
        content = _reply(body["model"] + json.dumps(body["messages"])[-200:])
        if self.calls == self.emoji_call:
            content += " \U0001f600"
        message = {"role": "assistant", "content": content}
        return httpx.Response(
            200,
            json={
                "id": f"x{self.calls}",
                "model": body["model"],
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 600, "completion_tokens": 350},
            },
        )


async def _measure(
    tmp_path: Path,
    cases: int,
    candidate: str = _CANDIDATE,
    models: tuple[str, ...] = (_MODEL,),
    *,
    emoji_call: int | None,
) -> tuple[float, float, str]:
    """Run N Cases; return (aggregate KiB per Case, held KiB per Case, outcome).

    Each model of ``models`` answers once per Case: one call for a single model, six for
    the 5-member Fusion (five members and the synthesizer).
    """

    _write_bundle(tmp_path, cases)
    calls_per_case = len(models)
    gateway = _CountingGateway(cases * calls_per_case, emoji_call=emoji_call)
    url4 = link_candidate(candidate, imported_benchmark("mmlu_pro").benchmark.build(cases))
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.respond), base_url="http://aigateway.test"
    )
    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=models[0],
            models=tuple(ModelSpec(id=model) for model in models),
        )
    )
    executor = build_executor(
        {
            "URL4_CLOUD_TOPIC": "streamed-result-memory",
            "URL4_CLOUD_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
        },
        config,
        client=client,
        benchmarks=BUILTIN_BENCHMARKS,
        benchmark_assets_root=tmp_path,
    )
    gc.collect()
    tracemalloc.start(1)
    try:
        await run(_Publisher(), executor, "streamed-result-memory", url4, node=RUN_ROOT_NODE)
        held_at_end, aggregate_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        await client.aclose()
    assert gateway.calls == cases * calls_per_case, "every model call must have been answered"
    aggregate = (aggregate_peak - gateway.at_last_call) / cases / _KIB
    held = (held_at_end - gateway.at_last_call) / cases / _KIB
    return aggregate, held, str(getattr(executor.last_summary(), "outcome", None))


@pytest.mark.asyncio
async def test_a_five_member_fusion_aggregate_is_bounded_after_streaming(tmp_path: Path) -> None:
    aggregate, held, outcome = await _measure(
        tmp_path, _CASES, _FUSION_CANDIDATE, _FUSION_MODELS, emoji_call=None
    )
    print(f"fusion N={_CASES} aggregate={aggregate:.2f} KiB/Case held={held:.2f} KiB/Case")
    assert outcome == "succeeded"
    assert aggregate < _FUSION_AGGREGATE_KIB_PER_CASE, f"aggregate {aggregate:.2f} KiB/Case"
    assert held < _HELD_KIB_PER_CASE, f"held {held:.2f} KiB/Case"


@pytest.mark.asyncio
async def test_one_wide_character_no_longer_multiplies_the_aggregate(tmp_path: Path) -> None:
    # WHY call 7: it is the first model call of a later Case, so one answer in the whole run
    # carries the emoji. Before the fix that one character made the whole result str wide.
    aggregate, held, outcome = await _measure(
        tmp_path, _CASES, _FUSION_CANDIDATE, _FUSION_MODELS, emoji_call=7
    )
    print(f"fusion+emoji N={_CASES} aggregate={aggregate:.2f} KiB/Case held={held:.2f} KiB/Case")
    assert outcome == "succeeded"
    assert aggregate < _WIDE_AGGREGATE_KIB_PER_CASE, f"aggregate {aggregate:.2f} KiB/Case"
    assert held < _HELD_KIB_PER_CASE, f"held {held:.2f} KiB/Case"
