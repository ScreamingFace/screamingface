# OME-1924 part 1 — Queue Visibility Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the App and runner logs alone, on-call can name every run's owner key, Run facts, accept, claim (with wait) and finish (with outcome), and the 300 s notice's operator line says how many runs wait and run.

**Architecture:** Four additive log lines on the existing `logging.getLogger(__name__)` loggers, `%`-formatted `key=value` style; one new optional collaborator on `UnclaimedRunWarner` (a demand reader) and one optional read of `queue_snapshot()`. No port signature changes, no new metrics, no change to admission or scheduling.

**Tech Stack:** Python 3.12, FastAPI routes, asyncio worker, pytest + `caplog` (engine suite: `cd apps/screamingface-engine && uv run pytest`).

**Spec:** `docs/spec/2026-11-16-OME-1924-queue-visibility-logs.md`

## Global Constraints

- Identity in logs is only `runs.records.owner_key(...)` (sha256 of the trimmed, lowercased email) or the literal `anonymous`; an email never appears in a log record.
- `UNCLAIMED_MESSAGE` text is unchanged; new facts go to the operator log line and the frame attributes only (`unclaimed.py:26` invariant, `test_unclaimed_run_warner.py::test_the_message_names_no_internals`).
- Tests are append-only: no existing test file's prior tests change; new tests go in new files or appended.
- Unknown values are logged as `-`.
- Stable prefixes an operator greps: `run created`, `run scheduled` (existing), `run claimed`, `run finished`, `unclaimed run warned` (existing).
- Gates: `python3 .claude/scripts/run_gates.py screamingface-engine --base origin/main` and `repo --base origin/main` green; `check_module_size.py` within baseline.

## Review Focus

1. An identity header with upper case or spaces must log the same owner key as run history stores (`owner_key` normalises) — Task 2 test `test_scheduled_owner_matches_run_history_key`.
2. A message with a malformed or missing `ENQUEUED_AT_HEADER` must still log `run claimed` with `waited_s=-`, never raise — Task 3 test.
3. A duplicate claim acked away must log `run finished outcome=duplicate`, not an unhandled `KeyError` — Task 3 test.
4. The warner with the pre-existing `_Runner` fake (no `queue_snapshot`) and no demand reader keeps `attributes == {"run.wait_s": …}` exactly — the existing test `test_the_notice_is_a_generic_warn_log_frame_for_the_topic` already pins it; Task 4 must stay green on it.
5. `runner_demand.fresh()` returning `None` (stale sample) logs `running=-`, not `0` — Task 4 test.

---

### Task 1: `run created` line at `POST /runs`

**Files:**
- Modify: `apps/screamingface-engine/src/screamingface_engine/rest/runs.py` (`create_run`, after `registry.register`)
- Test: `apps/screamingface-engine/tests/unit/test_run_visibility_lines.py` (new)

**Interfaces:**
- Consumes: `RunRecord` (`runs/records.py:153`), `request_owner(request) -> OwnerKey`.
- Produces: INFO line on logger `screamingface_engine.rest.runs`:
  `run created run=%s owner=%s benchmark=%s cases=%d candidates=%d created=%s`
  (`created` is the bool from `registry.register`: a repeat `client_key` logs `created=False`).

- [ ] **Step 1: Write the failing test** (build the app and `POST /runs` the way `test_runs_routes.py` does; identity header `X-User-Email: " Ada@Example.ORG "`)

```python
async def test_create_run_logs_owner_key_and_run_facts(caplog, runs_app) -> None:
    with caplog.at_level(logging.INFO, logger="screamingface_engine.rest.runs"):
        response = await runs_app.post("/runs", json=_RUN_BODY, headers={"X-User-Email": " Ada@Example.ORG "})
    assert response.status_code == 201
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("run created ")]
    assert f"owner={owner_key('ada@example.org')}" in line
    assert f"run={response.json()['id']}" in line
    assert "benchmark=mmmu cases=3 candidates=2 created=True" in line
    assert "@" not in "\n".join(r.getMessage() for r in caplog.records)
```

- [ ] **Step 2: Run it to verify it fails** — `uv run pytest tests/unit/test_run_visibility_lines.py -v` → FAIL (no `run created` record).
- [ ] **Step 3: Implement** — in `create_run`, after `record, created = await registry.register(owner, spec)`: `_logger.info("run created run=%s owner=%s benchmark=%s cases=%d candidates=%d created=%s", record.id, owner, record.benchmark, record.case_count, len(record.candidates), created)`; add `_logger = logging.getLogger(__name__)` if the module has none. WHY the count, not names: Candidate names are the caller's text.
- [ ] **Step 4: Run it to verify it passes.**
- [ ] **Step 5: Commit** — `feat(engine): log "run created" with the owner key and the Run facts (OME-1924)`.

