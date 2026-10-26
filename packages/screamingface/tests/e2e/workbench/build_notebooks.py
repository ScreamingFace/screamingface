"""Generate the workbench notebooks (e2e workbench spec §3.3).

The notebooks under ``notebooks/`` are BUILD OUTPUT: committed output-free and byte-identical
to what this module renders (``test_build_notebooks`` enforces it). Edit the builder, then run::

    uv run python tests/e2e/workbench/build_notebooks.py          # regenerate
    uv run python tests/e2e/workbench/build_notebooks.py --check  # exit 1 on drift

WHY generated: the replay recipe must be the exact candidate the golden recorded, so it is
rendered from the golden file rather than hand-copied into a notebook where it could drift.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import nbformat

# Run as a script, ``tests/e2e`` is not on sys.path; under pytest it already is.
_E2E_ROOT: Final = Path(__file__).resolve().parents[1]
if str(_E2E_ROOT) not in sys.path:
    sys.path.insert(0, str(_E2E_ROOT))

from harness._gating import GOLDENS_DIR  # noqa: E402
from harness.goldens import GoldenModelSpec, GoldenReport, load_golden  # noqa: E402

from workbench.evidence import _TRACE_ID_TOKEN  # noqa: E402  # pyright: ignore[reportPrivateUsage]
from workbench.runner import RESULT_PREFIX, RESULT_TAG  # noqa: E402

NOTEBOOK_DIR: Final = Path(__file__).resolve().parent / "notebooks"


def notebooks_for(target: str) -> list[Path]:
    """The committed notebooks that DECLARE ``target`` in their workbench metadata, sorted.

    WHY at collection: a notebook that is not meant for a target must not be collected for it
    at all; a runtime skip would be failed by SCREAMINGFACE_WORKBENCH_REQUIRE_ALL.
    """
    import nbformat

    return [
        path
        for path in sorted(NOTEBOOK_DIR.glob("*.ipynb"))
        if target
        in nbformat.read(path, as_version=4).metadata.get("workbench", {}).get("targets", [])
    ]


_INDENT: Final = "    "
_WRAP_AT: Final = 72  # string literals longer than this split into implicit concatenation
_KERNELSPEC: Final = {"name": "python3", "display_name": "Python 3", "language": "python"}


# --- golden recipe → Python source ------------------------------------------------------------


def _q(value: str) -> str:
    """``repr`` in ruff-format's preferred double quotes (so the notebook passes format --check)."""
    literal = repr(value)
    if literal.startswith("'") and '"' not in value:
        # repr picks single quotes here only when the value has no quote at all, so the
        # body needs no re-escaping.
        literal = f'"{literal[1:-1]}"'
    return literal


def _value(value: str | int | float | bool) -> str:
    return _q(value) if isinstance(value, str) else repr(value)


def _dict(mapping: Mapping[str, str | int | float | bool]) -> str:
    return "{" + ", ".join(f"{_q(key)}: {_value(val)}" for key, val in mapping.items()) + "}"


def _str(value: str, indent: str) -> str:
    """A deterministic string literal; long ones split on spaces into ``("…" "…")``."""
    if len(_q(value)) <= _WRAP_AT:
        return _q(value)
    chunks: list[str] = []
    for word in re.findall(r"\S*\s*", value):  # words keep their trailing whitespace
        if chunks and len(chunks[-1]) + len(word) <= _WRAP_AT - 4:
            chunks[-1] += word
        elif word:
            chunks.append(word)
    inner = indent + _INDENT
    body = "".join(f"{inner}{_q(chunk)}\n" for chunk in chunks)
    return f"(\n{body}{indent})"


def _call(func: str, args: Sequence[str], indent: str) -> str:
    """``func(\\n    arg,\\n)`` — one argument per line, trailing commas, ruff-format shaped."""
    inner = indent + _INDENT
    body = "".join(f"{inner}{arg},\n" for arg in args)
    return f"{func}(\n{body}{indent})"


def _list(items: Sequence[str], indent: str) -> str:
    inner = indent + _INDENT
    body = "".join(f"{inner}{item},\n" for item in items)
    return f"[\n{body}{indent}]"


