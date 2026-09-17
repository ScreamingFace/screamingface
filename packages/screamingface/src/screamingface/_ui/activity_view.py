"""Candidate-scoped activity, grouped by explicit execution parentage."""

import time
from html import escape

from screamingface._ui.activity_groups import ActivityGroup, groups
from screamingface._ui.activity_record import TERMINAL
from screamingface._ui.activity_state import ActivityLog, ActivityRow

STYLE = """<style>
.sf-activity{color:var(--sf-ink);font-family:"IBM Plex Mono",monospace;
 font-size:12px;line-height:1.7;padding:8px 16px;font-variant-numeric:tabular-nums;
 overflow-wrap:anywhere}
.sf-activity p{font-size:12px;color:var(--sf-ink-2)}
.sf-activity h4{font:inherit;font-weight:600;margin:12px 0 4px}
.sf-activity h4 small{font:inherit;font-weight:400;color:var(--sf-ink-2)}
.sf-activity__call{padding-left:16px;white-space:pre-wrap}
.sf-activity__details{color:var(--sf-ink-2)}
.sf-activity__failed,.sf-activity__refused{color:var(--sf-danger-solid)}
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


def _call(row: ActivityRow) -> str:
    record = row.record
    facts = dict(record.facts)
    name = str(facts.get("model_id", "Model call"))
    details = " · ".join(
        f"{k.replace('_', ' ')}: {v}" for k, v in record.facts if k not in {"model_id", "parent_id"}
    )
    return (
        f'<div class="sf-activity__call">{escape(name)} — '
        f'<span class="sf-activity__{record.state}">{escape(_outcome(row))}</span>'
        f' · <span title="Measured elapsed">{record.elapsed_ms / 1000:g}s</span>'
        + (f' <span class="sf-activity__details">· {escape(details)}</span>' if details else "")
        + "</div>"
    )


def _group(group: ActivityGroup, selected: set[tuple[str, str]]) -> str:
    calls = [r for r in group.calls if (r.run, r.record.id) in selected]
    stage = group.stage
    if not calls and (stage is None or (stage.run, stage.record.id) not in selected):
        return ""
    summary = (
        f"{_outcome(stage)} · {stage.record.elapsed_ms / 1000:g}s"
        if stage
        else "No parent activity was provided or retained"
    )
    lines = "".join(_call(r) for r in calls)
    return f"<section><h4>{group.label} <small>— {escape(summary)}</small></h4>{lines}</section>"


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
    notice = " · ".join(f"{n} {label}" for label, n in notices if n)
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
        + f'<section class="sf-activity" aria-label="Activity for {label}">'
        + (f"<p>Partial history: {notice}.</p>" if notice else "")
        + content
        + "</section>"
    )
