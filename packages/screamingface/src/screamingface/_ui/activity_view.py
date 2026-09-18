"""Latest operation states in stable order, labelled by explicit execution parentage."""

import time
from html import escape

from screamingface._ui.activity_groups import groups
from screamingface._ui.activity_record import LABELS, TERMINAL
from screamingface._ui.activity_state import ActivityLog, ActivityRow

STYLE = """<style>
.sf-activity-console{box-sizing:border-box;min-height:280px;
 margin:0;padding:12px 16px;border:1px solid var(--sf-line);
 background:var(--sf-surface);color:var(--sf-ink);font:12px/1.6 "IBM Plex Mono",monospace;
 font-variant-numeric:tabular-nums;overflow-wrap:anywhere;text-align:left}
.sf-activity-console .sf-activity__stage{display:flex;margin:0;padding:0;font:inherit}
.sf-activity-console .sf-activity__call{display:flex;margin:0;padding:0;
 font:inherit;white-space:normal}
.sf-activity-console .sf-activity__failed,.sf-activity-console .sf-activity__refused{
 color:var(--sf-danger-solid)}
.sf-activity-mark{display:inline-flex;align-items:center;justify-content:center;
 flex:0 0 14px;width:14px;height:19px;margin-right:8px;color:var(--sf-ink-2)}
.sf-activity-mark svg{width:12px;height:12px}
.sf-activity-spinner{width:10px;height:10px;border:1px solid var(--sf-line);
 border-top-color:var(--sf-accent);border-right-color:var(--sf-accent);border-radius:50%;
 animation:sf-activity-spin .85s linear infinite}
@keyframes sf-activity-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.sf-activity-spinner{animation:none}}
.sf-activity-console .sf-activity__failed .sf-activity-mark{color:var(--sf-danger-solid)}
.sf-activity-console p{margin:0;font:inherit;color:var(--sf-ink-2)}
.sf-candidate-row .sf-eval__table-wrap{margin-top:0;border-top:0}
.sf-candidate-row .sf-eval__table thead{position:absolute;width:1px;height:1px;overflow:hidden;
 clip:rect(0,0,0,0)}
.sf-candidate-row .widget-toggle-button{border:0;border-radius:0;box-shadow:none;
 background:var(--sf-surface);color:var(--sf-ink-2);margin:0}
.sf-candidate-row .widget-toggle-button:focus-visible{outline:2px solid var(--sf-accent)}
.sf-candidate-row .sf-eval__table,.sf-candidate-head .sf-eval__table{min-width:796px}
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
        label = "Aggregated scores" if outcome == "completed" else "Aggregating scores"
    return label


def _description(row: ActivityRow, label: str, *, model: bool = False) -> str:
    facts = dict(row.record.facts)
    prefix = _case_prefix(facts, model=model)
    name = facts.get("model_id")
    outcome = _outcome(row)
    label = _stage_label(row, label, outcome)
    subject = f"{label} with {name}" if model and name else label
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
    state = "" if outcome in {"started", "running", "completed"} else f" {outcome}"
    return f"{prefix}{subject}{state}{suffix}"


def visible_operations(log: ActivityLog, candidate: int) -> list[tuple[ActivityRow, str]]:
    """Hide only routine Answering scopes represented by explicitly parented calls."""
    labels = {}
    hidden = set()
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


def _line(row: ActivityRow, label: str) -> str:
    model = row.record.kind == "model_call"
    kind = "call" if model else "stage"
    return (
        f'<div class="sf-activity__{kind}">{_marker(row)}'
        f'<span class="sf-activity__{row.record.state}">'
        f"{escape(_description(row, label, model=model))}</span></div>"
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
        + (f"<p>Partial history: {notice}.</p>" if notice else "")
        + content
        + "</section>"
    )