def _model(spec: GoldenModelSpec, indent: str) -> str:
    """Mirrors ``harness.goldens.spec_model``: route, then prompt and params only when set."""
    inner = indent + _INDENT
    args = [_q(spec.model)]
    if spec.prompt is not None:
        args.append(f"prompt={_str(spec.prompt, inner)}")
    if spec.params:
        args.append(f"params={_dict(spec.params)}")
    return _call("sf.Model", args, indent)


def _render_loop(golden: GoldenReport) -> str:
    assert golden.judge_spec is not None and golden.max_rounds is not None  # validator-held
    members = _list([_model(spec, _INDENT * 2) for spec in golden.member_specs], _INDENT)
    return _call(
        "sf.CorrectiveLoop",
        [
            members,
            f"judge={_model(golden.judge_spec, _INDENT)}",
            f"max_rounds={golden.max_rounds!r}",
        ],
        "",
    )


def _render_fusion(golden: GoldenReport) -> str:
    members = _list([_q(route) for route in golden.models], _INDENT)
    return _call(
        "sf.Fusion",
        [members, f"name={_q(golden.recipe or '')}", f"synthesizer={_q(golden.synthesizer or '')}"],
        "",
    )


def _render_model(golden: GoldenReport) -> str:
    if len(golden.models) != 1:
        raise ValueError(f"a 'model' golden names exactly one model, got {len(golden.models)}")
    return f"sf.Model({_q(golden.models[0])})"


_RENDERERS: Final[dict[str, Callable[[GoldenReport], str]]] = {
    "corrective_loop": _render_loop,
    "fusion": _render_fusion,
    "model": _render_model,
}


def render_golden_candidate(golden: GoldenReport) -> str:
    """Python source binding ``candidate`` to exactly what ``build_candidate(golden)`` builds.

    Expects ``sf`` (``import screamingface as sf``) in scope. Literals are ``repr``-rendered
    (double-quoted for ruff format), so the output is a pure function of the golden.
    """
    return f"candidate = {_RENDERERS[golden.kind](golden)}\n"


# --- notebook cells ---------------------------------------------------------------------------


def _code(source: str, *tags: str) -> nbformat.NotebookNode:
    cell = nbformat.v4.new_code_cell(source.strip("\n"))
    if tags:
        cell.metadata["tags"] = list(tags)
    return cell


def _markdown(source: str) -> nbformat.NotebookNode:
    return nbformat.v4.new_markdown_cell(source.strip("\n"))


def _require_one_result(cells: list[nbformat.NotebookNode]) -> None:
    """Review finding 6: the runner refuses anything but ONE ``workbench-result`` cell printing
    ONE marker, so a notebook of any other shape must never be built."""
    tagged = [c for c in cells if RESULT_TAG in c.metadata.get("tags", [])]
    if len(tagged) != 1:
        raise ValueError(f"exactly one cell tagged {RESULT_TAG!r} required, found {len(tagged)}")
    markers = sum(c.source.count(RESULT_PREFIX) for c in cells)
    if markers != 1 or tagged[0].source.count(RESULT_PREFIX) != 1:
        raise ValueError(
            f"exactly one {RESULT_PREFIX} marker required, in the {RESULT_TAG!r} cell;"
            f" found {markers} in the notebook"
        )


def _notebook(stem: str, cells: list[nbformat.NotebookNode], meta: dict[str, Any]) -> Any:
    _require_one_result(cells)
    nb = nbformat.v4.new_notebook(cells=cells)
    nb.metadata["kernelspec"] = dict(_KERNELSPEC)
    nb.metadata["workbench"] = meta
    for i, cell in enumerate(nb.cells):
        cell["id"] = f"{stem}-{i:02d}"  # fixed ids: rebuilds are byte-identical
    return nb


_QUICKSTART_TITLE = """
# Quickstart: one evaluation, end to end

Builds one candidate, evaluates it on `BENCHMARK`, and asserts that the client minted a trace
id, the candidate compiled to url4, and the score sits in the hand-set `SCORE_BAND`. The
`workbench-result` cell reports the trace ids right after the evaluation, before any
assertion, so a failing check still leaves them in the evidence. If `client.evaluate()` itself
raises, the SDK error's `trace_id` is reported instead and the error re-raised after the
result cell. The workbench then requires each id to appear in the engine and aigateway logs.

On `replay` the recipe is the golden ifeval recipe (served from the recorded cache, no spend);
on `local` it is the authored open-source fusion below, run with your OpenRouter key.
"""

