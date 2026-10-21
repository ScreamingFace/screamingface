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
    assert chain.missing(["engine", "aigateway"]) == [f"aigateway: trace {TID} absent"]
    assert chain.lifecycle == {"scheduled": True, "terminated": True}


def test_a_missing_log_file_is_a_missing_hop_not_a_crash(tmp_path: Path) -> None:
    chain = collect([TID], [FileLogSource("engine", tmp_path / "absent.log")])
    assert chain.missing(["engine"]) == [f"engine: trace {TID} absent"]


def test_no_trace_ids_means_every_hop_is_missing(tmp_path: Path) -> None:
    engine = _src(tmp_path, "engine", f"anything {TID}\n")
    assert collect([], [engine]).missing(["engine"]) == ["engine: no trace id to match"]


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
    assert chain.missing(["engine", "aigateway"]) == [f"aigateway: trace {TID} absent"]


def test_service_source_reads_empty_when_the_log_is_absent(tmp_path: Path) -> None:
    assert ServiceLogSource("engine", tmp_path / "nope.log", "engine").read() == ""


def _engine_with(tmp_path: Path, *ids: str) -> FileLogSource:
    return _src(tmp_path, "engine", "".join(f"run scheduled trace_id={t}\n" for t in ids))


def test_every_reported_trace_id_must_be_in_every_required_hop(tmp_path: Path) -> None:
    # Engine has both ids, the gateway only TID: one id present is not the chain for both.
    engine = _engine_with(tmp_path, TID, OTHER)
    gateway = _src(tmp_path, "aigateway", f"gateway_call_id=c1 trace_id={TID} POST\n")
    chain = collect([TID, OTHER], [engine, gateway])
    assert chain.missing(["engine", "aigateway"]) == [f"aigateway: trace {OTHER} absent"]
    hops = {h["name"]: h for h in chain.to_json()["hops"]}
    assert hops["aigateway"]["found"] is False
    assert hops["aigateway"]["missing_ids"] == [OTHER]
    assert hops["engine"]["found"] is True


def test_missing_names_each_absent_id_in_each_hop(tmp_path: Path) -> None:
    engine = _engine_with(tmp_path, TID)
    gateway = _src(tmp_path, "aigateway", "")
    chain = collect([TID, OTHER], [engine, gateway])
    assert chain.missing(["engine", "aigateway"]) == [
        f"engine: trace {OTHER} absent",
        f"aigateway: trace {TID} absent",
        f"aigateway: trace {OTHER} absent",
    ]


def test_a_required_hop_with_no_source_is_named(tmp_path: Path) -> None:
    chain = collect([TID], [_engine_with(tmp_path, TID)])
    assert chain.missing(["engine", "aigateway"]) == ["aigateway: no log source"]


def test_a_gateway_that_emits_no_call_ids_fails(tmp_path: Path) -> None:
    # The id is present, but on no identified line: the hop exists, the call is unattributable.
    engine = _engine_with(tmp_path, TID)
    gateway = _src(tmp_path, "aigateway", f"POST /v1/chat/completions trace_id={TID}\n")
    chain = collect([TID], [engine, gateway])
    assert chain.missing(["engine", "aigateway"]) == [
        f"aigateway: trace {TID} on no line carrying gateway_call_id"
    ]


def test_a_call_id_on_another_runs_line_does_not_identify_this_run(tmp_path: Path) -> None:
    engine = _engine_with(tmp_path, TID)
    gateway = _src(
        tmp_path,
        "aigateway",
        f"gateway_call_id=c9 trace_id={OTHER} POST\nPOST /v1/chat/completions trace_id={TID}\n",
    )
    chain = collect([TID], [engine, gateway])
    assert chain.missing(["engine", "aigateway"]) == [
        f"aigateway: trace {TID} on no line carrying gateway_call_id"
    ]


def test_call_id_rule_applies_only_when_aigateway_is_required(tmp_path: Path) -> None:
    gateway = _src(tmp_path, "aigateway", f"POST trace_id={TID}\n")
    chain = collect([TID], [_engine_with(tmp_path, TID), gateway])
    assert chain.missing(["engine"]) == []