### Task 2: `run scheduled` gains `owner`, `run`, `candidate`

**Files:**
- Modify: `rest/runs_start.py` (`StartBinding` gains `run_id: str | None = None`, `candidate: int | None = None`; `bind_start` fills them for a bound start)
- Modify: `rest/routes.py` (`_schedule` gains keyword-only `owner: str`, `run_id: str | None`, `candidate: int | None`; the `run scheduled` line at `:403-408` becomes
  `"run scheduled topic=%s url4_chars=%d cache=%s owner=%s run=%s candidate=%s"`; `start_run` computes `owner = request_caller(request) or "anonymous"` and passes `binding.run_id`, `binding.candidate`)
- Test: append to `tests/unit/test_run_visibility_lines.py`

**Interfaces:**
- Consumes: `request_caller(request) -> OwnerKey | None` (`rest/runs_boundary.py:168`), `StartBinding` (`rest/runs_start.py:97`).
- Produces: the extended line; `run=-` and `candidate=-` for an unbound start.

- [ ] **Step 1: Write the failing tests** (start a run the way `test_selector_refusal.py::test_the_run_scheduling_log_names_no_profile` does, once with `X-SF-Run`/`X-SF-Run-Candidate` through a bound Run and once unbound):

```python
async def test_scheduled_owner_matches_run_history_key(caplog, ...) -> None:
    # identity " Ada@Example.ORG " → owner=owner_key("ada@example.org"); no "@" in any record
async def test_a_bound_start_logs_run_and_candidate(caplog, ...) -> None:
    # "run=<id> candidate=1" present
async def test_an_unbound_start_logs_dashes(caplog, ...) -> None:
    # "run=- candidate=-" present; owner is "anonymous" when no identity header on a hosted app
```

- [ ] **Step 2: Run to verify they fail** (`KeyError`/missing fields).
- [ ] **Step 3: Implement** the three edits above. Unknowns render as `-` through one tiny helper `_dash(value) -> str` in `routes.py`.
- [ ] **Step 4: Run the new tests and `tests/unit/test_selector_refusal.py tests/unit/test_run_evidence_lines.py` to verify all pass** (existing `run scheduled` assertions only check containment).
- [ ] **Step 5: Commit** — `feat(engine): name the owner key, Run and Candidate on "run scheduled" (OME-1924)`.

### Task 3: runner `run claimed` and `run finished` lines

**Files:**
- Modify: `worker/supervisor.py` — `_claim` (after `_already_settled`, before `_run_child`): `logger.info("run claimed topic=%s waited_s=%s", topic, _seconds(self._waited_s(msg)))`; `supervise` passes `started` into `_supervise(msg, started)`; `_supervise` logs in a `finally` inside `run_scope(topic)`: `logger.info("run finished topic=%s outcome=%s ran_s=%.0f", topic, self._outcomes.pop(topic, "unknown"), time.monotonic() - started)`; `_publish_terminal` and `_publish_ending` record `self._outcomes[topic] = status`; the duplicate-claim branch records `"duplicate"`, the undecodable path logs nothing (no topic).
- Test: `tests/unit/test_supervisor_visibility_lines.py` (new; fakes from `test_supervisor_outcomes.py`)

**Interfaces:**
- Consumes: `_published_at(msg) -> datetime | None` (`supervisor.py:983`).
- Produces: `_waited_s(msg) -> float | None` (= `(now_utc - published).total_seconds()` or `None`); module helper `_seconds(value: float | None) -> str` (`"-"` or `f"{value:.0f}"`).

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_claim_logs_how_long_the_run_waited(caplog, ...)  # ENQUEUED_AT_HEADER 42 s ago → "waited_s=42"
async def test_a_claim_without_a_stamp_logs_a_dash(caplog, ...)   # header absent and metadata None → "waited_s=-"
async def test_a_finished_run_logs_its_outcome(caplog, ...)       # normal end → "run finished topic=t outcome=finished ran_s="
async def test_a_duplicate_claim_logs_outcome_duplicate(caplog, ...)
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** as above; keep `_claim`'s `max-returns = 3` (no new return).
- [ ] **Step 4: Run the new file plus `tests/unit/test_supervisor_outcomes.py tests/unit/test_worker_claim.py tests/unit/test_supervisor_launch.py` to verify all pass.**
- [ ] **Step 5: Commit** — `feat(engine): runner logs "run claimed" with the queue wait and "run finished" with the outcome (OME-1924)`.