_QUICKSTART_PARAMETERS = """
ENGINE_URL = "http://127.0.0.1:9108"
SCOREBOARD_URL = "http://127.0.0.1:9106"  # always explicit; replay has none and never calls it
RECIPE = "authored"  # "golden" on replay: the exact recipe the ifeval tape recorded
BENCHMARK = "ifeval"
LIMIT = 1
SCORE_BAND = [0.0, 1.0]  # hand-set sanity band (owner decision 2026-10-16)
EXPECT_CACHED = False
EVENTS_PATH = ""  # set by the workbench: SDK events (and the report files beside them)
"""

_QUICKSTART_CLIENT = """
import json
import os

import screamingface as sf

if not SCOREBOARD_URL:  # spec §3.1: never fall back to the hosted leaderboard
    raise ValueError("SCOREBOARD_URL must be explicit")
client = sf.Client(engine_url=ENGINE_URL, scoreboard_url=SCOREBOARD_URL)
if os.environ.get("OPENROUTER_API_KEY") and RECIPE == "authored":
    client.connect("openrouter", api_key=os.environ["OPENROUTER_API_KEY"])
"""

_QUICKSTART_AUTHORED = """
else:
    ANSWER = (
        "Answer the request accurately and completely. "
        "Follow every instruction and formatting constraint in the request."
    )
    SYNTH = (
        "Produce the single best answer to the original request by combining the panel "
        "drafts. Preserve every instruction and formatting constraint stated in the "
        "original prompt."
    )
    candidate = sf.Fusion(
        [
            sf.Model("openrouter/deepseek/deepseek-v4-pro", prompt=ANSWER),
            sf.Model("openrouter/qwen/qwen3-coder", prompt=ANSWER),
        ],
        name="best_open_source",
        synthesizer=sf.Model("openrouter/z-ai/glm-5.2", prompt=SYNTH),
    )
candidate
"""

# WHY the recorder is imported only when EVENTS_PATH is set: outside the workbench the notebook
# is a plain SDK quickstart; inside it, the private kernel has `tests/e2e` on its PYTHONPATH
# (runner.py), and `workbench.telemetry_recorder` redacts every event before it is written.
#
# WHY catch the SDK error here and re-raise it after the result cell (review gap (a)): a run
# minted before the failure carries its id on `sf.ScreamingFaceError.trace_id` (OME-967), and
# the bundle can only correlate the logs of that run if the result cell gets to report it.
# Only the SDK's public error is held back; anything else is a notebook bug and fails here.
_QUICKSTART_EVALUATE = """
recorder = None
if EVENTS_PATH:  # the workbench records every SDK event, redacted, into the run's bundle
    from workbench.telemetry_recorder import EventRecorder

    recorder = EventRecorder(EVENTS_PATH)
report = None
evaluate_error = None
try:
    report = client.evaluate(
        candidate, benchmark=BENCHMARK, limit=LIMIT, progress=False, on_event=recorder
    )
except sf.ScreamingFaceError as exc:
    evaluate_error = exc
    report = getattr(exc, "partial_report", None)  # ExecutionError: the Candidates that ran
"""

# WHY after the result cell: a failing assert must still leave the trace ids in the bundle
# (Review Focus 1), so the workbench can check the chain of the run that misbehaved.
_QUICKSTART_ASSERT = """
if evaluate_error is not None:
    raise evaluate_error
(result,) = list(report.candidates)
assert result.trace_id, "the client minted no trace id (OME-967)"
assert result.url4, "the candidate compiled to no url4"
assert result.score is not None and SCORE_BAND[0] <= result.score <= SCORE_BAND[1], result.score
if EXPECT_CACHED:
    assert result.cache_hits > 0, "expected a warm cache on this target"
report
"""

