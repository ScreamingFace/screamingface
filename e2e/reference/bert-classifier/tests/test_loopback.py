import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from bert_reference.server import loopback_server


def test_verified_server_binds_loopback_and_does_not_log_input_or_bearer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path.resolve()
    root.joinpath("manifest.json").write_bytes(
        Path(__file__).with_name("manifest_fixture.json").read_bytes()
    )
    for name, data in {
        "config.json": b"{}",
        "tokenizer_config.json": b"{}",
        "model.safetensors": b"head",
        "vocab.txt": b"abc",
    }.items():
        root.joinpath(name).write_bytes(data)
    expected_pin = "9f94a3b04de4138225dc013b8cb2d858f99279ea87eb658b184d127e64b699a7"
    seen: list[str] = []

    def tokenizer(text: str, *, add_special_tokens: bool, truncation: bool) -> Sequence[int]:
        assert add_special_tokens and not truncation
        seen.append(text)
        return (101, 102)

    def head(_: Sequence[int]) -> Sequence[object]:
        if seen[-1] != "ping":
            raise RuntimeError("synthetic failure detail")
        return (0.0, 0.0)

    def load(files: Mapping[str, bytes]):
        assert files["model.safetensors"] == b"head"
        return tokenizer, head

    config = {
        "SF_BERT_REFERENCE_ARTIFACT_ROOT": str(root),
        "SF_BERT_REFERENCE_MANIFEST_SHA256": expected_pin,
    }
    server = loopback_server(config, load, port=0)
    assert server.config.host == "127.0.0.1"
    assert not server.config.proxy_headers and not server.config.access_log

    async def exchange(port: int, text: str) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        body = json.dumps({"inputs": text}).encode()
        writer.write(
            b"POST /classify HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Authorization: Bearer synthetic-header-sentinel\r\n"
            b"X-Forwarded-For: 192.0.2.1\r\nConnection: close\r\n"
            b"Content-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
            + body
        )
        try:
            await writer.drain()
            return await asyncio.wait_for(reader.read(), timeout=3)
        finally:
            writer.close()
            await writer.wait_closed()

    async def run() -> None:
        task = asyncio.create_task(server.serve())
        try:
            async with asyncio.timeout(3):
                while not server.started:
                    assert not task.done()
                    await asyncio.sleep(0.005)
            (listener,) = server.servers[0].sockets
            bind_ip, port = listener.getsockname()
            assert bind_ip == "127.0.0.1"
            ping = await exchange(port, "ping")
            assert ping.startswith(b"HTTP/1.1 200 ") and b'"label":"NEGATIVE"' in ping
            failure = await exchange(port, "input-sentinel")
            assert failure.startswith(b"HTTP/1.1 500 ")
            assert b'{"error":{"code":"classifier_failed"}}' in failure
            assert b"content-encoding:" not in (ping + failure).lower()
            assert b"sentinel" not in (ping + failure)
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=3)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(run())
    assert seen == ["ping", "input-sentinel"]
    assert "sentinel" not in caplog.text and "synthetic failure detail" not in caplog.text