### Task 4: the notice carries waiting and running counts

**Files:**
- Modify: `unclaimed.py` — `UnclaimedRunWarner.__init__(..., demand: Callable[[], tuple[RunnerDemand, datetime, float] | None] | None = None)`; `_warn_if_unclaimed` reads `waiting = getattr(self._runs, "queue_snapshot", lambda: (None, None))()[0]`, `running = (d[0].running if (d := self._demand()) else None) if self._demand else None`; attributes gain `"run.queue_waiting": waiting` only when `waiting is not None`; the log line becomes `"unclaimed run warned topic=%s wait_s=%.0f waiting=%s running=%s"` with `-` for unknowns.
- Modify: `app.py::_install_unclaimed_run_warner` — pass `demand=lambda: _demand_fresh(app)` where `_demand_fresh` returns `sampler.fresh()` for `sampler = getattr(app.state, "runner_demand", None)` else `None`.
- Test: `tests/unit/test_unclaimed_run_warner_counts.py` (new; reuse the `_Runner`/`_Audience` shapes by copy — do not edit the existing file)

**Interfaces:**
- Consumes: `QueueJobRunner.queue_snapshot() -> tuple[int | None, float | None]` (`adapters/queue_runner.py:704`), `RunnerDemandSampler.fresh()` (`runner_demand.py:122`), `RunnerDemand.running`.
- Produces: attribute key `run.queue_waiting` (int).

- [ ] **Step 1: Write the failing tests**

```python
async def test_the_notice_log_line_names_waiting_and_running(caplog)  # runner.queue_snapshot → (6, 310.0); demand → running 8 → "waiting=6 running=8"; attributes == {"run.wait_s": 301, "run.queue_waiting": 6}
async def test_unknown_counts_log_dashes_and_add_no_attribute(caplog)  # no queue_snapshot, demand None → "waiting=- running=-"; attributes == {"run.wait_s": 301}
async def test_a_stale_demand_sample_logs_running_dash(caplog)         # demand() returns None → "running=-"
def test_the_message_text_is_unchanged()                               # UNCLAIMED_MESSAGE equality, as the existing test
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `unclaimed.py` and the `app.py` wiring; `test_unclaimed_run_warner_wiring.py:175` must still pass.
- [ ] **Step 4: Run the new file plus `tests/unit/test_unclaimed_run_warner.py tests/unit/test_unclaimed_run_warner_wiring.py` to verify all pass.**
- [ ] **Step 5: Commit** — `feat(engine): the unclaimed-run notice logs waiting and running counts (OME-1924)`.

### Task 5: ledger, mirror, gates

**Files:**
- Modify: `docs/work/2026-11-16-queue-visibility-logs.md` (status, Outcome)
- Create: `docs/tasks/2026-11-16-OME-1924-queue-visibility-logs.md` (mirror, `status: in_review`, parent `OME-1314`, labels `[screamingface-engine, agentic, design-session]`)

- [ ] **Step 1:** `python3 .claude/scripts/run_gates.py screamingface-engine --base origin/main` → `ALL GATES GREEN`.
- [ ] **Step 2:** `python3 .claude/scripts/run_gates.py repo --base origin/main` → `ALL GATES GREEN`.
- [ ] **Step 3:** Fill the ledger Outcome (files, commits, gate lines, deviations: the evidence `log_scheduled` line keeps topic↔trace↔job only; the routes line carries identity — spec said both).
- [ ] **Step 4: Commit** — `docs(work): OME-1924 part 1 ledger and mirror`.
- [ ] **Step 5:** Rename the branch `git branch -m OME-1924-queue-visibility-logs`, push, open the PR (`Refs: OME-1924`, Linear link) after the owner's confirmation; move OME-1924 to In Review.

## Self-review notes

- Spec coverage: §Design 1 → Task 1; 2 → Task 2 (routes line only — recorded as a deviation in Task 5); 3 → Task 3; 4 → Task 4; tests incl. the `@` ratchet → each task's first test asserts `"@" not in` the joined records.
- Type consistency: `_seconds`/`_dash` are two helpers in two modules on purpose (worker and rest never import each other).
- Proportion: 5 tasks, ~15 lines of production code per task.