# WHY `recorder.finish` after the marker: the trace ids must reach the evidence first; finish()
# writes report.json and accounting.json, redacted, and records (never raises) any failure.
#
# WHY `_usd`: the SDK's None means nothing priceable was observed, which is not zero, so it
# stays null in the payload (str(None) would read as the amount "None").
_QUICKSTART_RESULT = """
def _usd(amount):
    return None if amount is None else str(amount)


ran = list(report.candidates) if report is not None else []
error_trace_id = evaluate_error.trace_id if evaluate_error is not None else None
trace_ids = [c.trace_id for c in ran if c.trace_id] + [error_trace_id]
print(
    "WORKBENCH_RESULT="
    + json.dumps(
        {
            "trace_ids": [t for t in dict.fromkeys(trace_ids) if t],
            "run_ids": [str(c.run_id) for c in ran],
            "candidates": {
                c.name: {
                    "score": c.score,
                    "cost_usd": _usd(c.usage.cost_usd),
                    "cache_hits": c.cache_hits,
                    "cache_saved_cost_usd": _usd(c.cache_saved_cost_usd),
                }
                for c in ran
            },
            "evaluate_error": None
            if evaluate_error is None
            else {"type": type(evaluate_error).__name__, "code": evaluate_error.code},
        }
    )
)
if recorder is not None:  # report.json + accounting.json beside the events; never raises
    recorder.finish(report)
"""


def _quickstart() -> Any:
    golden = load_golden(GOLDENS_DIR / "ifeval.golden.json")
    recipe = (
        'if RECIPE == "golden":\n'
        + textwrap.indent(render_golden_candidate(golden), _INDENT)
        + _QUICKSTART_AUTHORED.strip("\n")
    )
    cells = [
        _markdown(_QUICKSTART_TITLE),
        _code(_QUICKSTART_PARAMETERS, "parameters"),
        _code(_QUICKSTART_CLIENT),
        _code(recipe),
        _code(_QUICKSTART_EVALUATE),
        _code(_QUICKSTART_RESULT, RESULT_TAG),
        _code(_QUICKSTART_ASSERT),
        _code("client.close()"),
    ]
    meta = {"targets": ["replay", "local"], "required_result": ["trace_ids"]}
    return _notebook("quickstart", cells, meta)


# --- debug_failing_run (unit 7, spec §3.7) ------------------------------------------------------
#
# A notebook that fails ON PURPOSE, then teaches how to debug it. Every fact it relies on was
# discovered on replay, keyless, over 3 identical runs (unit 7 ledger, Task 2), never guessed:
# `client.evaluate()` returns; the run terminates `succeeded`; case 1 fails with
# `upstream_error` at stage `candidate` (the gateway's 404 `profile_not_found`); 2 ERROR Logs
# name the failing model; the failing url4 Spans name only the HEALTHY member; 2 Usage events
# and one cache hit prove the healthy member ran.
#
# WHY replay only: the unservable route is a declared Engine route the ifeval tape never
# recorded. On `local` with a key it is a real, billed model, so the run would pass (red as an
# "unexpected pass") and spend; a non-catalog id is refused at preflight with no trace (ledger,
# Probe 1), which the verdict rejects. Owner decision pending (ledger, "Open for the owner").

DEBUG_STEM: Final = "debug_failing_run"
DEBUG_UNSERVABLE_MODEL: Final = "openrouter/openai/gpt-5.5"
#: The declaration the verdict holds the run to (spec §3.7); the parameters cell renders the same.
DEBUG_EXPECT: Final = {"outcome": "fail", "failure_codes": ["upstream_error"], "stage": "candidate"}

_DEBUG_TITLE = """
# Debugging a failing run with telemetry

This notebook **fails on purpose**. It runs a two-member fusion where one member is a model the
gateway cannot serve, then walks from the symptom to the root cause:

1. run the fusion;
2. read the symptom in the report;
3. find the run's trace id;
4. read the SDK telemetry: failing spans, ERROR logs, usage;
5. follow the trace id into the gateway logs;
6. fix the recipe.

It runs on `replay` only: the healthy member is served from the recorded ifeval cache, and the
unservable member is a route the tape never recorded, so it fails the same way every time and
never reaches a provider. The workbench passes it only when it fails exactly as its metadata
declares (`workbench.expect`) and the evidence is complete: the trace chain, and the error in
the telemetry.
"""

