from __future__ import annotations

import json
from pathlib import Path

from harness.trace_evidence import unattributed_gateway_lines

from workbench.evidence import FileLogSource, ServiceLogSource, collect

TID = "4bf92f3577b34da6a3ce929d0e0e4736"
OTHER = "00f067aa0ba902b7aaaaaaaaaaaaaaaa"


def _src(tmp_path: Path, name: str, text: str) -> FileLogSource:
    path = tmp_path / f"{name}.log"
    path.write_text(text)
    return FileLogSource(name, path)


def test_hops_are_found_only_by_this_runs_trace_id(tmp_path: Path) -> None:
    engine = _src(
        tmp_path,
        "engine",
        f"run scheduled topic=t trace_id={TID} job_name=j\n"
        f"run terminated topic=t trace_id={TID} outcome=ok\n",
    )
    gateway = _src(tmp_path, "aigateway", f"gateway_call_id=c1 trace_id={OTHER} POST\n")
    chain = collect([TID], [engine, gateway])
    assert chain.missing(["engine", "aigateway"]) == ["aigateway"]
    assert chain.lifecycle == {"scheduled": True, "terminated": True}


def test_a_missing_log_file_is_a_missing_hop_not_a_crash(tmp_path: Path) -> None:
    chain = collect([TID], [FileLogSource("engine", tmp_path / "absent.log")])
    assert chain.missing(["engine"]) == ["engine"]


def test_no_trace_ids_means_every_hop_is_missing(tmp_path: Path) -> None:
    engine = _src(tmp_path, "engine", f"anything {TID}\n")
    assert collect([], [engine]).missing(["engine"]) == ["engine"]


def test_gateway_lines_inside_the_request_window_need_a_call_id() -> None:
    text = "startup\ngateway_call_id=a x\nno id here\ngateway_call_id=a y\nshutdown\n"
    identified, anonymous = unattributed_gateway_lines(text)
    assert identified == 2
    assert anonymous == ["no id here"]


def test_chain_json_is_serialisable_and_names_each_hop(tmp_path: Path) -> None:
    chain = collect([TID], [_src(tmp_path, "engine", f"x trace_id={TID}\n")])
    payload = json.loads(json.dumps(chain.to_json()))
    assert payload["hops"][0]["name"] == "engine"
    assert payload["hops"][0]["found"] is True


def test_service_source_keeps_only_its_tagged_runtime_lines(tmp_path: Path) -> None:
    log = tmp_path / "runtime.log"
    log.write_text(
        f"2026-10-16T10:00:00+00:00 [engine] run scheduled trace_id={TID}\n"
        f"2026-10-16T10:00:01+00:00 [gateway] gateway_call_id=c1 trace_id={TID} POST\n"
        "2026-10-16T10:00:02+00:00 [supervisor] ScreamingFace is ready.\n"
        "2026-10-16T10:00:03+00:00 [scoreboard] seeded\n"
        "a stray untagged line [engine] in the middle\n"
    )
    engine = ServiceLogSource("engine", log, service="engine")
    gateway = ServiceLogSource("aigateway", log, service="gateway")
    assert engine.read().splitlines() == [
        f"2026-10-16T10:00:00+00:00 [engine] run scheduled trace_id={TID}"
    ]
    assert gateway.read().splitlines() == [
        f"2026-10-16T10:00:01+00:00 [gateway] gateway_call_id=c1 trace_id={TID} POST"
    ]


def test_service_sources_split_one_runtime_log_into_separate_hops(tmp_path: Path) -> None:
    log = tmp_path / "runtime.log"
    log.write_text(
        f"2026-10-16T10:00:00+00:00 [engine] run scheduled trace_id={TID}\n"
        "2026-10-16T10:00:01+00:00 [gateway] POST /v1/chat/completions\n"
    )
    chain = collect(
        [TID],
        [ServiceLogSource("engine", log, "engine"), ServiceLogSource("aigateway", log, "gateway")],
    )
    assert chain.missing(["engine", "aigateway"]) == ["aigateway"]


def test_service_source_reads_empty_when_the_log_is_absent(tmp_path: Path) -> None:
    assert ServiceLogSource("engine", tmp_path / "nope.log", "engine").read() == ""
