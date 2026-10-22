"""Write one notebook run's evidence bundle (e2e workbench spec §3.3). Secrets never land.

Redaction is ``workbench.redaction`` (values, never serialised JSON — see its INVARIANT).

Telemetry (spec §3.6, unit 6 Task 4): the notebook's recorder writes ``events.jsonl``,
``report.json``, ``accounting.json`` and ``recorder.json`` into the bundle while it runs;
``write_telemetry`` then copies the run's spans in and writes ``telemetry.json``, which says
how many of each were kept, how many were dropped by the cap, and why a file is empty.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Final

import nbformat

from workbench.evidence import TraceChain
from workbench.redaction import redact, redact_named_tree, redact_tree
from workbench.runner import NotebookRun
from workbench.telemetry_recorder import ACCOUNTING_FILE, RECORDER_FILE, REPORT_FILE

EVENTS_FILE: Final = "events.jsonl"
SPANS_FILE: Final = "spans.jsonl"
TELEMETRY_FILE: Final = "telemetry.json"
SPANS_CAP: Final = 20_000
#: Written while (or for) one run; a rerun into the same bundle must never inherit them.
_RUN_FILES: Final = (
    EVENTS_FILE,
    SPANS_FILE,
    TELEMETRY_FILE,
    REPORT_FILE,
    ACCOUNTING_FILE,
    RECORDER_FILE,
)

type SpansFor = Callable[[Iterable[str]], list[dict[str, Any]]]

_HEADER = "| target | notebook | outcome | trace ids | reasons |\n|---|---|---|---|---|\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def write_bundle(
    root: Path,
    *,
    target: str,
    notebook: str,
    run: NotebookRun,
    chain: TraceChain,
    passed: bool,
    reasons: Sequence[str],
    notes: Sequence[str] = (),
) -> Path:
    """Write ``root/<target>/<notebook>/`` and append one row to ``root/summary.md``.

    ``notes`` are evidence that never decides the verdict (a telemetry write that failed):
    kept in ``trace.json`` and appended to the summary row's reasons cell, redacted.
    """
    out = bundle_dir(root, target, notebook)
    (out / "logs").mkdir(parents=True, exist_ok=True)

    executed = nbformat.from_dict(redact_tree(run.executed))
    nbformat.write(executed, out / "executed.ipynb")

    for hop in chain.hops:
        (out / "logs" / f"{hop.name}.txt").write_text(redact("\n".join(hop.lines)))

    trace = chain.to_json() | {
        "passed": passed,
        "reasons": list(reasons),
        "notes": list(notes),
        "result": run.result,
        "error": run.error,
    }
    (out / "trace.json").write_text(json.dumps(redact_tree(trace), indent=2))

    ids = ", ".join(chain.trace_ids) or "—"
    why = "; ".join([*reasons, *notes]) or "—"
    _append_row(root, target, notebook, "PASS" if passed else "FAIL", ids, why)
    return out


def bundle_dir(root: Path, target: str, notebook: str) -> Path:
    return root / target / notebook


def prepare_bundle(root: Path, target: str, notebook: str) -> Path:
    """Create the bundle dir BEFORE the run (its recorder writes there live) and remove the
    telemetry files of any previous run into it, so a stale report never reads as this one."""
    out = bundle_dir(root, target, notebook)
    out.mkdir(parents=True, exist_ok=True)
    for name in _RUN_FILES:
        (out / name).unlink(missing_ok=True)
    return out


def settled(
    spans_for: SpansFor,
    *,
    quiet_s: float = 1.0,
    max_s: float = 10.0,
    poll_s: float = 0.1,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> SpansFor:
    """``spans_for`` that returns once the run's span count has been still for ``quiet_s``,
    or after ``max_s`` at most.

    WHY: the engine and the gateway batch their spans (``OTEL_BSP_SCHEDULE_DELAY``, 200 ms in
    the workbench), so the last batch of a run can land just after its notebook ends. A
    still window of five batch delays catches it; the bound keeps a chatty receiver from
    holding the verdict. With no spans at all it costs one quiet window.
    """

    def select(trace_ids: Iterable[str]) -> list[dict[str, Any]]:
        ids = list(trace_ids)
        start = clock()
        spans = spans_for(ids)
        still_since = start
        while clock() - still_since < quiet_s and clock() - start < max_s:
            sleep(poll_s)
            latest = spans_for(ids)
            if len(latest) != len(spans):
                spans, still_since = latest, clock()
        return spans

    return select


def _span_selection(
    trace_ids: Sequence[str], spans_for: SpansFor | None
) -> tuple[list[dict[str, Any]], str | None]:
    """The run's spans and, when there are none, why. Never raises (export never fails a run)."""
    spans: list[dict[str, Any]] = []
    if spans_for is None:
        note: str | None = "no OTLP receiver in this session"
    elif not trace_ids:
        note = "no trace ids to select spans by"
    else:
        try:
            spans = spans_for(trace_ids)
            note = None if spans else "no spans received for this run's trace ids"
        except Exception as exc:  # noqa: BLE001 — a bad spans file is evidence, not a failure
            note = redact(f"spans unavailable: {type(exc).__name__}: {exc}")
    return spans, note


