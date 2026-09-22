"""Latest operation states in stable order, labelled by explicit execution parentage."""

import time
from datetime import UTC, datetime
from html import escape

from screamingface._ui.activity_groups import groups
from screamingface._ui.activity_record import LABELS, TERMINAL
from screamingface._ui.activity_state import ActivityLog, ActivityRow

STYLE = """<style>
.sf-activity-console{box-sizing:border-box;
 margin:0;padding:8px;border:1px solid var(--sf-line);
 background:var(--sf-surface);color:var(--sf-ink);font:12px/1.6 "IBM Plex Mono",monospace;
 font-variant-numeric:tabular-nums;overflow-wrap:anywhere;text-align:left}
.sf-activity-tools{display:flex;justify-content:flex-end;position:sticky;top:0;
 z-index:1;background:var(--sf-surface);padding-bottom:4px}
.sf-activity-copy{font:inherit;color:var(--sf-ink-2);background:var(--sf-surface);
 border:1px solid var(--sf-line);border-radius:0;padding:2px 8px;cursor:pointer}
.sf-activity-copy:hover{color:var(--sf-ink);border-color:var(--sf-accent)}
.sf-activity-copy:focus-visible{outline:2px solid var(--sf-accent);outline-offset:2px}
.sf-activity-console .sf-activity__stage{display:flex;margin:0;padding:0;font:inherit}
.sf-activity-console .sf-activity__call{display:flex;margin:0;padding:0;
 font:inherit;white-space:normal}
.sf-activity-console .sf-activity__failed,.sf-activity-console .sf-activity__refused{
 color:var(--sf-danger-solid)}
.sf-activity-mark{display:inline-flex;align-items:center;justify-content:center;
 flex:0 0 14px;width:14px;height:19px;margin-right:8px;color:var(--sf-ink-2)}
.sf-activity-time{flex:0 0 auto;margin-right:10px;color:var(--sf-ink-2);font-style:normal}
.sf-activity-mark svg{width:12px;height:12px}
.sf-activity-spinner{width:10px;height:10px;border:1px solid var(--sf-line);
 border-top-color:var(--sf-accent);border-right-color:var(--sf-accent);border-radius:50%;
 animation:sf-activity-spin .85s linear infinite}
@keyframes sf-activity-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.sf-activity-spinner{animation:none}}
.sf-activity-console .sf-activity__failed .sf-activity-mark{color:var(--sf-danger-solid)}
.sf-activity-console p{margin:0;font:inherit;color:var(--sf-ink-2)}
.sf-candidate-row{border:1px solid var(--sf-line);border-top:0;box-sizing:border-box}
.sf-candidate-summary{position:relative}
.sf-candidate-row .sf-eval__table-wrap{margin:0;border:0}
.sf-candidate-summary .widget-html{pointer-events:none;margin:0}
.sf-candidate-summary .sf-eval__candidate{position:relative;z-index:2;pointer-events:auto}
.sf-candidate-row .sf-eval__table thead{position:absolute;width:1px;height:1px;overflow:hidden;
 clip:rect(0,0,0,0)}
.sf-candidate-row .widget-toggle-button{position:absolute;inset:0;z-index:1;
 border:0;border-radius:0;box-shadow:none;background:transparent!important;
 color:var(--sf-ink-2);margin:0;padding:0;font-size:0;cursor:pointer}
.sf-candidate-row .widget-toggle-button .fa{position:absolute;left:12px;top:50%;
 transform:translateY(-50%);font-size:12px;margin:0}
.sf-candidate-summary:hover{background:var(--sf-surface)}
.sf-candidate-row .widget-toggle-button:focus-visible{outline:2px solid var(--sf-accent);
 outline-offset:-2px}
.sf-candidate-row .sf-eval__table td:first-child,
.sf-candidate-head .sf-eval__table th:first-child{padding-left:36px}
.sf-candidate-details{border-top:1px solid var(--sf-line)}
.sf-candidate-details .widget-html{margin:0}
.sf-candidate-details .sf-activity-console{border:0}
.sf-candidate-row .sf-eval__table,.sf-candidate-head .sf-eval__table{min-width:820px}
</style>"""