_DEBUG_PARAMETERS = f"""
ENGINE_URL = "http://127.0.0.1:9108"
SCOREBOARD_URL = "http://127.0.0.1:9106"  # always explicit; replay has none and never calls it
BENCHMARK = "ifeval"
LIMIT = 1
UNSERVABLE_MODEL = {_q(DEBUG_UNSERVABLE_MODEL)}  # a declared route the ifeval tape never recorded
EXPECTED_CODE = {_q(DEBUG_EXPECT["failure_codes"][0])}  # discovered on replay, never guessed
EXPECTED_STAGE = {_q(str(DEBUG_EXPECT["stage"]))}
EVENTS_PATH = ""  # set by the workbench: SDK events (and the report files beside them)
GATEWAY_LOG = ""  # optional: the stack's aigateway.log, to filter for this run's lines
"""

_DEBUG_CLIENT = """
import dataclasses
import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import screamingface as sf

if not SCOREBOARD_URL:  # spec §3.1: never fall back to the hosted leaderboard
    raise ValueError("SCOREBOARD_URL must be explicit")
client = sf.Client(engine_url=ENGINE_URL, scoreboard_url=SCOREBOARD_URL)
"""

_DEBUG_RUN_MD = """
## 1. Run the fusion

Two members answer, one synthesizer combines. The first member is exactly the request the
ifeval tape recorded, so the replay gateway serves it from cache. The second member is
`UNSERVABLE_MODEL`: the Engine knows the route, but the replay gateway holds no answer and no
key for it, so it refuses the call (`404 profile_not_found`) without any live request.
"""

# WHY a tee: the workbench records the events redacted into EVENTS_PATH (section 4 reads that
# copy); outside the workbench the same events are kept in memory, so the tutorial still runs.
_DEBUG_EVALUATE = """
recorder = None
if EVENTS_PATH:  # the workbench records every SDK event, redacted, into the run's bundle
    from workbench.telemetry_recorder import EventRecorder

    recorder = EventRecorder(EVENTS_PATH)
seen = []  # outside the workbench, the same events in memory


def on_event(event):
    seen.append(event)
    if recorder is not None:
        recorder(event)


report = None
evaluate_error = None
try:
    report = client.evaluate(
        candidate, benchmark=BENCHMARK, limit=LIMIT, progress=False, on_event=on_event
    )
except sf.ScreamingFaceError as exc:
    evaluate_error = exc
    report = getattr(exc, "partial_report", None)  # ExecutionError: the Candidates that ran
"""

_DEBUG_RESULT_MD = """
### Record the evidence first

Before any check, the next cell reports the run's trace ids and failure codes to the workbench
(the single `WORKBENCH_RESULT` line). If a later check fails, the evidence of the run that
misbehaved is already in the bundle.
"""

_DEBUG_RESULT = """
ran = list(report.candidates) if report is not None else []
error_trace_id = evaluate_error.trace_id if evaluate_error is not None else None
trace_ids = [c.trace_id for c in ran if c.trace_id] + [error_trace_id]
failure_codes = sorted(
    {f.code for c in ran for f in c.failures}
    | {f.code for c in ran for case in c.cases for f in case.failures}
)
print(
    "WORKBENCH_RESULT="
    + json.dumps(
        {
            "trace_ids": [t for t in dict.fromkeys(trace_ids) if t],
            "run_ids": [str(c.run_id) for c in ran],
            "failure_codes": failure_codes,
            "evaluate_error": None
            if evaluate_error is None
            else {"type": type(evaluate_error).__name__, "code": evaluate_error.code},
        }
    )
)
if recorder is not None:  # report.json + accounting.json beside the events; never raises
    recorder.finish(report)
"""

_DEBUG_SYMPTOM_MD = """
## 2. Symptom: the report

`client.evaluate()` did **not** raise, and the run terminated `succeeded`: a member failing is a
case failure, not a run failure. The report says which case failed, at which stage and with which
code. The candidate has no score, because its only case has no output: with the default
`quorum="all"` one failed member fails the whole case before the synthesizer runs. So the
healthy member's answer is not in the report; its cache hit is, and section 4 shows its usage.

Only the code, stage and source code are printed. A failure's `message` is provider text, which on
a live target can quote request details, so it is never printed here.
"""

