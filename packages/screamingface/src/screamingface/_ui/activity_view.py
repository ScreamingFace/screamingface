"""Candidate-scoped activity, grouped by explicit execution parentage."""

import time
from html import escape

from screamingface._ui.activity_groups import ActivityGroup, groups
from screamingface._ui.activity_record import TERMINAL
from screamingface._ui.activity_state import ActivityLog, ActivityRow

STYLE = """<style>
.sf-activity-console{box-sizing:border-box;height:280px;overflow:auto;
 margin:8px 0;padding:12px 16px;border:1px solid var(--sf-line);
 background:var(--sf-surface);color:var(--sf-ink);font:12px/1.6 "IBM Plex Mono",monospace;
 font-variant-numeric:tabular-nums;overflow-wrap:anywhere;text-align:left}
.sf-activity-console .sf-activity__stage{display:block;margin:0;padding:0;font:inherit}
.sf-activity-console .sf-activity__call{display:block;margin:0;padding:0;
 font:inherit;white-space:normal}
.sf-activity-console .sf-activity__failed,.sf-activity-console .sf-activity__refused{
 color:var(--sf-danger-solid)}
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
    if record.state in TERMINAL:
        return record.state
    if row.ended:
        return "Run ended; operation outcome not observed"
    age = time.time() * 1000 - record.observed_at_ms
    return "No recent update; outcome not observed" if not -30000 <= age < 150000 else record.state


def _description(row: ActivityRow, label: str, *, model: bool = False) -> str:
    facts = dict(row.record.facts)
    case_id = facts.get("case_id")
    # WHY: the Engine supplies identity, not an ordinal. Never parse "007" as 7
    # or borrow a sibling's Case when the producer did not supply one.
    prefix = (
        f"Case {case_id}: " if case_id is not None else "Case not identified: " if model else ""
    )
    name = facts.get("model_id")
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
        ("loaded_count", "cases loaded"),
        ("selected_count", "cases selected"),
        ("result_count", "results"),
        ("prepared_task_count", "grading tasks prepared"),
    ):
        if key in facts:
            details.append(f"{facts[key]} {description}")
    suffix = ": " + "; ".join(details) if details else ""
    return f"{prefix}{subject} {_outcome(row)}{suffix}"


def _call(row: ActivityRow, label: str) -> str:
    return (
        f'<div class="sf-activity__call"><span class="sf-activity__{row.record.state}">'
        f"{escape(_description(row, label, model=True))}</span></div>"
    )


def _group(group: ActivityGroup, selected: set[tuple[str, str]]) -> str:
    calls = [r for r in group.calls if (r.run, r.record.id) in selected]
    stage = group.stage
    if not calls and (stage is None or (stage.run, stage.record.id) not in selected):
        return ""
    summary = _description(stage, group.label) if stage else group.label
    lines = "".join(_call(r, group.label if stage else "Model call") for r in calls)
    return f'<div class="sf-activity__stage">{escape(summary)}</div>{lines}'


def activity_html(
    log: ActivityLog,
    candidates: tuple[str, ...],
    *,
    candidate: int = 0,
    page: int = 0,
    finished: bool = False,
) -> str:
    rows = [r for r in log.rows(detailed=True) if r.candidate == candidate]
    page = max(0, min(page, max(0, (len(rows) - 1) // 100)))
    selected = {
        (r.run, r.record.id)
        for r in rows[max(0, len(rows) - (page + 1) * 100) : len(rows) - page * 100]
    }
    notices = [
        ("evaluation history entries evicted", log.truncated),
        ("operation revision gaps", log.gaps),
        ("invalid activity records", log.invalid),
        ("unsupported activity records", log.unsupported),
        ("producer records suppressed", sum(log.suppressed.get(candidate, {}).values())),
        ("Engine bridge Logs dropped", log.bridge_loss.get(candidate, 0)),
    ]
    notice = "; ".join(f"{n} {label}" for label, n in notices if n)
    content = "".join(_group(g, selected) for g in groups(log, candidate))
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