def _outcome(row: ActivityRow) -> str:
    record = row.record
    if row.historical or record.state in TERMINAL:
        return record.state
    if row.ended:
        return "Run ended; operation outcome not observed"
    age = time.time() * 1000 - record.observed_at_ms
    return "No recent update; outcome not observed" if not -30000 <= age < 150000 else record.state


def _case_prefix(facts: dict[str, str | int | float], *, model: bool) -> str:
    # INVARIANT: selected position comes from the Engine, never event arrival order.
    if "case_position" in facts and "case_count" in facts:
        return f"[Case {facts['case_position']}/{facts['case_count']}] "
    case_id = facts.get("case_id")
    if case_id is not None:
        return f"Case {case_id}: "
    return "Case not identified: " if model else ""


def _stage_label(row: ActivityRow, label: str, outcome: str) -> str:
    facts = dict(row.record.facts)
    if row.record.kind == "case_loading":
        label = "Loading benchmark cases"
        if outcome == "completed":
            count = facts.get("loaded_count")
            label = (
                f"Loaded {count} benchmark cases" if count is not None else "Benchmark cases loaded"
            )
    if row.record.kind == "aggregation":
        label = "Scores aggregated" if outcome == "completed" else "Aggregating scores"
    if outcome == "completed":
        label = {"Answering": "Answered", "Grading": "Graded"}.get(label, label)
    return label


def _call_label(name: str, outcome: str) -> str:
    # WHY: stage membership does not establish a member, synthesiser or judge role.
    return {
        "started": f"Calling {name}",
        "running": f"Calling {name}",
        "completed": f"Completed {name} call",
        "retrying": f"Retrying {name} call",
    }.get(outcome, f"{name} call {outcome}")


def _description(row: ActivityRow, label: str, *, model: bool = False) -> str:
    facts = dict(row.record.facts)
    prefix = _case_prefix(facts, model=model)
    name = facts.get("model_id")
    outcome = _outcome(row)
    label = _stage_label(row, label, outcome)
    subject = _call_label(str(name), outcome) if model and name else label
    details = []
    if failure := facts.get("failure_code"):
        details.append(str(failure).replace("_", " "))
    if row.record.state == "retrying" and (attempt := facts.get("attempt")):
        details.append(f"attempt {attempt}")
    finish = {"length": "token limit reached", "content_filter": "content filtered"}.get(
        str(facts.get("finish_reason"))
    )
    if finish:
        details.append(finish)
    for key, description in (
        ("selected_count", "cases selected"),
        ("result_count", "results"),
        ("prepared_task_count", "grading tasks prepared"),
    ):
        if key in facts:
            details.append(f"{facts[key]} {description}")
    suffix = ": " + "; ".join(details) if details else ""
    state = (
        "" if model and name or outcome in {"started", "running", "completed"} else f" {outcome}"
    )
    return f"{prefix}{subject}{state}{suffix}"


def visible_operations(log: ActivityLog, candidate: int) -> list[tuple[ActivityRow, str]]:
    """Keep case phases and calls; hide routine endpoint detail represented by summaries."""
    labels = {}
    rows = [row for row in log.rows(detailed=True) if row.candidate == candidate]
    case_runs = {
        row.run
        for row in rows
        if dict(row.record.facts).get("scope") == "case" and row.record.kind == "grading"
    }
    hidden = {
        (row.run, row.record.id)
        for row in rows
        if row.run in case_runs
        and row.record.kind == "grading"
        and dict(row.record.facts).get("scope") != "case"
        and _outcome(row) in {"started", "running", "completed"}
    }
    for group in groups(log, candidate):
        for call in group.calls:
            labels[(call.run, call.record.id)] = group.label if group.stage else "Model call"
        stage = group.stage
        if (
            stage is not None
            and stage.record.kind == "answering"
            and group.calls
            and _outcome(stage) in {"started", "running", "completed"}
        ):
            hidden.add((stage.run, stage.record.id))
    # INVARIANT: dict insertion order is first observation, not last update time.
    return [
        (row, labels.get((row.run, row.record.id), LABELS[row.record.kind]))
        for row in log.rows(detailed=True)
        if row.candidate == candidate and (row.run, row.record.id) not in hidden
    ]