_DEBUG_SYMPTOM = """
if evaluate_error is not None:
    raise evaluate_error  # this recipe fails inside the run; evaluate() itself must not raise
(result,) = list(report.candidates)
failed = [case for case in result.cases if case.failures]
for case in failed:
    for failure in case.failures:
        source = dict(failure.metadata.get("source_error") or {})
        print(
            f"case {case.case_id}: status={case.status} stage={failure.stage} "
            f"code={failure.code} retryable={failure.retryable} "
            f"source_code={source.get('source_code')}"
        )
print(f"score={result.score} cache_hits={result.cache_hits}")
observed = sorted({(f.code, f.stage) for case in failed for f in case.failures})
assert observed, "unexpected pass: no case failed"
assert observed == [(EXPECTED_CODE, EXPECTED_STAGE)], observed
assert result.cache_hits >= 1, "the healthy member was not served from the cache"
"""

_DEBUG_TRACE_MD = """
## 3. The trace id

Every run has one trace id. It is on each candidate of the report (`result.trace_id`). When
`client.evaluate()` raises after the run started, the SDK error carries it instead
(`exc.trace_id`). The engine, the gateway and the recorded spans all carry the same id, so it is
the key to everything that follows.
"""

_DEBUG_TRACE = """
trace_id = result.trace_id
assert trace_id and re.fullmatch(r"[0-9a-f]{32}", trace_id), trace_id
print("trace id:", trace_id)
"""

_DEBUG_TELEMETRY_MD = """
## 4. Telemetry: what the SDK saw

The SDK streams events while the run executes: `Span` (url4 nodes), `Log`, `Usage`. The
workbench records them, redacted, into the run's bundle (`events.jsonl`); the cell below loads
that copy. Two filters find the error:

- **failing spans**: `status == "error"` (or a refusal);
- **ERROR logs**: `severity_number >= 17`.

Read them together. The failing spans are the url4 nodes the failure propagated through, and the
model-bearing one names the **healthy** member (its call succeeded, from cache). Only the ERROR
`Log` "Model call failed" names the failing model. Its `sf.activity.failure_code` is the
activity's own code, not the report's: trust the report for the code, and the log for the model.
"""


def _debug_telemetry() -> str:
    return """
def as_row(value):
    \"\"\"An in-memory SDK event as the same plain tree the recorder writes.\"\"\"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        row = {f.name.lstrip("_"): getattr(value, f.name) for f in dataclasses.fields(value)}
        value = {"kind": value.kind, **row} if hasattr(value, "kind") else row
    if isinstance(value, Mapping):
        return {str(k): as_row(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [as_row(v) for v in value]
    return value


if EVENTS_PATH:  # the workbench's recorded copy, already redacted
    lines = Path(EVENTS_PATH).read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
else:
    events = [as_row(event) for event in seen]
print(f"{len(events)} events:", dict(Counter(e["kind"] for e in events)))

failing_spans = [
    e for e in events if e["kind"] == "span" and (e.get("status") == "error" or e.get("refusal"))
]
error_logs = [e for e in events if e["kind"] == "log" and e.get("severity_number", 0) >= 17]
for span in failing_spans:
    name = str(span.get("name"))
    name = name if len(name) <= 48 else name[:45] + "..."  # url4 map nodes name the expression
    print(
        f"span {name} [{span.get('operation')}]: status={span.get('status')} "
        f"provider={span.get('provider')} model={span.get('request_model')} "
        f"finish={list(span.get('finish_reasons') or [])} cache={span.get('cache_status')}"
    )
for log in error_logs:
    attrs = log.get("attributes") or {}
    print(
        f"{log.get('severity_text')} {log.get('body')!r}: "
        f"model={attrs.get('sf.activity.model_id')} kind={attrs.get('sf.activity.kind')} "
        f"failure_code={attrs.get('sf.activity.failure_code')}"
    )
assert error_logs, "no ERROR log: the telemetry missed the failure"
failing_models = {(log.get("attributes") or {}).get("sf.activity.model_id") for log in error_logs}
assert UNSERVABLE_MODEL in failing_models, failing_models
"""


_DEBUG_USAGE_MD = """
`Usage` events are the accounting per model. A `Usage` row for the healthy member proves it ran
even though its answer never reached the report. On replay its counts and cost are zero: the
answer came from the cache.
"""

_DEBUG_USAGE = """
usage = [e for e in events if e["kind"] == "usage"]
for row in usage:
    amounts = row.get("usage") or {}
    print(
        f"usage scope={row.get('scope')} provider={row.get('provider')} "
        f"model={row.get('model')} input_tokens={amounts.get('input_tokens')} "
        f"output_tokens={amounts.get('output_tokens')} cost_usd={amounts.get('cost_usd')}"
    )
assert any(row.get("model") == HEALTHY_MODEL for row in usage), "no Usage for the healthy member"
"""

