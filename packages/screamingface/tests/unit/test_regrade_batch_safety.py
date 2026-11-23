"""OME-1958 rollout boundaries, crash recovery and cross-process exclusion."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from test_regrade_batch_script import _NEW, _OLD, _SCRIPT, _board, _entry, _FakeRegrader, batch

_BOARD = "inspect-mmlu_pro"


def test_transition_table_matches_exactly_the_47_engine_bumps() -> None:
    root = _SCRIPT.parents[3]
    source = (
        root / "apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py"
    ).read_text()
    expected = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "BenchmarkSpec":
            continue
        fields = {kw.arg: kw.value for kw in node.keywords}
        if "regradable_from" not in fields:
            continue
        if "OME-1958" not in (ast.get_source_segment(source, node) or ""):
            continue
        key = ast.literal_eval(fields["key"])
        origin = ast.literal_eval(fields["origin"]) if "origin" in fields else "inspect_evals"
        # WHY: local Tasks use bare keys, matching imported_benchmark_id in the Engine.
        board_id = "inspect-" + key if origin == "inspect_evals" else key
        expected[board_id] = {
            "source": ast.literal_eval(fields["regradable_from"])[0][0],
            "target": ast.literal_eval(fields["published_revision"]),
        }
    assert len(expected) == 47
    assert batch.TRANSITIONS == expected


def test_discovery_ignores_unrelated_historical_revisions() -> None:
    def board(request: httpx.Request) -> httpx.Response:
        response = _board(request)
        if request.url.path.endswith("/revisions"):
            data = response.json()
            data["revisions"].append({"revision": "unrelated", "result_count": 10})
            return httpx.Response(200, json=data)
        return response

    with httpx.Client(base_url="http://board", transport=httpx.MockTransport(board)) as http:
        assert len(batch.find_entries(http, [_BOARD])) == 2


@pytest.mark.parametrize(
    "mutation", ["missing", "unknown", "source", "private", "overflow", "short"]
)
def test_discovery_refuses_missing_wrong_or_incomplete_targets(mutation: str) -> None:
    def board(request: httpx.Request) -> httpx.Response:
        data = _board(request).json()
        if request.url.path == "/v1/benchmarks":
            if mutation == "missing":
                data["benchmarks"] = []
            elif mutation in {"unknown", "source"}:
                data["benchmarks"][0]["revision"] = _OLD if mutation == "source" else "unknown"
            elif mutation == "private":
                data["benchmarks"][0]["visibility"] = "private"
        elif request.url.path.endswith("/revisions") and mutation == "overflow":
            data["revisions"][1]["result_count"] = 201
        elif request.url.path == f"/v1/leaderboard/{_BOARD}" and mutation == "short":
            data["entries"] = data["entries"][:1]
        return httpx.Response(200, json=data)

    with httpx.Client(base_url="http://board", transport=httpx.MockTransport(board)) as http:
        with pytest.raises(batch.BoardReadError):
            batch.find_entries(http, [_BOARD])


@pytest.mark.parametrize(
    "argv",
    [
        ["--benchmark", "inspect-mmlu_pr"],
        ["--when-revision", _BOARD],
        ["--when-revision", f"{_BOARD}="],
        ["--when-revision", f"{_BOARD}={_OLD}"],
        ["--when-revision", f"{_BOARD}={_NEW}=extra"],
        ["--when-revision", f"unknown={_NEW}"],
        ["--benchmark", "inspect-mmlu", "--when-revision", f"{_BOARD}={_NEW}"],
    ],
)
def test_bad_selectors_fail_before_any_client_is_created(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        batch._arguments(argv)
    assert exc.value.code == 2


def test_unresolved_entries_stay_incomplete_even_if_discovery_no_longer_lists_them(
    tmp_path: Path,
) -> None:
    from screamingface.errors import PlanningError

    log = tmp_path / "log.jsonl"
    client = _FakeRegrader(
        {"refused": PlanningError("changed", code="not_regradable", permanent=True)}
    )
    entries = [_entry("refused", "s1"), _entry(None, "s2")]
    first = batch.regrade_all(client, entries, log)
    second = batch.regrade_all(client, [], log)
    assert first["unresolved"] == second["unresolved"] == 2
    assert batch.exit_status(second) == 1
    assert client.calls == ["refused"]
    keys = [row["entry_key"] for row in map(json.loads, log.read_text().splitlines())]
    resolved = batch.regrade_all(
        client, entries, log, resolutions={key: "Owner chose fresh run" for key in keys}
    )
    assert resolved["unresolved"] == 0
    assert batch.exit_status(resolved) == 0
    assert all(row["note"] for row in map(json.loads, log.read_text().splitlines()[-2:]))


@pytest.mark.parametrize("tail", [b'{"outcome":', b'{"outcome":"regraded"}', b"\xff"])
def test_only_unterminated_tail_is_recovered_before_resume(tmp_path: Path, tail: bytes) -> None:
    log = tmp_path / "log.jsonl"
    client = _FakeRegrader({"one": None, "two": None})
    batch.regrade_all(client, [_entry("one", "s1")], log)
    saved = log.read_bytes()
    log.write_bytes(saved + tail)
    if tail == b'{"outcome":"regraded"}':
        # A complete JSON value is evidence to inspect, never a partial write to discard.
        with pytest.raises(batch.LogError):
            batch.regrade_all(client, [_entry("one", "s1"), _entry("two", "s2")], log)
        assert log.read_bytes() == saved + tail
        assert client.calls == ["one"]
        return
    batch.regrade_all(client, [_entry("one", "s1"), _entry("two", "s2")], log)
    assert client.calls == ["one", "two"]
    assert log.read_bytes().startswith(saved)
    assert len(log.read_text().splitlines()) == 2


@pytest.mark.parametrize("bad", [b"broken\n", b"{}\n", b"[]\n", b"\xff\n"])
def test_complete_corruption_is_never_silently_discarded(tmp_path: Path, bad: bytes) -> None:
    log = tmp_path / "log.jsonl"
    log.write_bytes(bad)
    client = _FakeRegrader({"one": None})
    with pytest.raises(batch.LogError):
        batch.regrade_all(client, [_entry("one", "s1")], log)
    assert log.read_bytes() == bad
    assert client.calls == []


def test_outcomes_are_fsynced_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced = []
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    batch.regrade_all(_FakeRegrader({"one": None}), [_entry("one", "s1")], tmp_path / "log")
    assert synced


def test_second_process_cannot_replay_while_first_holds_log(tmp_path: Path) -> None:
    # INVARIANT: real OS processes exercise the actual lock, not a mock of flock.
    worker = """