def _events_summary(out: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """The recorder's own counts, or (it never finished) the whole lines in the events file."""
    try:
        summary = json.loads((out / RECORDER_FILE).read_text(encoding="utf-8"))
        return summary["events"] | {"note": None}, summary["files"]
    except (OSError, ValueError, KeyError, TypeError):
        pass  # missing or torn (the kernel died mid-write): count the events file instead
    events = out / EVENTS_FILE
    if not events.exists():
        note = "no events recorded: the notebook never started its recorder"
        recorded = 0
    else:
        note = "the recorder did not finish: the notebook stopped before its result cell"
        text = events.read_text(encoding="utf-8")
        recorded = text.count("\n")  # a torn tail (no newline) is not an event
    counts = {"recorded": recorded, "dropped": None, "failed": None, "cap": None, "note": note}
    return counts, {}


def write_telemetry(
    out: Path,
    trace_ids: Sequence[str],
    spans_for: SpansFor | None,
    *,
    cap: int = SPANS_CAP,
) -> dict[str, Any]:
    """Copy the spans of exactly ``trace_ids`` into ``out/spans.jsonl`` (at most ``cap``) and
    write ``out/telemetry.json``; return what it holds.

    Spans are selected by exact trace id, so another run's or notebook's spans sharing the
    session receiver never land here (Review Focus 3), and redacted again on the way in.
    """
    spans, span_note = _span_selection(trace_ids, spans_for)
    kept = spans[:cap]
    lines = "".join(json.dumps(redact_named_tree(s), sort_keys=True) + "\n" for s in kept)
    (out / SPANS_FILE).write_text(lines, encoding="utf-8")
    events, files = _events_summary(out)
    telemetry = {
        "schema": "workbench.telemetry.v1",
        "events": {"file": EVENTS_FILE} | events,
        "files": files,
        "spans": {
            "file": SPANS_FILE,
            "copied": len(kept),
            "dropped": len(spans) - len(kept),
            "cap": cap,
            "note": span_note,
        },
    }
    (out / TELEMETRY_FILE).write_text(json.dumps(redact_named_tree(telemetry), indent=2) + "\n")
    return telemetry


SETUP_ERROR_FILE = "setup_error.txt"
SETUP_ROW = "(target setup)"


def write_setup_failure(root: Path, *, target: str, skipped: bool, detail: str) -> Path:
    """Record a target that never came up: ``root/setup_error.txt`` plus a summary row.

    WHY (review finding 4): no notebook ran, so no bundle exists; without this the evidence dir
    is empty and the reviewer has no artifact saying why. ``detail`` is redacted here.
    """
    root.mkdir(parents=True, exist_ok=True)
    clean = redact(detail).rstrip()
    path = root / SETUP_ERROR_FILE
    with path.open("a") as fh:
        fh.write(f"target: {target}\n{clean}\n")
    last = (clean.splitlines() or ["?"])[-1]
    _append_row(root, target, SETUP_ROW, "SETUP-SKIP" if skipped else "SETUP-ERROR", "—", last)
    return path


def _append_row(root: Path, target: str, notebook: str, outcome: str, ids: str, why: str) -> None:
    summary = root / "summary.md"
    if not summary.exists():
        summary.write_text(_HEADER)
    row = f"| {_cell(target)} | {_cell(notebook)} | {outcome} | {ids} | {_cell(why)} |\n"
    with summary.open("a") as fh:
        fh.write(redact(row))