_DEBUG_FOLLOW_MD = """
## 5. Follow the trace into the logs

The engine and the gateway write `key=value` log lines. Each gateway line of this run carries
`trace_id=<id>` and a `gateway_call_id=call_<id>`, one call id per member call. The workbench's
bundle page for this run (`trace.json`, Telemetry) lists those lines and links each failing span
and ERROR log to them.

To filter a log yourself, match the **exact token** `trace_id=<32 hex>`, bounded by whitespace,
the same rule the workbench verdict uses. A substring match is wrong: it also picks up
`parent_trace_id=<id>`, or a longer id that merely starts with this one, and those lines belong to
another run.

On this failure the gateway logs a "usage accounting started" line for **both** member calls,
and a "global cache hit" line only for the healthy one. The call id with no cache-hit line is the
refused member: the 404 itself logs nothing at the gateway. The excerpt below has that shape,
plus decoys a substring match would wrongly keep. Set `GATEWAY_LOG` to the stack's
`aigateway.log` to filter the real one.
"""


def _debug_follow() -> str:
    # Rendered from the verdict's own pattern, so the tutorial can never teach a different rule.
    pattern = _TRACE_ID_TOKEN.pattern
    if '"' in pattern:
        raise ValueError("the trace_id token pattern must render as a raw string literal")
    return f"""
TRACE_ID_TOKEN = re.compile(r"{pattern}")  # the verdict's rule


def lines_of(trace_id, text):
    \"\"\"The lines carrying an exact `trace_id=<id>` token for this id, never a substring.\"\"\"
    return [line for line in text.splitlines() if trace_id in TRACE_ID_TOKEN.findall(line)]


other = "0" * 32
excerpt = "\\n".join(
    [
        f"INFO session gateway_call_id=call_a trace_id={{trace_id}} usage accounting started",
        f"INFO session gateway_call_id=call_b trace_id={{trace_id}} usage accounting started",
        f"INFO chat_cache_stage gateway_call_id=call_a trace_id={{trace_id}} global cache hit "
        f"model='{{HEALTHY_MODEL}}'",
        f"INFO session gateway_call_id=call_c parent_trace_id={{trace_id}} another run",
        f"INFO session gateway_call_id=call_d trace_id={{trace_id}}ff another run",
        f"INFO session gateway_call_id=call_e trace_id={{other}} another run",
    ]
)
mine = lines_of(trace_id, excerpt)
substring = [line for line in excerpt.splitlines() if trace_id in line]
# WHY this wording: "token: <n>" reads like a credential to the redactor and gets masked.
print(f"lines kept by the exact rule: {{len(mine)}}; by a substring match: {{len(substring)}}")
calls = {{}}
for line in mine:
    call = re.search(r"(?<!\\S)gateway_call_id=(\\S+)", line).group(1)
    calls.setdefault(call, []).append("cache hit" if "cache hit" in line else "started")
for call, seen_as in calls.items():
    verdict = "served" if "cache hit" in seen_as else "refused: no cache-hit line"
    print(f"{{call}}: {{', '.join(seen_as)}} -> {{verdict}}")
if GATEWAY_LOG and Path(GATEWAY_LOG).is_file():
    print(f"--- {{GATEWAY_LOG}}, this run only")
    for line in lines_of(trace_id, Path(GATEWAY_LOG).read_text(encoding="utf-8")):
        print(line)
"""


_DEBUG_FOLLOW_CHECK = """
assert len(mine) == 3 and len(substring) == 5, (mine, substring)
assert sorted(calls) == ["call_a", "call_b"], calls
"""