import importlib.util, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("regrade_batch", sys.argv[1])
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
from pathlib import Path
class Client:
    def regrade(self, score_id, *, expected_target_revision):
        assert expected_target_revision == "4efebd6cc74c2dca"
        print("REPLAY", flush=True)
        sys.stdin.readline()
        return type("Result", (), {
            "id": "new", "benchmark_id": "inspect-mmlu_pro",
            "benchmark_revision": expected_target_revision, "regraded_from": score_id,
        })()
try:
    entry = m.Entry("inspect-mmlu_pro", "145edec84bfc2324", "s1", "copy", "one")
    m.regrade_all(Client(), [entry], Path(sys.argv[2]))
except m.BatchAlreadyRunning:
    sys.exit(2)
"""
    cmd = [sys.executable, "-c", worker, str(_SCRIPT), str(tmp_path / "log")]
    first = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        assert first.stdout is not None
        assert first.stdout.readline().strip() == "REPLAY"
        second = subprocess.run(cmd, input="\n", capture_output=True, text=True, timeout=10)
        assert second.returncode == 2, second.stderr
        assert "REPLAY" not in second.stdout
        first.communicate("\n", timeout=10)
        assert first.returncode == 0
        third = subprocess.run(cmd, input="\n", capture_output=True, text=True, timeout=10)
        assert third.returncode == 0, third.stderr
        assert "REPLAY" not in third.stdout
    finally:
        if first.poll() is None:
            first.kill()
        first.communicate()


def test_default_scope_is_all_47_transitions_and_never_unrelated_boards() -> None:
    visited = []

    def board(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/benchmarks":
            rows = [
                {"id": key, "revision": value["target"], "visibility": "public"}
                for key, value in batch.TRANSITIONS.items()
            ]
            rows.append({"id": "inspect-musique", "revision": "other", "visibility": "public"})
            return httpx.Response(200, json={"benchmarks": rows})
        key = path.split("/")[3]
        assert key in batch.TRANSITIONS
        if path.endswith("/revisions"):
            visited.append(key)
            return httpx.Response(
                200,
                json={
                    "revisions": [{"revision": batch.TRANSITIONS[key]["source"], "result_count": 0}]
                },
            )
        return httpx.Response(200, json={"entries": []})

    with httpx.Client(base_url="http://board", transport=httpx.MockTransport(board)) as http:
        assert batch.find_entries(http) == []
    assert len(visited) == len(set(visited)) == 47


def test_log_cannot_be_reused_on_another_environment(tmp_path: Path) -> None:
    log = tmp_path / "log"
    client = _FakeRegrader({"one": None})
    batch.regrade_all(client, [_entry("one", "s1")], log, scope="https://dev.example")
    with pytest.raises(batch.LogError, match="different Scoreboard"):
        batch.regrade_all(client, [_entry("one", "s1")], log, scope="https://prod.example")
    assert client.calls == ["one"]


def test_invalid_resolution_does_not_partially_record_owner_decisions(tmp_path: Path) -> None:
    log = tmp_path / "log"
    client = _FakeRegrader({})
    batch.regrade_all(client, [_entry(None, "s1")], log)
    saved = log.read_bytes()
    key = json.loads(saved)["entry_key"]
    with pytest.raises(batch.LogError):
        batch.regrade_all(client, [], log, resolutions={key: "done", "typo": "done"})
    assert log.read_bytes() == saved


def test_apply_exit_status_stays_nonzero_on_uncached_reruns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import screamingface as sf

    class Client(_FakeRegrader):
        scoreboard_url = "http://board"
        authenticated = True

    client = Client({})
    monkeypatch.setattr(sf, "Client", lambda **kwargs: client)
    monkeypatch.setattr(batch, "find_entries", lambda *args: [_entry(None, "s1")])
    argv = ["--apply", "--benchmark", _BOARD, "--log", str(tmp_path / "log")]
    assert batch.main(argv) == batch.main(argv) == 1
    assert client.calls == []


def test_waiting_guard_does_not_hide_previously_unresolved_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import screamingface as sf

    class Client(_FakeRegrader):
        scoreboard_url = "http://board"
        authenticated = True

    client = Client({})
    monkeypatch.setattr(sf, "Client", lambda **kwargs: client)
    monkeypatch.setattr(batch, "board_revision", lambda *args: _OLD)
    log = tmp_path / "log"
    argv = ["--apply", "--when-revision", f"{_BOARD}={_NEW}", "--log", str(log)]
    assert batch.main(argv) == 0
    batch.regrade_all(client, [_entry(None, "s1")], log, scope=client.scoreboard_url)
    assert batch.main(argv) == 1


@pytest.mark.parametrize(
    "damage",
    [
        {"spec_id": None},
        {"new_score_id": None},
        {"outcome": "owner_resolved", "note": None},
    ],
)
def test_complete_records_with_invalid_field_types_cannot_mark_an_entry_resolved(
    tmp_path: Path, damage: dict[str, object]
) -> None:
    log = tmp_path / "log"
    client = _FakeRegrader({"one": None})
    batch.regrade_all(client, [_entry("one", "s1")], log)
    record = json.loads(log.read_text())
    record.update(damage)
    log.write_text(json.dumps(record) + "\n")
    saved = log.read_bytes()
    with pytest.raises(batch.LogError):
        batch.regrade_all(client, [], log)
    assert log.read_bytes() == saved