def _marker(row: ActivityRow) -> str:
    outcome = _outcome(row)
    if outcome in {"started", "running", "retrying"}:
        label = "Retrying" if outcome == "retrying" else "Running"
        icon = '<span class="sf-activity-spinner"></span>'
    else:
        label, path = {
            "completed": ("Completed", "M3 8l3 3 7-7"),
            "failed": ("Failed", "M4 4l8 8M12 4l-8 8"),
            "refused": ("Refused", "M4 4l8 8M12 4l-8 8"),
            "cancelled": ("Cancelled", "M3 8h10"),
        }.get(outcome, ("Status unknown", "M8 3v6M8 11v2"))
        icon = (
            '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" '
            f'stroke-width="1.5" aria-hidden="true"><path d="{path}"/></svg>'
        )
    return f'<span class="sf-activity-mark" role="img" aria-label="{label}">{icon}</span>'


def _timestamp(row: ActivityRow) -> str:
    observed = row.first_observed_ms
    if observed is None:
        observed = row.record.observed_at_ms
    try:
        stamp = datetime.fromtimestamp(observed / 1000, UTC)
    except (ValueError, OverflowError, OSError):
        return '<span class="sf-activity-time" title="Time unavailable">--:--:--</span>'
    return (
        f'<time class="sf-activity-time" datetime="{stamp.isoformat()}" '
        f'title="First observed: {stamp:%Y-%m-%d %H:%M:%S} UTC">{stamp:%H:%M:%S}</time>'
    )


def _line(row: ActivityRow, label: str) -> str:
    model = row.record.kind == "model_call"
    kind = "call" if model else "stage"
    return (
        f'<div class="sf-activity__{kind}">{_timestamp(row)}{_marker(row)}'
        f'<span class="sf-activity__{row.record.state}">'
        f"{escape(_description(row, label, model=model))}</span></div>"
    )


def _copy_control() -> str:
    # INVARIANT: copy only this rendered page; raw event bodies never enter the DOM.
    action = r"""event.stopPropagation();(async()=>{
      const button=this;
      const content=button.closest('.sf-activity-console').querySelector('.sf-activity-content');
      const text=Array.from(content.children)
        .map(line=>line.innerText.replace(/\n+/g,' ')).join('\n');
      try {
        await navigator.clipboard.writeText(text);
        button.textContent='Copied';
      } catch {
        button.textContent='Copy failed';
        button.title='Select the log text and copy it manually';
      }
    })()"""
    return (
        '<div class="sf-activity-tools"><button class="sf-activity-copy" type="button" '
        'aria-label="Copy displayed logs" title="Copy displayed logs" '
        f'onclick="{escape(action, quote=True)}">Copy</button></div>'
    )


def activity_html(
    log: ActivityLog,
    candidates: tuple[str, ...],
    *,
    candidate: int = 0,
    page: int = 0,
    finished: bool = False,
) -> str:
    rows = visible_operations(log, candidate)
    page = max(0, min(page, max(0, (len(rows) - 1) // 100)))
    selected = rows[max(0, len(rows) - (page + 1) * 100) : len(rows) - page * 100]
    notices = [
        ("evaluation history entries evicted", log.truncated),
        ("operation revision gaps", log.gaps),
        ("invalid activity records", log.invalid),
        ("unsupported activity records", log.unsupported),
        ("producer records suppressed", sum(log.suppressed.get(candidate, {}).values())),
        ("Engine bridge Logs dropped", log.bridge_loss.get(candidate, 0)),
    ]
    notice = "; ".join(f"{n} {label}" for label, n in notices if n)
    content = "".join(_line(row, label) for row, label in selected)
    if not content:
        content = (
            "<p>"
            + (
                "No structured activity received for this run."
                if finished
                else "No structured activity received yet."
            )
            + "</p>"
        )
    label = escape(candidates[candidate], quote=True)
    return (
        STYLE
        + f'<section class="sf-activity-console" tabindex="0" aria-label="Activity for {label}">'
        + _copy_control()
        + '<div class="sf-activity-content">'
        + (f"<p>Partial history: {notice}.</p>" if notice else "")
        + content
        + "</div></section>"
    )
