---
ticket: OME-1106
stack: repo
started: 2026-09-03
status: in_progress
finished:
---

# OME-1106 — Setup validator for the traceability e2e lanes

## Intent

Running the traceability rungs needs a chain of prerequisites that is only discoverable by
hitting each one in turn. Every item below was found the hard way during `OME-1105`: the
`[runtime]` extra, prepared draco assets, a Docker daemon, `SCREAMINGFACE_TEST_E2E=1`, a
client build carrying `OME-967`, and — for the k8s lane — a kubectl context that currently
does not resolve at all.

The dangerous one is the assets: without them **every rung skips**, and `pytest` exits `0`.
An all-skipped run looks exactly like a passing run to anyone reading the exit code, which is
the single most likely way for someone to believe the chain was validated when nothing ran.

## Design decisions

**D1 — read-only and offline-safe.** The validator probes local state only. It does not SSH,
authenticate, or contact a cluster. Bastion reachability is reported **unknown**, not tested:
probing it is a credentialed action belonging to the operator, and an automated tool that
silently opens sessions to a jump host is the wrong default.

**D2 — `importlib.util.find_spec`, not imports, for the runtime extra.** Importing `litellm`
to check presence is slow and has side effects (it installs logging handlers at import time —
see `OME-1050`). `find_spec` answers the same question without executing the package.

**D3 — exit code reflects the LOCAL lane only.** The local e2e lane is the one that can
actually be made green on a laptop; the k8s lane depends on credentials nobody here controls.
Failing the exit code on the k8s lane would make the validator permanently red and therefore
ignored.

## Planned changes

- `e2e/failor/check_setup.py` — the validator.
- `e2e/failor/notebooks/README.md` — point at it.
- This ledger + the `docs/tasks/` mirror.

## Test plan

No stack gates apply (new file in a top-level directory outside every path filter) — but
**ruff runs repo-wide via pre-commit**, which `OME-1074` established the hard way, so
`ruff check` and `ruff format --check` must be clean. Verification:

- the script runs on this machine and reports a truthful table (verified against the state
  established during `OME-1105`: Docker up, runtime extra installed, draco assets present,
  kubeconfig broken);
- it exits non-zero when a local-lane prerequisite is missing and zero when they are all met;
- it never performs a network or credentialed action.

## Acceptance

- One command reports per-lane readiness with an exact remedy for each missing item.
- It states plainly that a skipped rung proves nothing.
- Clean ruff; no network access.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `e2e/failor/check_setup.py`,
  `e2e/failor/notebooks/README.md` (pointer), the ledger and the mirror.
- **Commits:** `feat(e2e): add a setup validator for the traceability lanes` (sha at
  squash-merge).
- **Gates:** `ruff check` + `ruff format --check` clean (they run repo-wide via pre-commit —
  `OME-1074` established that the hard way). No stack gate applies. **Both exit paths were
  observed**, not reasoned about: `exit=1` with two prerequisites missing, then `exit=0` with
  all five green after `uv sync --extra runtime` in this worktree.
- **Deviations:**
  - **The first version probed the wrong interpreter, and running it caught that.** It used
    the in-process `importlib.util.find_spec`, but the script is invoked as
    `python3 e2e/failor/check_setup.py` from the repo root — so it probed whatever python is
    on PATH, not the client venv, and reported the `[runtime]` extra missing while it was
    installed in the only environment that runs the lane. A validator that lies about
    readiness is worse than no validator. It now probes
    `packages/screamingface/.venv/bin/python` explicitly and labels which interpreter it
    used, falling back with the fallback named in the output.
  - The firecall bastion details (`firecall@172.190.209.255`, AKS `aks-dev-eastus` in
    `rg-aks-platform-dev-eastus`, namespaces `sf-aigw` / `sf-fusion` / `sf-scoreboard`) are
    recorded as constants so nobody has to SSH in to rediscover them. Reachability is
    deliberately NOT probed — see D1.

