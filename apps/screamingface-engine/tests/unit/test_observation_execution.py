"""An unregistered installation preserves execution and operator diagnostics."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_unregistered_engine_preserves_requests_accounting_and_cancellation(tmp_path):
    source = Path(__file__).resolve().parents[2] / "src/screamingface_engine"
    target = tmp_path / "screamingface_engine"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "activity"))
    script = r"""
import asyncio
import importlib.util
import logging
import httpx
from screamingface_engine.runner import connector
from screamingface_engine.runner.main import build_executor
from screamingface_engine.local import create_local_app
from screamingface_engine.observations import ModelCall
from screamingface_engine.world_config import AigatewaySection, ModelSpec, WorldConfig
from url4.streaming.protocol import CachePolicy

assert importlib.util.find_spec('screamingface_engine.activity') is None
messages = []
class Capture(logging.Handler):
    def emit(self, record):
        messages.append(record.getMessage())
connector.logger.addHandler(Capture())
connector.logger.setLevel(logging.INFO)
connector._transport_backoff = lambda attempt: 0.0

def response():
    return httpx.Response(200, json={
        'model': 'model',
        'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5},
        'choices': [{'message': {'content': 'answer'}, 'finish_reason': 'stop'}],
    })

async def call(client):
    accounting = []
    choice = await connector._logged_round_trip(
        client, real_model_id='model', headers={}, body={}, cache=CachePolicy(),
        max_tokens=None, operation_accounting=accounting,
    )
    assert choice.content == 'answer'
    assert len(accounting) == 1 and accounting[0] is not None

async def main():
    attempts = []
    def retry(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ReadError('transport detail')
        return response()
    async with httpx.AsyncClient(
        base_url='http://gateway', transport=httpx.MockTransport(retry)
    ) as client:
        await call(client)
    assert len(attempts) == 2
    assert any('model call completed' in m for m in messages)

    attempts.clear()
    def failed(request):
        attempts.append(request)
        return httpx.Response(503, json={})
    async with httpx.AsyncClient(
        base_url='http://gateway', transport=httpx.MockTransport(failed)
    ) as client:
        try:
            await call(client)
        except Exception:
            pass
        else:
            raise AssertionError('provider failure disappeared')
    assert len(attempts) == 1
    assert any('model call failed' in m for m in messages)

    entered = asyncio.Event()
    async def stalled(request):
        entered.set()
        await asyncio.Event().wait()
    async with httpx.AsyncClient(
        base_url='http://gateway', transport=httpx.MockTransport(stalled)
    ) as client:
        task = asyncio.create_task(call(client))
        await entered.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('cancellation disappeared')
    assert not [t for t in asyncio.all_tasks() if '_in_flight_heartbeat' in str(t.get_coro())]

    config = WorldConfig(aigateway=AigatewaySection(
        base_url='http://gateway', default_model='model', models=(ModelSpec(id='model'),),
    ))
    async with httpx.AsyncClient(
        base_url='http://gateway', transport=httpx.MockTransport(lambda _: response())
    ) as client:
        executor = build_executor({}, config, client=client)
        frames = [frame async for frame in executor.execute("/model('question')!go")]
    assert frames
    assert 'sf.activity.' not in str(frames)

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
