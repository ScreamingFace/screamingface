# Plan — warn the client about an unclaimed queued run

Spec: `docs/spec/2026-09-28-engine-unclaimed-run-warning.md`. Stack: `screamingface-engine`
(sdlc-python). Worktree: `.claude/worktrees/engine-unclaimed-run-warning`.

## Step 1 — broker failure at schedule time (R10, R11)

1. RED: `tests/unit/test_queue_schedule_broker_failure.py`.
   - A fake queue whose `publish` raises `nats.errors.TimeoutError` → `schedule()` raises
     `RunQueueUnavailable`, and a second schedule for the same caller at cap 1 is admitted
     (the reservation was released).
   - A fake queue whose `depth` raises `nats.errors.ConnectionClosedError` → `RunQueueUnavailable`.
   - A `JobRunnerAtCapacity` still passes through unchanged.
   - Route: a fake runner that raises `RunQueueUnavailable` → 503, `application/problem+json`,
     `Retry-After: 5`, generic detail.
2. GREEN: add `RunQueueUnavailable(RuntimeError)` in `runner_queue.py`. Split
   `QueueJobRunner.schedule()`: the outer method catches `nats.errors.Error` and raises
   `RunQueueUnavailable` from it. Add the `except RunQueueUnavailable` branch in
   `rest/routes.py::_schedule`.

## Step 2 — `accepted_ages()` (spec 3.1)

1. RED: `tests/unit/test_queue_runner_accepted_ages.py` — empty at start; after a schedule the
   age follows the runner clock; a failed publish records nothing.
2. GREEN: `QueueJobRunner.accepted_ages() -> dict[str, float]` from `_scheduled_at`.

## Step 3 — the warner policy (R1–R7)

1. RED: `tests/unit/test_unclaimed_run_warner.py` with a fake runner (`accepted_ages`,
   `status`) and a fake audience (`has_subscriber`, `notify`).
   Cases: warn once after grace; not before; `running`/terminal/`not_found` never warn and are
   not read again; no subscriber → no decision, later subscriber → warn; `QueueReadError` →
   retry; decisions pruned when the runner forgets the topic; frame is `WARN`, text is the
   generic constant, attribute `run.wait_s`; tick derivation (`grace/8`, floor 1 s).
2. GREEN: `screamingface_engine/unclaimed.py` — `UnclaimedRunWarner`, `QueuedRuns` and
   `NoticeAudience` Protocols, `UNCLAIMED_MESSAGE`.
3. Add `"unclaimed"` to `CONTROL_PLANE` in `.claude/scripts/check_layering.py`.

## Step 4 — settings, wiring, chart (R8)

1. RED: `tests/unit/test_unclaimed_run_warner_wiring.py` — default 300; negative refused;
   installed with a queue-aware fake runner; absent with no runner, with a runner that has no
   `accepted_ages`, or with `0`; the task starts with the App and is cancelled with it; the
   warner asks the REAL registry (not the `interest` seam).
   `tests/unit/test_chart_render_unclaimed_run_warn.py` — the ConfigMap renders the value
   (follow `test_chart_render_queue_replicas.py`).
2. GREEN: `Settings.unclaimed_run_warn_s`; `app.py::_install_unclaimed_run_warner`; chart
   `values.yaml`, `values.schema.json`, `templates/configmap.yaml`.

## Step 5 — gates and close

- `uv run .claude/scripts/run_gates.py screamingface-engine` green.
- Fill the ledger Outcome, with the alert-rule proposal in follow-ups.
- Conventional commits, no `Co-Authored-By`. Push `engine-unclaimed-run-warning`. No PR, no
  Linear.
