from __future__ import annotations

import json
from pathlib import Path

from harness.trace_evidence import unattributed_gateway_lines

from workbench.evidence import FileLogSource, collect

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