## Round 2 — review fixes (2026-09-10, PR #832)

@IonesioJunior reviewed and did not approve. Two bugs, both making the script print
`LOCAL LANE READY` for a lane that is not ready — the exact failure it exists to prevent.
Both were real and both reproduced.

**R1 — the validator accepted an assets location the ladder never reads.** `_assets()` looked
in three places; `test_correlation_chain.py::_assets_root` looked in two, and the home-directory
default was not among them. So with assets where `screamingface prepare` actually writes, the
script said `OK` and every rung still skipped — and an all-skipped run exits 0.

**The fix went into the TEST, not the validator**, which is the reviewer's own suggestion and
the right half. `test_boards.py:63-71` and `test_failures.py:365-372` both default to
`default_data_dir() / "benchmark-assets"`, carrying an explicit `OME-1001` comment: *"it is
where `screamingface prepare` writes, so the assets a dev prepares for the stack are the assets
these tests find."* The ladder was the sole outlier, defaulting to `FIXTURES_DIR / "assets"` — a
path `prepare` never writes and the repo does not ship. Aligning the validator instead would
have codified the outlier and left the ladder needing a hand-set override forever.

**This was already costing time and was misread as a local quirk.** During `OME-1119` the
ladder had to be run as `SCREAMINGFACE_E2E_ASSETS=$PWD/tests/e2e/fixtures/assets/benchmark-assets`
after `prepare --data-dir` wrote one level deeper than the test looked. That was this bug,
diagnosed as an environment wrinkle and worked around instead of fixed.

**R2 — `UNKNOWN` did not block.** `blocked = [c for c in local if c.state == MISSING]` asks
"which failed" when three states demand "which did not succeed". `UNKNOWN` means *could not
check* — an unsynced venv, a failed probe — and readiness cannot be concluded from a check that
never ran. In that state the script printed READY and exited 0, while the run would die at
import. Worse than the skip case: a skip is silent, this promises an outcome that cannot happen.
Now `!= OK`, and the summary distinguishes "N missing, M unverifiable".

**R3 (reviewer's smaller point) — `SCREAMINGFACE_DATA_DIR` was ignored.** The old code hardcoded
`Path.home() / ".screamingface"`, but `default_data_dir()` honours that variable first
(`_runtime/config.py:12-16`). Fixed structurally rather than by copying the rule: the validator
now *asks the client* for its data dir via the venv interpreter it already probes, so the two
cannot drift again.

**R4 (reviewer's smaller point) — the printed ready command now echoes the override** when one
is set, so the command shown is the command that was validated.

**R5 (found here, not in review) — the printed expectation was stale.** It promised
`5 xfailed, 0 failed`, which stopped being true when rungs 1 and 2 went green (`OME-1121`,
`OME-1119`). A validator that states a wrong expected outcome trains the reader to ignore a real
regression. Now `2 passed, 3 xfailed, 0 failed`, naming the two tickets.

**Verified end to end, not reasoned about:** with the venv synced and no override set, the
validator reported all five checks `OK`, and running the command it printed **verbatim** gave
`2 passed, 3 xfailed` — the outcome it promised. Before the fix that same command skipped all
five. The unsynced-venv path was exercised too: `exit=1`, "2 missing, 2 unverifiable".

**Not addressed, and it is why these shipped:** `check_setup.py` has **no tests and no CI gate**
— nothing under `.github/workflows/` matches `e2e/failor/**`. Both bugs are pure logic in an
ungated file, so nothing could have caught them but a human reading it. Raised as a question for
the owner rather than fixed here: the script is a standalone tool outside any uv project, so
giving it a test home is a real decision, not a detail.

**Gates:** `run_gates.py screamingface --skip-append-only` — **ALL GREEN**. Append-only flagged
`test_correlation_chain.py` for the **fourth** consecutive time; benign by count — test functions
5 → 5, assertions 14 → 14, xfail markers 10 → 10, the change confined to the `_assets_root`
helper with no assertion touched.
