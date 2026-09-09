"""OME-1127: real interrupted HTTP delivery remains a candidate failure in reports."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from screamingface_engine.benchmarks.candidate_adapter import install_candidate_invocation
from screamingface_engine.benchmarks.contract import CandidateResult
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.medxpert import runtime
from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT
from screamingface_engine.benchmarks.medxpert.prepare import emit
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from screamingface_engine.runner import connector
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world_config import ModelSpec
from url4 import RelExpr, text
from url4.core.errors import ResolutionError
from url4.dag import run
from url4.observe import ObservationEvent, Usage

_MODEL = "test/model"


def _reply(mode: str) -> tuple[int, bytes, int]:
    bodies = {"empty": b"", "html": b"<html>login</html>", "partial": b'{"choices":['}
    body = bodies.get(mode, b"")
    if mode in {"ok", "reasoning_only"}:
        body = json.dumps(
            {
                "_aigw": _accounting(),
                "choices": [
                    {
                        "message": {
                            "content": "B" if mode == "ok" else None,
                            "reasoning": "Synthetic reasoning",
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        ).encode()
    status = int(mode) if mode in {"429", "503"} else 200
    length = len(body) + (100 if mode in {"disconnect", "partial"} else 0)
    return status, body, length


class Gateway:
    def __init__(self, mode: str, turn: str) -> None:
        self.mode = mode
        self.turn = turn
        self.failed_requests = 0
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        header = await reader.readuntil(b"\r\n\r\n")
        length = next(
            int(line.split(b":", 1)[1])
            for line in header.split(b"\r\n")
            if line.lower().startswith(b"content-length:")
        )
        request = json.loads(await reader.readexactly(length))
        prompt = json.dumps(request["messages"])
        turn = "commit" if "the answer is" in prompt else "reasoning"
        failing = turn == self.turn
        self.failed_requests += int(failing)
        status, body, announced = _reply(self.mode if failing else "ok")
        writer.write(
            f"HTTP/1.1 {status} Reply\r\nContent-Length: {announced}\r\n"
            "Connection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()


async def _run(tmp_path: Path, gateway: Gateway) -> CandidateResult:
    emit(
        [
            {
                "id": "Text-0",
                "question": "Pick B",
                "options": {"A": "alpha", "B": "beta"},
                "label": "B",
            }
        ],
        tmp_path / "medxpert",
    )
    async with await asyncio.start_server(gateway.handle, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
            world = await build_aigateway_world(
                AigatewayConfig(models=(ModelSpec(id=_MODEL),), default_model=_MODEL), client=client
            )
            install_candidate_invocation(world.node)
            BenchmarkRegistry((MEDXPERT,)).install(world.node, assets_root=tmp_path)
            linked = link_candidate(
                RelExpr(path=f"/{_MODEL}", context="$input", intent=text("Answer.")),
                MEDXPERT.build(1),
            )
            try:
                result = await run(linked, io=world.node, observer=gateway)
                return CandidateResult.model_validate(json.loads(result))
            finally:
                await world.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("turn", ["reasoning", "commit"])
@pytest.mark.parametrize(
    ("mode", "code", "retryable", "attempts"),
    [
        ("disconnect", "aigateway_transport_error", True, 2),
        ("partial", "aigateway_transport_error", True, 2),
        ("empty", "aigateway_empty_response", True, 1),
        ("html", "aigateway_bad_response", False, 1),
        ("reasoning_only", "model_empty_content", False, 1),
        ("429", "aigateway_http_429", True, 1),
        ("503", "aigateway_http_503", True, 1),
    ],
)
async def test_failure_survives_to_final_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    turn: str,
    mode: str,
    code: str,
    retryable: bool,
    attempts: int,
) -> None:
    monkeypatch.setattr(connector, "_transport_backoff", lambda _: 0)
    gateway = Gateway(mode, turn)
    result = await _run(tmp_path, gateway)
    failure = result.cases[0].failures[0]
    assert (failure.stage, failure.retryable) == ("candidate", retryable)
    assert failure.metadata["source_error"]["code"] == code
    assert result.score is None
    assert result.coverage == 0
    assert gateway.failed_requests == attempts


def _accounting() -> dict:
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "omitted_attempts": 0,
            "attempts": [
                {
                    "provider": "openrouter",
                    "response_model": _MODEL,
                    "latency_ms": 25,
                    "usage": {
                        "input": {"total": 10, "cache_read": 0, "cache_write": 0},
                        "output": {"total": 2, "reasoning": 0},
                    },
                }
            ],
            "cache": {"status": "miss", "reference": None},
        },
        "request_economics": {
            "direct_cost_status": "complete",
            "known_direct_cost_subtotals": [
                {"amount": "0.25", "unit": "openrouter_credits", "source": "provider"}
            ],
        },
    }


@pytest.mark.asyncio
async def test_commit_failure_keeps_completed_request_spend(tmp_path: Path) -> None:
    # INVARIANT: the failed later turn cannot erase an already recorded paid operation.
    gateway = Gateway("empty", "commit")
    result = await _run(tmp_path, gateway)
    costs = [event.cost_usd for event in gateway.events if isinstance(event, Usage)]
    assert costs == [0.25]
    assert result.score is None


@pytest.mark.asyncio
async def test_checker_failure_remains_grading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_checker(*args: object, **kwargs: object) -> str:
        raise ResolutionError("synthetic checker failure", code="test_checker", permanent=True)

    monkeypatch.setattr(runtime, "extract_choice_letter", broken_checker)
    result = await _run(tmp_path, Gateway("ok", "commit"))
    failure = result.cases[0].failures[0]
    assert failure.stage == "grading"
    assert failure.retryable is False
    assert "synthetic checker failure" in failure.message
    assert result.score is None


@pytest.mark.asyncio
async def test_successful_two_turn_run_keeps_score(tmp_path: Path) -> None:
    result = await _run(tmp_path, Gateway("ok", "commit"))
    assert result.score == 1.0
    assert result.coverage == 1.0
    assert result.cases[0].failures == []
