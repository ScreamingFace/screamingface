"""Group candidate activity using explicit, run-local parentage only."""

from dataclasses import dataclass, field

from screamingface._ui.activity_record import LABELS, TERMINAL
from screamingface._ui.activity_state import ActivityLog, ActivityRow


@dataclass
class ActivityGroup:
    label: str
    stage: ActivityRow | None
    calls: list[ActivityRow] = field(default_factory=list)


def _parent_stage(
    row: ActivityRow, index: dict[tuple[str, str], ActivityRow]
) -> tuple[str, str] | None:
    seen: set[str] = {row.record.id}
    parent = dict(row.record.facts).get("parent_id")
    while isinstance(parent, str) and parent not in seen:
        seen.add(parent)
        ancestor = index.get((row.run, parent))
        if ancestor is None:
            break
        if ancestor.record.kind != "model_call":
            return row.run, ancestor.record.id
        parent = dict(ancestor.record.facts).get("parent_id")
    return None


def groups(log: ActivityLog, candidate: int) -> list[ActivityGroup]:
    rows = [r for r in log.rows(detailed=True) if r.candidate == candidate]
    index = {(r.run, r.record.id): r for r in rows}
    stages = {
        (r.run, r.record.id): ActivityGroup(LABELS[r.record.kind], r)
        for r in rows
        if r.record.kind != "model_call"
    }
    unknown = ActivityGroup("Activity not identified", None)
    for row in rows:
        if row.record.kind == "model_call":
            parent = _parent_stage(row, index)
            group = stages[parent] if parent is not None else unknown
            group.calls.append(row)
    return [*stages.values(), *([unknown] if unknown.calls else [])]


def active_cases(log: ActivityLog, candidate: int, *, now_ms: float) -> str | None:
    """Display explicit current positions without changing completed-case accounting."""
    rows = [r for r in log.rows(detailed=True) if r.candidate == candidate]
    facts = [dict(r.record.facts) for r in _active_stages(rows, now_ms)]
    numbered = [f for f in facts if "case_position" in f and "case_count" in f]
    if not numbered or len(numbered) != len(facts):
        return None
    # INVARIANT: concurrency never turns the highest observed position into progress.
    return ", ".join(dict.fromkeys(f"{f['case_position']} / {f['case_count']}" for f in numbered))


def _active_stages(rows: list[ActivityRow], now_ms: float) -> list[ActivityRow]:
    return [
        r
        for r in rows
        if r.record.kind != "model_call"
        and not r.ended
        and r.record.state not in TERMINAL
        and -30000 <= now_ms - r.record.observed_at_ms < 150000
    ]


def stage_status(log: ActivityLog, candidate: int, *, now_ms: float) -> str | None:
    stages = [
        r
        for r in log.rows(detailed=True)
        if r.candidate == candidate and r.record.kind != "model_call"
    ]
    if not stages:
        return None
    # WHY: concurrent cases can occupy different phases. Neither arrival order nor
    # a later sibling's completion establishes that another operation has ended.
    active = _active_stages(stages, now_ms)
    if active:
        labels = {LABELS[r.record.kind] for r in active}
        return next(iter(labels)).split()[0] if len(labels) == 1 else "Running"
    return "Waiting"