def _debug_fixed_md(golden: GoldenReport) -> str:
    assert golden.judge_spec is not None  # validator-held for a corrective_loop golden
    members = _list([_model(spec, _INDENT * 2) for spec in golden.member_specs[:2]], _INDENT)
    fixed = _call(
        "sf.Fusion",
        [members, f"name={_q('debug_fixed')}", f"synthesizer={_model(golden.judge_spec, _INDENT)}"],
        "",
    )
    return f"""
## 6. Root cause and the fixed recipe

**Root cause:** `UNSERVABLE_MODEL` is a route the gateway cannot serve here (on replay: no
recorded answer and no key, so a `404 profile_not_found`). The engine reports it as
`upstream_error` at stage `candidate`, and with `quorum="all"` it takes the whole case down.

**Fix:** use members the gateway can serve. Here the unservable member is replaced by the other
member the ifeval golden recorded. It is left as text, not run, so this notebook stays failing by
design.

```python
candidate = {fixed}
```
"""


_DEBUG_RESULT_SECTION_MD = """
## 7. The result

The `WORKBENCH_RESULT` line printed after section 1 carries the trace id and the failure codes.
The workbench checks them against this notebook's declaration (`workbench.expect`): the declared
code at the declared stage, the trace in the engine and gateway logs with call ids, and an error
in the telemetry. Anything else, including an unexpected pass, is red.
"""


def _debug_failing_run() -> Any:
    golden = load_golden(GOLDENS_DIR / "ifeval.golden.json")
    healthy, judge = golden.member_specs[0], golden.judge_spec
    assert judge is not None and healthy.prompt is not None  # validator-held
    unservable = _call(
        "sf.Model", ["UNSERVABLE_MODEL", f"prompt={_str(healthy.prompt, _INDENT * 3)}"], _INDENT * 2
    )
    members = _list([_model(healthy, _INDENT * 2), unservable], _INDENT)
    recipe = f"HEALTHY_MODEL = {_q(healthy.model)}  # the golden's first member: a cache hit\n" + (
        "candidate = "
        + _call(
            "sf.Fusion",
            [members, f"name={_q('debug_unservable')}", f"synthesizer={_model(judge, _INDENT)}"],
            "",
        )
        + "\ncandidate\n"
    )
    cells = [
        _markdown(_DEBUG_TITLE),
        _code(_DEBUG_PARAMETERS, "parameters"),
        _code(_DEBUG_CLIENT),
        _markdown(_DEBUG_RUN_MD),
        _code(recipe),
        _code(_DEBUG_EVALUATE),
        _markdown(_DEBUG_RESULT_MD),
        _code(_DEBUG_RESULT, RESULT_TAG),
        _markdown(_DEBUG_SYMPTOM_MD),
        _code(_DEBUG_SYMPTOM),
        _markdown(_DEBUG_TRACE_MD),
        _code(_DEBUG_TRACE),
        _markdown(_DEBUG_TELEMETRY_MD),
        _code(_debug_telemetry()),
        _markdown(_DEBUG_USAGE_MD),
        _code(_DEBUG_USAGE),
        _markdown(_DEBUG_FOLLOW_MD),
        _code(_debug_follow()),
        _code(_DEBUG_FOLLOW_CHECK),
        _markdown(_debug_fixed_md(golden)),
        _markdown(_DEBUG_RESULT_SECTION_MD),
        _code("client.close()"),
    ]
    meta = {"targets": ["replay"], "required_result": ["trace_ids"], "expect": DEBUG_EXPECT}
    return _notebook(DEBUG_STEM, cells, meta)


_BUILDERS: Final[dict[str, Callable[[], Any]]] = {
    "quickstart": _quickstart,
    DEBUG_STEM: _debug_failing_run,
}


def serialize(nb: nbformat.NotebookNode) -> str:
    """The on-disk bytes: ``nbformat.writes`` plus the final newline ``nbformat.write`` adds
    (and the repo's end-of-file-fixer hook demands)."""
    return nbformat.writes(nb) + "\n"


def build() -> dict[str, nbformat.NotebookNode]:
    """Every workbench notebook, keyed by stem, rendered fresh."""
    return {stem: builder() for stem, builder in _BUILDERS.items()}


# --- CLI --------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the workbench notebooks.")
    parser.add_argument("--check", action="store_true", help="exit 1 if a file is stale")
    parser.add_argument("--out", type=Path, default=NOTEBOOK_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    out: Path = args.out
    stale: list[str] = []
    for stem, nb in build().items():
        path = out / f"{stem}.ipynb"
        text = serialize(nb)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        if args.check:
            stale.append(path.name)
        else:
            out.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path}")
    if stale:
        print(f"stale: {', '.join(stale)}; run build_notebooks.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
