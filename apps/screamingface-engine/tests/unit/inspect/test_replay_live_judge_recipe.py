# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""OME-1909 — a judged recipe re-graded live: only the judge call leaves the replay.

FEATURE: OME-1909. The header, env and connector rules for `X-Replay-Live-Judge` are pinned
extra-less in `tests/unit/test_replay_live_judge.py`. This module drives a real judged Imported
Benchmark (FrontierScience) end to end, solo and Fusion, so it needs the inspect extra and lives
in the inspect lane (`tests/unit/test_inspect_suite_location.py`).

STORY: as a maintainer who bumped a Benchmark's grading, I re-grade a published run from its
pinned cache, paying only for the judge calls of the Cases I name.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("inspect_ai")

# WHY: the inspect lane collects only tests/unit/inspect, so pytest's prepend mode never puts
# tests/unit on sys.path; the shared frozen-copy gateway fakes live there. A full run already
# has it; the guard keeps the entry single.
_UNIT_TESTS: str = str(Path(__file__).resolve().parent.parent)
if _UNIT_TESTS not in sys.path:
    sys.path.insert(0, _UNIT_TESTS)

from frozen_copy_support import CHAT, COPY, REPLAY_CHAT, replay_scope  # noqa: E402

from screamingface_engine.activity.observer import ActivityObserver  # noqa: E402
from screamingface_engine.benchmarks.definition import link_candidate  # noqa: E402
from screamingface_engine.capture_outcomes import capture_outcomes  # noqa: E402
from screamingface_engine.grading_accounting import capture_grading_requests  # noqa: E402
from screamingface_engine.job_env import LiveJudge  # noqa: E402
from screamingface_engine.observations import RunObservations  # noqa: E402
from screamingface_engine.operation_calls import capture_request_accounting  # noqa: E402
from screamingface_engine.request_scope import RequestScope, request_scope  # noqa: E402
from screamingface_engine.world.candidate_adapter import install_candidate_invocation  # noqa: E402
from screamingface_engine.world.config import ModelSpec  # noqa: E402
from screamingface_engine.world.connector import (  # noqa: E402
    AigatewayConfig,
    build_aigateway_world,
)
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from url4.dag import run as execute  # noqa: E402

# FrontierScience (olympic format) is a judged Imported Benchmark: an inspect scorer asks this
# judge model for `GRADE: C`. Its judge call is identified the way production identifies it (the
# scorer's grading tag and the judge provider's request-key registry), not by a test-set tag.
JUDGE_MODEL = "openrouter/openai/gpt-5.4"
SOLO = "(answer:0.0:/writer($input)!'Answer')!'$answer'"
# A Fusion: two members (writer, writer-b) and a synthesizer (synth) that reads both answers.
FUSION = (
    "(a:0.0:/writer($input)!'Answer',b:0.0:/writer-b($input)!'Answer',"
    "answer:0.0:/synth($a,$b)!'Synthesize')!'$answer'"
)


def _write_case_one(cases: Path) -> None:
    """Write FrontierScience's one olympic-format Case and its reference answer under ``cases``."""
    (cases / "targets").mkdir(parents=True)
    (cases / "cases.json").write_text(json.dumps([{"id": 1, "input": "Explain."}]))
    (cases / "targets" / "1.json").write_text(
        json.dumps({"target": "Reference", "metadata": {"format": "olympic"}})
    )


async def _judged_replay(
    root: Path, candidate: str, live: LiveJudge
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Replay FrontierScience Case 1 with ``live`` judges; the result and every (path, model)."""
    benchmark = imported_benchmark("frontierscience")
    _write_case_one(root / benchmark.benchmark.id)
    calls: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Answer live and replayed calls alike; record which route each model's call took."""
        model: str = json.loads(request.content)["model"]
        calls.append((request.url.path, model))
        answer: str = "GRADE: C" if model == JUDGE_MODEL else "Answer"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": answer}, "finish_reason": "stop"}]}
        )

    models: tuple[str, ...] = ("writer", "writer-b", "synth", JUDGE_MODEL)
    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(respond)
    ) as client:
        world = await build_aigateway_world(
            AigatewayConfig(
                base_url="http://gateway",
                default_model="writer",
                models=tuple(ModelSpec(id=name) for name in models),
                allow_outbound=False,
            ),
            client=client,
        )
        install_candidate_invocation(world.node)
        benchmark.benchmark.install(world.node, root)
        run = RunObservations((ActivityObserver,))
        scope: RequestScope = replay_scope(replay_live_judge=live)
        try:
            with (
                request_scope(scope),
                capture_outcomes() as tally,
                run.bind(),
                capture_request_accounting(),
                capture_grading_requests(),
            ):
                # Play the executor's binding of a replay run's tally (`runner/executor.py`).
                tally.mode, tally.frozen_copy_id = "replay", COPY
                result: dict[str, Any] = json.loads(
                    await execute(
                        link_candidate(candidate, benchmark.benchmark.protocol(1)),
                        io=world.node,
                    )
                )
        finally:
            await run.aclose()
            await world.aclose()
    return result, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", [SOLO, FUSION], ids=["solo", "fusion"])
@pytest.mark.parametrize(
    ("live", "judge_route"),
    [("all", CHAT), (frozenset({"1"}), CHAT), (frozenset({"2"}), REPLAY_CHAT)],
    ids=["all", "case-1-named", "other-case-named"],
)
async def test_a_judged_recipe_sends_only_judge_calls_live_and_replays_writer_and_synth(
    tmp_path: Path, candidate: str, live: LiveJudge, judge_route: str
) -> None:
    """Only a named Case's judge call goes live; every member and synthesizer call replays."""
    result, calls = await _judged_replay(tmp_path, candidate, live)

    assert result["score"] == 1.0, result
    judge_paths: set[str] = {path for path, model in calls if model == JUDGE_MODEL}
    answer_paths: set[str] = {path for path, model in calls if model != JUDGE_MODEL}
    # The judge call goes live only when its Case (id 1, an int, named as "1") is named.
    assert judge_paths == {judge_route}
    # Every member and synthesizer call is part of the Candidate, so it always replays.
    assert answer_paths == {REPLAY_CHAT}
    answer_models: set[str] = {model for _path, model in calls if model != JUDGE_MODEL}
    assert answer_models == ({"writer", "writer-b", "synth"} if candidate == FUSION else {"writer"})