def test_identified_gateway_line_for_every_id_passes(tmp_path: Path) -> None:
    engine = _engine_with(tmp_path, TID, OTHER)
    gateway = _src(
        tmp_path,
        "aigateway",
        f"gateway_call_id=c1 trace_id={TID} POST\ngateway_call_id=c2 trace_id={OTHER} POST\n",
    )
    chain = collect([TID, OTHER], [engine, gateway])
    assert chain.missing(["engine", "aigateway"]) == []
    assert chain.reasons(["engine", "aigateway"]) == []


def test_reasons_join_missing_and_unattributed_lines(tmp_path: Path) -> None:
    engine = _engine_with(tmp_path, TID)
    gateway = _src(
        tmp_path,
        "aigateway",
        f"gateway_call_id=c1 trace_id={TID} a\nanonymous mid-request\ngateway_call_id=c1 b\n",
    )
    chain = collect([TID, OTHER], [engine, gateway])
    assert chain.reasons(["engine", "aigateway"]) == [
        f"trace chain incomplete: engine: trace {OTHER} absent; aigateway: trace {OTHER} absent",
        "1 aigateway lines lack gateway_call_id",
    ]


def test_reasons_skip_the_chain_when_no_id_was_reported(tmp_path: Path) -> None:
    # check_result already fails a run with no id; the chain must not double-report it.
    chain = collect([], [_engine_with(tmp_path, TID)])
    assert chain.reasons(["engine"]) == []


# Finding 2 (PR #1455 review): an id is matched as the exact `trace_id=<32 hex>` token, never
# as a substring of a longer value, and the excerpt shown is chosen by the same parser.


def test_a_trace_id_embedded_in_a_longer_value_is_not_a_match(tmp_path: Path) -> None:
    engine = _src(tmp_path, "engine", f"run scheduled trace_id=aa{TID}bb\n")
    gateway = _src(tmp_path, "aigateway", f"gateway_call_id=x trace_id=aa{TID}bb POST\n")
    chain = collect([TID], [engine, gateway])
    assert chain.missing(["engine", "aigateway"]) == [
        f"engine: trace {TID} absent",
        f"aigateway: trace {TID} absent",
    ]
    assert all(h.lines == () for h in chain.hops)
    assert chain.lifecycle == {"scheduled": False, "terminated": False}


def test_a_bare_id_or_another_key_is_not_a_trace_id_token(tmp_path: Path) -> None:
    engine = _src(
        tmp_path,
        "engine",
        f"mentions {TID} in prose\nparent_trace_id={TID}\nrun scheduled trace_id={TID}x\n",
    )
    chain = collect([TID], [engine])
    assert chain.missing(["engine"]) == [f"engine: trace {TID} absent"]
    assert chain.hops[0].lines == ()


def test_an_uppercase_trace_id_token_is_not_the_lowercase_id(tmp_path: Path) -> None:
    engine = _src(tmp_path, "engine", f"run scheduled trace_id={TID.upper()}\n")
    assert collect([TID], [engine]).missing(["engine"]) == [f"engine: trace {TID} absent"]


def test_excerpt_lines_are_exactly_the_lines_the_verdict_counted(tmp_path: Path) -> None:
    good = f"2026-10-16T10:00:00+00:00 INFO run scheduled topic=t trace_id={TID} job_name=j"
    decoy = f"gateway_call_id=x trace_id=aa{TID}bb"
    engine = _src(tmp_path, "engine", f"{decoy}\n{good}\n")
    chain = collect([TID], [engine])
    assert chain.hops[0].lines == (good,)
    assert chain.hops[0].found_ids == (TID,)


def test_a_call_id_line_with_a_lookalike_trace_does_not_identify_the_run(tmp_path: Path) -> None:
    gateway = _src(
        tmp_path,
        "aigateway",
        f"gateway_call_id=c1 trace_id=aa{TID}bb POST\nPOST trace_id={TID}\n",
    )
    chain = collect([TID], [_engine_with(tmp_path, TID), gateway])
    assert chain.missing(["engine", "aigateway"]) == [
        f"aigateway: trace {TID} on no line carrying gateway_call_id"
    ]


def test_trace_id_tokens_parses_every_exact_token_on_a_line() -> None:
    from workbench.evidence import trace_id_tokens

    line = f"a trace_id={TID} b trace_id={OTHER} trace_id=aa{TID} trace_id={TID[:-1]}"
    assert trace_id_tokens(line) == frozenset({TID, OTHER})
    assert trace_id_tokens(f"trace_id={TID}") == frozenset({TID})
    assert trace_id_tokens("") == frozenset()
