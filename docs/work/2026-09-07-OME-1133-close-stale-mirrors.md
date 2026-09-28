---
ticket: OME-1133
stack: repo
status: done
started: 2026-09-07
finished: 2026-09-07
---

# OME-1133 — Close the five stale docs/tasks mirrors and work ledgers

## Intent

Five observability work items shipped and are **Done** in Linear, but their repo-side mirrors
and ledgers on `main` still read `status: in_progress` with an empty `finished:`. The card
makes Linear the status authority and the mirror its repo-side reflection; a reader working
from the checkout alone — the normal case for anyone reading the repo cold — currently sees
five items apparently still in flight while Phase 1 is actively being built on top of them.
That is how a duplicate ticket gets filed for merged work.

Stated plainly: each of those PRs closed its Linear issue but not its mirror. Five in a row is
a process defect, not five slips. Recorded rather than quietly fixed.

## Planned changes

Frontmatter only — `status: in_progress` → `done`, and `finished:` → the PR's merge date. No
prose is rewritten and no ledger Outcome section is touched; those are already filled.

| Item | Merged | Files |
|---|---|---|
| `OME-967` | 2026-09-02 (#789) | `docs/tasks/2026-08-24-OME-967-client-originates-traceparent.md` · `docs/work/2026-09-01-OME-967-client-originates-traceparent.md` |
| `OME-990` | 2026-09-02 (#780) | `docs/tasks/2026-08-25-OME-990-runtime-log-prompts.md` · `docs/work/2026-08-31-OME-990-runtime-access-log-off.md` |
| `OME-1074` | 2026-09-02 (#812) | `docs/tasks/2026-09-02-OME-1074-e2e-traceability-notebook.md` · `docs/work/2026-09-02-OME-1074-e2e-traceability-notebook.md` |
| `OME-1105` | 2026-09-03 (#831) | `docs/tasks/2026-09-03-OME-1105-correlation-chain-e2e.md` · `docs/work/2026-09-03-OME-1105-correlation-chain-e2e.md` |
| `OME-1121` | 2026-09-07 (#842) | `docs/tasks/2026-09-04-OME-1121-report-trace-id.md` · `docs/work/2026-09-04-OME-1121-report-trace-id.md` |

Plus this ledger and the `OME-1133` mirror, both closed in the same change — the defect this
unit fixes is exactly "the mirror close was deferred", so deferring it here would be absurd.

## Test plan

There is no code under change, so there is no failing test to write first. The verifiable
claim is a state one, and it is checked mechanically rather than by eye: no file under
`docs/tasks/` or `docs/work/` naming a Linear-Done item may carry `status: in_progress`. The
check is run before and after — it must list ten files before and none after.

## Acceptance

- All ten files read `status: done` with a `finished:` date matching their PR's merge date.
- No prose or Outcome content changed — the diff is frontmatter lines only.
- `OME-1133`'s own mirror and this ledger are closed in the same commit.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — ten frontmatter edits across `docs/tasks/` and `docs/work/`,
  plus this ledger and `docs/tasks/2026-09-07-OME-1133-close-stale-mirrors.md`.
- **Commits:** `docs(tasks): close the five stale observability mirrors and ledgers` (sha at
  squash-merge).
- **Gates:** no stack gate applies — the change touches `docs/` only, so no
  `run_gates.py <stack>` lane is triggered and CI's path filters run nothing. The verifiable
  claim was checked mechanically instead: the scratchpad checker listed **10 stale files
  before and 0 after**, and `git diff -U0` confirms **20 changed lines, every one a
  `status:`/`finished:`/`closed:` field** — no prose or Outcome content altered.
- **Deviations:**
  - **The checker had a bug that would have let this unit pass falsely.**
    `finished:[ \t]*(\S*)` was first written with `\s*`, which crosses the newline on an empty
    field and captures the `---` fence below it — so a file marked `done` with **no date**
    would have reported `ok`. Caught on the baseline run (`finished=---` for every stale
    file), fixed to `[ \t]*`, and the baseline re-run before any edit. Worth recording: a
    check that cannot fail is the same defect class as a mirror that is never closed.
  - **No enforcement gate was added**, deliberately. `run_gates.py` cannot see Linear state,
    so a mechanical "mirror closed at merge" check needs a decision about where it lives
    (PR template · CI job reading the Linear API · close-time step in the SDLC skill). Left
    to its own item rather than guessed at here.
