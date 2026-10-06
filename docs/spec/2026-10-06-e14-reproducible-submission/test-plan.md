# Test plan — E14 reproducible submission

This plan collects the TDD tables of the four PRDs. It adds the cross-cutting rules. Source tags
follow `00-overview.md` §3.

## 1. Ground rules (each PR inherits them)

- **RED first.** Write the test, run it, and see it fail for the right reason (an assertion on the
  missing behaviour, not an import error). A test that passes at once proves nothing. The exception
  is the `CHAR` tests: they pin today's behaviour and pass on today's code, by design.
- **GREEN with the smallest change.** Refactor only on green.
- **One behaviour for each test.** The test name states the behaviour.
- **Append-only test gate.** Do not edit or delete an existing test. An approved exception needs
  `--skip-append-only` and a note in the work ledger.
- **Gates for each PR:** `run_gates.py <stack> --base <parent branch>` and `check_layering.py`. In a
  fresh worktree, the SDK gates need `uv sync --extra runtime --extra notebook`.
- **Postgres tests** (the scoreboard row lock, unique indexes, migrations) need Docker. When Docker
  is missing, the PR says so. Such a test is never marked as passed.

## 2. Risk register (it drives the order of the tests)

Scales: Impact H/M/L × Likelihood H/M/L (qa-tester rubric).

| ID | Risk | I×L | Covered by |
|---|---|---|---|
| RK1 | A replay pays a provider (a bypass, a re-issue, a Tavily call, an old gateway or an old engine) | H×M | gw #10–#12; rp #2–#6, #23 |
| RK2 | An old label stops producing its old keys after a code change | H×M | gw #2, #6, #7 |
| RK3 | A constant changes and no registry entry is added | H×M | gw #3, #5 |
| RK4 | A user who is not the owner edits a score, or reads its edit log | H×M | md #7–#9, #18 |
| RK5 | A run is marked `complete` but cannot replay | H×M | cv #5–#11 |
| RK6 | A resubmit rewrites a published cache version or the frontier | H×L | md #17; cv #18 |
| RK7 | Reproductions are counted twice, or recorded for a non-exact replay | M×M | rp #8, #9, #11 |
| RK8 | Today's callers break (cache grammar, submit payload, score DTO) | H×L | gw #1, #20; md #1, #2; cv #1, #2 |

## 3. Levels (test pyramid)

| PR | Unit | Integration | E2E |
|---|---|---|---|
| A1 scoreboard paper link, edit + log | md #4, #6, #13, #14 | md #1–#3, #5, #7–#12, #15–#18 | — |
| A2 SDK metadata | md #19–#22 | — | — |
| B1 gateway label, registry + replay controls | gw #1–#8, #12–#15 | gw #9–#11, #16–#21 | — |
| B2 engine Tavily (OME-1045) | the OME-1045 list | the OME-1045 list | — |
| B3 engine capture + replay | cv #1, #2, #4–#13; rp #2–#6, #23 | — | — |
| B4 scoreboard cache version + reproductions | cv #17; rp #14 | cv #16, #18; rp #7–#13 | — |
| B5 SDK capture + reproduce | cv #14, #15; rp #15–#21 | — | rp #22 |
| C1 public docs | — | — | — |

There is one E2E test for the whole epic: rp #22, submit then reproduce on the local stack. The
local stack runs an embedded gateway
(`[existing packages/screamingface/src/screamingface/_runtime/server.py:257]`), so the test needs no hosted service.

## 4. Universal properties

- **P1. One key path.** For any request and the current label, `cache_key_for(current, …)` equals
  `build_global_cache_key(…)` (gw #7). Use Hypothesis over the golden request generator.
- **P2. Label sensitivity.** Changing any one constant gives a new label (gw #5).
- **P3. Replay never writes.** For any old label, a replay request leads to no store write
  (gw #14, #16).
- **P4. Fill-only fields.** For any stored non-NULL cache version, no resubmit changes it (cv #18).

## 5. What this plan does not cover

- Load tests. The new hot-path work is O(1) for each call (gateway PRD §4).
- Hosted deploy order. B1 must be deployed before B3 is used for replay. Until then, K10 and the
  ack stop a replay safely, so a wrong order is a refusal, not a cost.
- Manual portal checks beyond the JS unit tests.
