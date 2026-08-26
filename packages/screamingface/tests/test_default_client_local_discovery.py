"""Default-client discovery of a running `screamingface up` stack (OME-998).

FEATURE: `up` -> open notebook -> `sf.connect()` with zero configuration — the lazy
default Client prefers a running, liveness-checked local stack over the hosted engine.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from screamingface import _default_client
from screamingface._runtime import detect

_HOSTED_ENGINE = "https://fusion.dev.screamingface.ai"
_HOSTED_SCOREBOARD = "https://leaderboard.dev.screamingface.ai"


@pytest.fixture
def isolated_default_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    """Point discovery at an empty data dir and reset the process-wide Client."""

    monkeypatch.setenv("SCREAMINGFACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SCREAMINGFACE_ENGINE_URL", raising=False)
    monkeypatch.delenv("SCREAMINGFACE_SCOREBOARD_URL", raising=False)
    monkeypatch.setattr(_default_client, "_client", None)
    yield tmp_path
    client = _default_client._client
    if client is not None:
        client.close()
    monkeypatch.setattr(_default_client, "_client", None)


def _write_state(data_dir: Path, *, engine_url: str, scoreboard_url: str) -> None:
    state = {
        "schema_version": 1,
        "pid": 1,
        "services": {
            "gateway": "http://127.0.0.1:9105",
            "scoreboard": scoreboard_url,
            "engine": engine_url,
        },
    }
    (data_dir / "runtime.json").write_text(json.dumps(state))


class _HealthzHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server contract
        status = 200 if self.path == "/healthz" else 404
        self.send_response(status)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@pytest.fixture
def live_engine_url() -> Iterator[str]:
    """A real local HTTP server answering 200 on /healthz, like the runtime does."""

    server = HTTPServer(("127.0.0.1", 0), _HealthzHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _dead_engine_url() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def test_default_client_prefers_a_running_local_stack(
    isolated_default_client: Path,
    live_engine_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # STORY: as a local tester, `up` then a fresh notebook connects locally, announced.
    _write_state(
        isolated_default_client,
        engine_url=live_engine_url,
        scoreboard_url="http://127.0.0.1:9106",
    )

    client = _default_client.default_client()

    assert client.engine_url == live_engine_url
    assert client.scoreboard_url == "http://127.0.0.1:9106"
    output = capsys.readouterr().out
    assert live_engine_url in output
    assert "SCREAMINGFACE_ENGINE_URL" in output


def test_local_stack_announcement_prints_once_per_client(
    isolated_default_client: Path,
    live_engine_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_state(
        isolated_default_client,
        engine_url=live_engine_url,
        scoreboard_url="http://127.0.0.1:9106",
    )

    first = _default_client.default_client()
    second = _default_client.default_client()

    assert first is second
    assert capsys.readouterr().out.count(live_engine_url) == 1


def test_explicit_engine_env_var_beats_a_running_local_stack(
    isolated_default_client: Path,
    live_engine_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # INVARIANT: an explicit SCREAMINGFACE_ENGINE_URL keeps absolute precedence —
    # hosted-while-local-running stays one export away.
    _write_state(
        isolated_default_client,
        engine_url=live_engine_url,
        scoreboard_url="http://127.0.0.1:9106",
    )
    monkeypatch.setenv("SCREAMINGFACE_ENGINE_URL", "https://override.example")

    client = _default_client.default_client()

    assert client.engine_url == "https://override.example"
    assert client.scoreboard_url == _HOSTED_SCOREBOARD
    assert capsys.readouterr().out == ""


def test_scoreboard_env_var_beats_the_discovered_local_scoreboard(
    isolated_default_client: Path,
    live_engine_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_state(
        isolated_default_client,
        engine_url=live_engine_url,
        scoreboard_url="http://127.0.0.1:9106",
    )
    monkeypatch.setenv("SCREAMINGFACE_SCOREBOARD_URL", "https://scores.example")

    client = _default_client.default_client()

    assert client.engine_url == live_engine_url
    assert client.scoreboard_url == "https://scores.example"


def test_stale_state_with_a_dead_engine_falls_back_to_hosted(
    isolated_default_client: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # INVARIANT: a crashed runtime's leftover state must never route connect at a
    # dead port — discovery is gated on a real liveness probe, not file existence.
    _write_state(
        isolated_default_client,
        engine_url=_dead_engine_url(),
        scoreboard_url="http://127.0.0.1:9106",
    )

    client = _default_client.default_client()

    assert client.engine_url == _HOSTED_ENGINE
    assert client.scoreboard_url == _HOSTED_SCOREBOARD
    assert capsys.readouterr().out == ""


def test_no_local_state_keeps_the_hosted_default_silent(
    isolated_default_client: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probes: list[str] = []
    monkeypatch.setattr(detect, "_engine_alive", lambda url: probes.append(url) or True)

    client = _default_client.default_client()

    assert client.engine_url == _HOSTED_ENGINE
    assert probes == []
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "state_text",
    [
        "not json",
        json.dumps(["not", "a", "dict"]),
        json.dumps({"schema_version": 999, "services": {}}),
        json.dumps({"schema_version": 1, "services": {"engine": "http://127.0.0.1:9108"}}),
    ],
)
def test_unusable_state_is_ignored_without_a_probe(
    isolated_default_client: Path,
    monkeypatch: pytest.MonkeyPatch,
    state_text: str,
) -> None:
    (isolated_default_client / "runtime.json").write_text(state_text)
    probes: list[str] = []
    monkeypatch.setattr(detect, "_engine_alive", lambda url: probes.append(url) or True)

    client = _default_client.default_client()

    assert client.engine_url == _HOSTED_ENGINE
    assert probes == []


def test_configure_ignores_discovery(
    isolated_default_client: Path,
    live_engine_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_state(
        isolated_default_client,
        engine_url=live_engine_url,
        scoreboard_url="http://127.0.0.1:9106",
    )

    client = _default_client.configure(engine_url="https://chosen.example")

    assert client.engine_url == "https://chosen.example"
    assert capsys.readouterr().out == ""


def test_detect_reads_the_same_state_file_the_runtime_writes(
    isolated_default_client: Path,
) -> None:
    # INVARIANT: detect and RuntimeConfig.state_path must never drift apart.
    from screamingface._runtime.config import RuntimeConfig, default_data_dir

    config = RuntimeConfig(data_dir=default_data_dir())

    assert detect._local_state_path() == config.state_path
