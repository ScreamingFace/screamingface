---
ticket: OME-798
stack: scoreboard
status: in_review
started: 2026-08-13
finished: 2026-08-14
---

# OME-798 — run the portal's JS tests in CI and in the scoreboard gate list

## Intent

`OME-769` (merged as `2a20c154`) shipped `apps/scoreboard/tests/portal/leaderboard-logic.test.js`
— 14 tests covering the board's load-bearing judgements: which row may be presented as
state-of-the-art, row ordering, and accuracy-bar scaling. **Nothing runs them.** Neither
`scoreboard-tests.yml` nor `run_gates.py scoreboard` knows they exist, so the invariant "only a
reproducible entry may be presented as SOTA" is protected by a test no pipeline executes.

This unit makes an existing command run in the two places that gate a merge. No new dependency:
Node ships the runner, so there is no `package.json`, no vitest, no lockfile, no dependabot
ecosystem and no new release lane.

## Decisions locked (2026-08-13) — all evidence-backed, none assumed

The ticket warned that "a test step that silently collects zero tests is worse than no step,
because it reads as coverage". That is not hypothetical here — **two of the three obvious
invocations do exactly that.** Measured on Node v24.10.0:

| Invocation | Result | Exit |
|---|---|---|
| `node --test tests/portal/` | **fails** — Node 24 resolves the directory as a module | non-zero, but for the wrong reason |
| `node --test "tests/portal/*.test.js"` (quoted) | `pass 0, fail 0` when nothing matches | **0 — silently green** |
| `node --test tests/portal/*.test.js` (unquoted) | same: **Node itself expands globs**, so the shell not matching changes nothing | **0 — silently green** |
| `node --test tests/portal/leaderboard-logic.test.js` | runs 14 tests; **errors if the file is absent** | 1 on failure or absence |

| # | Decision | Choice |
|---|---|---|
| D1 | Invocation | **Explicit file path.** It is the only form that is loud when the tests are not there. A glob that stops matching — file renamed, directory restructured — would leave a permanently green step covering nothing, which is precisely the failure this ticket exists to prevent. |
| D2 | Accepted trade-off | A second test file added later will **not** run until it is named here. That is the lesser risk: a missing file fails loudly (exit 1), whereas an empty glob passes silently. Both the workflow and the card name the file, and an `AIDEV-NOTE` at each site says to add new files explicitly. |
| D3 | Shell portability | `run_gates.py` executes gates via `subprocess.run(..., shell=True)`, i.e. `/bin/sh`, while CI uses bash and this machine uses zsh — and unmatched globs behave differently in all three (zsh aborts outright). An explicit path has no glob semantics to reason about, so it behaves identically everywhere. |
| D4 | Node version in CI | Pin a `setup-node` version rather than inherit the runner default, since the directory-form breakage is version-specific and a silent runner upgrade should not change what the step does. |
| D5 | Scope | CI + the gate card only. No vitest/jsdom, no DOM-level tests, no JS toolchain — that would be the "adding a new component" checklist and its own ticket. |

## Planned changes

- `.github/workflows/scoreboard-tests.yml` — add `actions/setup-node` and a step running the
  portal tests.
- `.claude/sdlc.local.md` — add the same command to the `scoreboard` stack's `gates:` list, so
  `run_gates.py scoreboard` covers it locally and the card stops under-describing the stack.

## Test plan

This unit wires up an existing test suite, so "RED first" is about the **wiring**, not new
assertions. Verified by observation, not by reading YAML:

- `run_gates.py scoreboard` does **not** run the JS tests before the change, and **does** after.
- With an assertion deliberately broken, the JS command exits **1** and `run_gates.py` reports a
  failed gate — confirmed before the change is called done, then reverted.
- The three rejected invocations are measured, not assumed (table above).
- The workflow's path filters already cover `apps/scoreboard/**`, so no trigger change is needed —
  confirm rather than assume.

## Acceptance

- `scoreboard-tests.yml` runs the portal JS tests on PRs touching `apps/scoreboard/**`.
- `run_gates.py scoreboard` runs them too, and the card lists the command.
- Breaking an assertion demonstrably reds both, verified rather than assumed.
- The tests stay out of the shipped image (they live in `tests/`, which the Dockerfile does not
  copy — `portal/` is copied wholesale, which is why they were placed outside it).

## Outcome

