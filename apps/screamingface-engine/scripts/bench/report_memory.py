"""Where does the end-of-run memory go? Stage marks under tracemalloc, stub gateway, no network.

UNIT 0 of memory fix 3 (OME-1835). Spec: ``docs/spec/2026-11-16-streamed-candidate-result.md``.
REPORT ONLY: this script measures and prints. It changes nothing under ``src/``.

It uses the OME-1833 harness (``tests/unit/inspect/test_case_result_memory.py``): a synthetic
MMLU-Pro bundle, a stub gateway through ``httpx.MockTransport``, and no network. It wraps the
stage functions at run time, only those that exist, and restores every wrapper when the run
ends, even when it fails.

Usage:
    uv run --extra inspect python scripts/bench/report_memory.py single 2000
    uv run --extra inspect python scripts/bench/report_memory.py fusion 1000
    uv run --extra inspect python scripts/bench/report_memory.py fusion 300 --one-emoji
"""

import argparse
import asyncio
import gc
import importlib
import json
import shutil
import sys
import tempfile
import tracemalloc
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from screamingface_engine.benchmarks import grading_endpoints as ge
from screamingface_engine.benchmarks import link_candidate
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.contract import CandidateResult
from screamingface_engine.benchmarks.shared_grading import benchmark_aggregation as ba
from screamingface_engine.runner import executor as ex
from screamingface_engine.runner.main import build_executor
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from screamingface_engine.subjects import RUN_ROOT_NODE
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine_inspect.benchmarks import imported_benchmark
from url4.streaming.lifecycle import run

_ENGINE_ROOT = Path(__file__).resolve().parents[2]  # apps/screamingface-engine
_HARNESS_DIR = _ENGINE_ROOT / "tests" / "unit" / "inspect"
_MIB = 1024 * 1024
_FUSION_MODELS: tuple[str, ...] = tuple(f"prov/member-{c}~v1" for c in "abcde") + ("prov/synth~v1",)
# The compiled sf.Fusion of five members (member-a..e~v1) and one synthesizer (synth~v1),
# inlined so the script reads no file. It is the exact text of fusion5.url4, stripped.
_FUSION_CANDIDATE: str = (
    "(model_1:0.0:/prov/member-a~v1($input)!'Answer the request accurately and completely. "
    "Follow every instruction and formatting constraint in the request.', model_2:0.0:/prov"
    "/member-b~v1($input)!'Answer the request accurately and completely. Follow every instr"
    "uction and formatting constraint in the request.', model_3:0.0:/prov/member-c~v1($inpu"
    "t)!'Answer the request accurately and completely. Follow every instruction and formatt"
    "ing constraint in the request.', model_4:0.0:/prov/member-d~v1($input)!'Answer the req"
    "uest accurately and completely. Follow every instruction and formatting constraint in "
    "the request.', model_5:0.0:/prov/member-e~v1($input)!'Answer the request accurately an"
    "d completely. Follow every instruction and formatting constraint in the request.', syn"
    "thesis_1:0.0:/prov/synth~v1({input: '$input', outputs: {member_1: '$model_1', member_2"
    ": '$model_2', member_3: '$model_3', member_4: '$model_4', member_5: '$model_5'}})!'Pro"
    "duce the final answer to the original request. Synthesize the strongest supported answ"
    "er from the panel responses, and follow every instruction and formatting constraint in"
    ' the original request.\', _sf_recipe:0.0:\'{"recipe":{"binding":"synthesis_1","ki'
    'nd":"fusion","members":[{"binding":"model_1","kind":"model","name":"me'
    'mber-a~v1","named":false,"role":"model"},{"binding":"model_2","kind":"mo'
    'del","name":"member-b~v1","named":false,"role":"model"},{"binding":"mode'
    'l_3","kind":"model","name":"member-c~v1","named":false,"role":"model"},'
    '{"binding":"model_4","kind":"model","name":"member-d~v1","named":false,'
    '"role":"model"},{"binding":"model_5","kind":"model","name":"member-e~v1'
    '","named":false,"role":"model"}],"name":"member-a~v1+member-b~v1+member-c~v1'
    '+member-d~v1+member-e~v1","synthesizer":{"binding":"synthesis_1","kind":"mod'
    'el","name":"synth~v1","named":false,"role":"synthesis"}},"schema":"screa'
    "mingface.recipe.v1\"}')!'$synthesis_1'"
)


