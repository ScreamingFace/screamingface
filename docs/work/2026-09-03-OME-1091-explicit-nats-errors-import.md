---
ticket: OME-1091
stack: screamingface-engine
status: in_progress
started: 2026-09-03
finished:
---

# OME-1091 — import `nats.errors` explicitly in the run queue

## Intent

`runner_queue.py` catches `nats.errors.Error` in the pull path (`:537`) while importing only
the `nats` package. `nats.errors` is a SUBMODULE: `import nats` does not bind it. The name
resolves today purely because `from nats.aio.client import Client` on the next line happens to
import `nats.errors` as a side effect, which populates the attribute on the parent package.

That is an accident, not a contract. If `nats.aio.client`'s own imports change in any future
version, this `except` clause raises `AttributeError` — **while handling an error**, on the
broker-failure path, which is the worst possible place to discover it. The pull guard that
exists to keep one blip local would itself become the failure.

Surfaced by the pyright gate while rebasing this branch onto the fixed OME-1090. It is the last
error standing between this branch and a green gate; the rest of the stack's pyright breakage
was repaired on OME-1089 and OME-1090.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` — add
  `import nats.errors` beside the existing `import nats`.

## Test plan

No new test. The change binds a name that already resolves at runtime, so there is no
behavior a test could distinguish before and after — the existing pull-path tests on this
branch already cover the `nats.errors.Error` branch they exercise. The pyright gate is the
driver here, and it is the thing that would regress.

## Acceptance

- `uv run pyright` reports 0 errors on this branch.
- `run_gates.py screamingface-engine` green, with the whole prior suite unchanged.

## Outcome

- **Actual files:** as planned — `src/screamingface_engine/runner_queue.py` only.
- **Commits:** `fix(engine): import nats.errors explicitly in the run queue`
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` — ALL GATES GREEN
  (ruff check · ruff format --check · pyright · check_layering · pytest --cov ≥80). Green on
  the first attempt.
- **Deviations:**
  1. **This branch needed no B2 wiring of its own.** The replica-count changes reached it
     through the rebase onto OME-1090, which is the intended behaviour of a stacked series.
     Its only change is the import above.
  2. **The rebase onto the fixed OME-1090 hit two conflicts, both resolved by keeping BOTH
     sides** — never by dropping either:
     - `factory.py` and `worker/loop.py`: this branch adds `bucket_count=` at the same
       position where OME-1090 added `replicas=`. Both kwargs are now passed.
     - `test_runners_factory.py`: this branch adds an `assert ..._subject_prefix` where
       OME-1090 introduced the `isinstance` narrowing and casts. The new assertion is kept,
       expressed through the narrowed locals.
  3. **`--skip-append-only` was used** because the branch carries the owner-approved
     prior-test edits from OME-1089/OME-1090 beneath it. No prior test was edited in THIS
     unit beyond the conflict resolution above, which preserves this branch's own assertion.

## Follow-ups surfaced (not in this unit)

- The same latent shape may exist elsewhere: any module doing `import nats` and then reaching
  `nats.errors` / `nats.js.errors` through the parent package works only by transitive-import
  accident. Worth a sweep, but out of scope for a blocker fix.