- **Actual files:** exactly as planned — `.claude/sdlc.local.md` (one gate + the rationale comment)
  and `.github/workflows/scoreboard-tests.yml` (pinned `setup-node@v6` + one step). No production
  code, no test changes, no new dependency.
- **Gates:** `run_gates.py scoreboard --base origin/main` → append-only ✓, ruff check ✓,
  ruff format ✓, pyright ✓, pytest --cov ✓, **`node --test tests/portal/leaderboard-logic.test.js` ✓
  (new)**. ALL GATES GREEN — six gates where there were five.
- **Verification — the falsifiability check the ticket asked for:** broke an assertion and confirmed
  the runner reports `✗ node --test tests/portal/leaderboard-logic.test.js (exit 1)` and surfaces
  `AssertionError: OME-798 deliberate break`, then restored and re-confirmed green. The step is
  therefore proven to fail, not merely observed to pass.

### Deviations

1. **My first attempt at that verification proved nothing, and I nearly recorded it as if it had.**
   Breaking an assertion in a file that exists on `origin/main` trips the **append-only check**,
   which runs first and aborts the run — so the output was `GATE FAILED`, but for editing a prior
   test, never reaching the JS gate at all. Re-run with `--skip-append-only` to actually exercise it.
   Worth keeping: a red gate runner is not evidence that *the gate you care about* is red.
2. **Three invocations were measured rather than reasoned about, and two of my predictions were
   wrong.** I expected an unquoted glob to pass the unmatched literal to Node and error; it does not
   — **Node expands globs itself**, so quoted and unquoted behave identically and both exit `0` with
   `pass 0`. That is the silent-green failure mode the ticket warned about, and it was one plausible
   line away from being shipped. Full table in the spec §2.
3. **A test file added later will not run until named** (D2). Accepted: a missing explicit path
   exits 1, an empty glob exits 0, so the explicit form fails in the safer direction. Both call
   sites carry an `AIDEV-NOTE` saying to add files by name.
4. **`#516` edits the same workflow file** and is awaiting review. Distinct steps, so a trivial
   merge; whichever lands second rebases.
5. No PR was open at the time of writing this section. Superseded: `11b7c95d` and `d93a3c39`
   are open as [#595](https://github.com/ScreamingFace/screamingface/pull/595), CI green,
   awaiting review.

## Review pass (2026-08-14) — four findings, all valid

| Finding | Fix |
|---|---|
| The explicit path guards renames but **not additions** — a new test file silently never runs | new `tests/unit/test_portal_ci_wiring.py` |
| The gates now need local Node, undocumented | `working-in-this-repo` + scoreboard README |
| `setup-node@v6` while five other workflows use `@v7`, and the comment reads as forbidding a bump | bumped to `@v7`, comment clarified |
| The JS step ran before pytest, so a JS failure buried the real cause | moved after pytest |

### The additions hole — the sharpest of the four

D2 accepted that a later test file would not run until named. The reviewer's point is that this is
**the same "believed tested" failure the explicit path was chosen to avoid**, just relocated: a renamed
file fails loudly, an added one is silently ignored at both call sites.

Fixed without reopening the worse hole. A glob would close additions but exit `0` with `pass 0` when
it matches nothing, so the invocation stays explicit and a **test** now enforces completeness: every
`tests/portal/*.test.js` must appear by name in both `scoreboard-tests.yml` and `.claude/sdlc.local.md`.
It also asserts the directory is non-empty, so it cannot pass vacuously.

**Proven falsifiable:** created `tests/portal/zz_new.test.js` and both parametrised cases failed
naming it (`does not run: ['zz_new.test.js']`); removed it and all three passed.

### The Node prerequisite

`working-in-this-repo` listed scoreboard as Python/uv only and called aigateway-ui "the repo's only
non-Python stack" — both now false, so a Python-only dev would have hit `node: command not found` and
a gate failure naming no prerequisite. The stack row, its note, and the aigateway-ui claim are
corrected, and the scoreboard README's Development block now shows the command.

Worth recording: the reviewer also observed that "local gates and CI cannot disagree" is true of the
**command string**, not the **runtime** — CI pins Node 24, local uses whatever is installed. The docs
now say so rather than implying parity.

### Step order

As an earlier step, a JS failure left `results.xml`/`coverage.xml` unwritten, so both `if: always()`
reporter steps failed on missing paths — three red steps burying one real cause. The JS step now runs
after pytest.

**Gates:** all six green, including the new wiring test.
