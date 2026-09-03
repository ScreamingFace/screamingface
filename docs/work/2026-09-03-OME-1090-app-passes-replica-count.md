---
ticket: OME-1090
stack: screamingface-engine
status: in_progress
started: 2026-09-03
finished:
---

# OME-1090 — the App's composition root passes the queue's replica count

## Intent

`build_job_runner` builds the `QueueJobRunner`'s `RunQueue` for the serving half, and it
omitted `replicas` — so the App declared the queue stream with the code default regardless of
configuration. OME-1088 made the count a setting and OME-1089 wired the worker half; this
completes the pair.

The App half is the one that usually declares the stream first, because the App accepts a run
before any worker pulls it. `ensure_stream` refuses a declaration whose properties diverge
from an existing stream, so leaving this half unwired means the App and the worker can
disagree — and on a clustered broker the second declarer fails at startup.

Found by manual e2e deployment of the OME-1086 stack on a single-node kind cluster
(2026-09-03 findings, B2).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/adapters/factory.py` — pass
  `replicas=settings.run_queue_replicas` in the `queue` branch of `build_job_runner`.
- `apps/screamingface-engine/tests/unit/test_factory_queue_replicas.py` — NEW file
  (tests are append-only; no prior test is touched).

## Test plan

- The App's queue carries the CONFIGURED replica count, asserted with a non-default value so
  a dropped argument cannot pass.
- The default path yields the single-node-safe count.
- The invariant that matters: for any `Settings`, the App half and the worker half declare the
  SAME replica count — the property whose absence `ensure_stream` turns into a startup failure.

## Acceptance

- `build_job_runner(settings)` produces a runner whose queue uses `settings.run_queue_replicas`.
- `run_gates.py screamingface-engine` green.

## Outcome

- **Actual files:** as planned, plus a typing-only repair to four prior test files
  (see Deviations).
  - `src/screamingface_engine/adapters/factory.py` — the `queue` branch passes
    `replicas=settings.run_queue_replicas`, with the declare-order invariant anchored.
  - `tests/unit/test_factory_queue_replicas.py` — NEW.
  - `tests/unit/test_max_deliveries_advisory.py`, `test_queue_runner_cancel.py`,
    `test_runners_factory.py`, `test_worker_claim.py` — EDITED, typing only.
- **Commits:**
  1. `fix(engine): satisfy pyright across the queue and worker tests`
  2. `fix(engine): the App declares the queue with its configured replica count`
- **Gates:** `run_gates.py screamingface-engine --skip-append-only`. RED was observed first
  and for the right reason: `KeyError: 'replicas'` on all five new tests. Notably the
  cross-half test failed on the APP side only, confirming OME-1089 had already wired the
  worker.
- **Deviations:**
  1. **This branch carried 14 pyright errors of its own**, on top of the 5 fixed on
     OME-1089 — in `test_max_deliveries_advisory.py`, `test_queue_runner_cancel.py`,
     `test_runners_factory.py` and `test_worker_claim.py`. Measured across the stack, the
     breakage is systemic: #819 red, #821 at 22 errors, #822 at 23. **No PR from #818
     upward has ever had a green CI run.** The owner was shown these numbers and gave a
     blanket approval to repair them per branch as typing-only commits.
  2. **Four prior test files were edited, typing only.** No assertion, fake behavior or
     test meaning changed: a `Literal` status parameter, a helper widened to the production
     `_ControlClient` Protocol (rather than a union — both fakes already satisfy it), an
     `assert isinstance(runner, QueueJobRunner)` narrowing plus casts where the tests reach
     private collaborators through Protocol-typed attributes, and one fake bound to a local
     instead of read back through a Protocol-typed field. No `# type: ignore` was used
     anywhere — the stack card forbids it. Landed as its own commit for independent review.
  3. **The mechanical repair was delegated** to an implementer subagent against an explicit
     error list and fix-pattern spec; its diff was reviewed line by line here before being
     accepted. The substantive wiring and its tests were written in the main loop.
  4. **The delegated agent's work was silently lost and had to be recovered.** It ran
     `git stash` instead of leaving changes in the tree, and the stash stack is shared across
     every worktree in the clone — so 14 reviewed-and-accepted fixes vanished from this
     worktree with nothing in `git status` or `git log` to show it. The gate re-reporting the
     original 14 errors is what caught it. Recovered by matching the stash entry to this
     worktree's HEAD, verifying its contents, and `git stash apply` BY SHA (never `pop`:
     `stash@{1}` and `{2}` belong to other sessions). Delegation prompts must forbid `git
     stash` explicitly, not just `git commit`.
  5. **`test_worker_composition_replicas.py` was retargeted** from `run_worker` to
     `worker_composition`. It is a prior test — authored on OME-1089 one commit below — and it
     did not merely fail here, it HUNG: OME-1090 gives `run_worker` a real
     `nats.connect(settings.nats_url)` for the run-control channel, so a unit test driving it
     blocks on a live broker. The same OME-1090 change extracted `worker_composition` for
     exactly this reason (its own docstring says so), which is the seam the test now uses.
     **No assertion, parameter or expected value changed** — only the entry point — so this
     adapts a test to a legitimate refactor rather than weakening it to make new code pass.
     An `AIDEV-NOTE` at the helper records the move and why.

## Follow-ups surfaced (not in this unit)

- The stack's test suite reaches into private collaborators (`runner._queue._stream`) in
  several places, which is what makes it fragile under pyright. A cleaner seam — exposing
  what the tests actually need to assert — would be worth considering, but changing test
  structure is out of scope for a blocker fix.