def _harness() -> Any:
    if str(_HARNESS_DIR) not in sys.path:
        sys.path.insert(0, str(_HARNESS_DIR))
    return importlib.import_module("test_case_result_memory")


@dataclass
class _Stages:
    marks: list[tuple[str, int, int]] = field(default_factory=list)
    sizes: dict[str, int] = field(default_factory=dict)
    snapshot: tracemalloc.Snapshot | None = None
    patched: list[tuple[object, str, object]] = field(default_factory=list)

    def mark(self, label: str) -> None:
        current, peak = tracemalloc.get_traced_memory()
        self.marks.append((label, current, peak))
        tracemalloc.reset_peak()

    def wrap(self, owner: object, name: str, make: Callable[[Any], Any]) -> bool:
        original = getattr(owner, name, None)
        if original is None:
            return False
        self.patched.append((owner, name, original))
        setattr(owner, name, make(original))
        return True

    def restore(self) -> None:
        for owner, name, original in reversed(self.patched):
            setattr(owner, name, original)
        self.patched.clear()


def _probe_aggregate(stages: _Stages) -> None:
    owner = ba.BenchmarkAggregation
    name = next(
        (n for n in ("aggregate_result_async", "aggregate_async") if hasattr(owner, n)), None
    )
    if name is None:
        return

    def make(original: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            stages.mark("1 aggregate start (all Cases answered)")
            stages.snapshot = tracemalloc.take_snapshot()
            return await original(*args, **kwargs)

        return wrapper

    stages.wrap(owner, name, make)


def _probe_finalize(stages: _Stages) -> None:
    def make(original: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            stages.mark("2 marking done (every CaseResult in a list)")
            result = original(*args, **kwargs)
            stages.mark("3 finalize done (typed_cases + CandidateResult)")
            return result

        return wrapper

    stages.wrap(ba, "finalize_candidate_result", make)


def _probe_payload(stages: _Stages) -> None:
    def make(original: Any) -> Any:
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            payload = original(self, *args, **kwargs)
            if self.cases:
                stages.mark("4 as_payload done (dict tree of the whole result)")
            return payload

        return wrapper

    stages.wrap(CandidateResult, "as_payload", make)


def _probe_compact_json(stages: _Stages) -> None:
    def make(original: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            text = original(*args, **kwargs)
            if len(text) > 200_000:
                stages.sizes["result_chars"] = len(text)
                stages.mark("5 compact_json done (one str)")
            return text

        return wrapper

    stages.wrap(ge, "compact_json", make)


def _probe_spool(stages: _Stages) -> None:
    try:
        spool = importlib.import_module("screamingface_engine.artifacts.spool")
    except ImportError:
        return

    def make(original: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            returned = original(*args, **kwargs)
            stages.sizes["spool_return_chars"] = len(returned)
            stages.mark("5 spool delivered (streamed, no whole str)")
            return returned

        return wrapper

    stages.wrap(getattr(spool, "ResultSpool", None), "deliver", make)


def _probe_build_result(stages: _Stages) -> None:
    def make(original: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            stages.mark("6 build_result start (after url4 hand-off)")
            result = original(*args, **kwargs)
            stages.sizes["delivery_artifact"] = 1 if result.artifact is not None else 0
            if result.artifact is not None:
                stages.sizes["result_bytes"] = result.artifact.size_bytes
            else:
                stages.sizes["result_bytes"] = len((result.body or "").encode("utf-8"))
            stages.mark("7 build_result done (encoded + store write)")
            return result

        return wrapper

    stages.wrap(ex._RunState, "build_result", make)


def _install(stages: _Stages) -> None:
    _probe_aggregate(stages)
    _probe_finalize(stages)
    _probe_payload(stages)
    _probe_compact_json(stages)
    _probe_spool(stages)
    _probe_build_result(stages)


class _Gateway:
    def __init__(self, harness: Any, *, wide: bool) -> None:
        self.harness = harness
        self.wide = wide
        self.calls = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls += 1
        content = self.harness._reply(body["model"] + json.dumps(body["messages"])[-200:])
        if self.wide and self.calls == 7:
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


def _candidate_for(harness: Any, mode: str) -> tuple[str, tuple[str, ...]]:
    if mode == "fusion":
        return _FUSION_CANDIDATE, _FUSION_MODELS
    if mode == "single":
        return harness._CANDIDATE, (harness._MODEL,)
    raise ValueError(f"unknown mode: {mode!r}")


def _executor(
    root: Path, client: httpx.AsyncClient, models: tuple[str, ...]
) -> OperationCapturingExecutor:
    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=models[0],
            models=tuple(ModelSpec(id=m) for m in models),
        )
    )
    return build_executor(
        {"URL4_CLOUD_TOPIC": "report-memory", "URL4_CLOUD_ARTIFACTS_DIR": str(root / "art")},
        config,
        client=client,
        benchmarks=BUILTIN_BENCHMARKS,
        benchmark_assets_root=root,
    )


def _print_growth(stages: _Stages, cases: int) -> None:
    if stages.snapshot is None:
        return
    after = tracemalloc.take_snapshot()
    print("TOP GROWTH from aggregate start to run end (per Case):")
    for stat in after.compare_to(stages.snapshot, "lineno")[:14]:
        frame = stat.traceback[0]
        where = frame.filename.split("/src/")[-1].split("site-packages/")[-1]
        print(f"  {stat.size_diff / cases / 1024:7.2f} KiB/Case  {where}:{frame.lineno}")


def _print_table(stages: _Stages, cases: int, mode: str, calls: int, outcome: object) -> None:
    print(f"mode={mode} N={cases} calls={calls} outcome={outcome} sizes={stages.sizes}")
    first = next((m for m in stages.marks if m[0].startswith("1 ")), stages.marks[0])
    base = first[1]
    header = f"{'stage':<52}{'live MiB':>10}{'peak MiB':>10}"
    print(header + f"{'live-(1) KiB/Case':>20}{'peak-(1) KiB/Case':>20}")
    for label, current, peak in stages.marks:
        print(
            f"{label:<52}{current / _MIB:>10.1f}{peak / _MIB:>10.1f}"
            f"{(current - base) / cases / 1024:>20.2f}{(peak - base) / cases / 1024:>20.2f}"
        )
    if "result_bytes" in stages.sizes:
        print(f"result bytes per Case: {stages.sizes['result_bytes'] / cases / 1024:.2f} KiB")


async def run_report(mode: str, cases: int, *, one_emoji: bool) -> None:
    harness = _harness()
    candidate, models = _candidate_for(harness, mode)
    root = Path(tempfile.mkdtemp(prefix="report-memory-"))
    harness._write_bundle(root, cases)
    gateway = _Gateway(harness, wide=one_emoji)
    url4 = link_candidate(candidate, imported_benchmark("mmlu_pro").benchmark.build(cases))
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.respond), base_url="http://aigateway.test"
    )
    executor = _executor(root, client, models)
    stages = _Stages()
    _install(stages)
    gc.collect()
    tracemalloc.start(1)
    try:
        stages.mark("0 run start")
        await run(harness._Publisher(), executor, "report-memory", url4, node=RUN_ROOT_NODE)
        stages.mark("8 run end")
        _print_growth(stages, cases)
    finally:
        tracemalloc.stop()
        stages.restore()
        await client.aclose()
        shutil.rmtree(root, ignore_errors=True)
    outcome = getattr(executor.last_summary(), "outcome", None)
    _print_table(stages, cases, mode, gateway.calls, outcome)


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="End-of-run memory per stage (report only).")
    parser.add_argument("mode", choices=["single", "fusion"])
    parser.add_argument("cases", type=int)
    parser.add_argument(
        "--one-emoji", action="store_true", help="add one emoji to one answer of the run"
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse(sys.argv[1:])
    asyncio.run(run_report(args.mode, args.cases, one_emoji=args.one_emoji))


if __name__ == "__main__":
    main()
