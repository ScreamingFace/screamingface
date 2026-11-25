# Test plan — frozen copy retention

**Base:** `origin/main` at `f683cd2e6` (before stack A). Paths are relative to the repo root.
The test cases are in the TDD tables of the three PRDs. This file gives the rules that apply to
all of them, the risk register, and the checks for the release to production.

## 1. Ground rules

1. **RED first.** Write the test, run it, and see it fail on the assertion for the behavior that
   is not there. A test that fails on an import error or a bad fixture is not RED.
2. **GREEN with the smallest change.** Do not write code for a later test.
3. **REFACTOR only when all tests pass.**
4. **One behavior for each test.** The test name states the behavior.
5. **Characterization tests** (`CH-n`, marked CHAR) pin the behavior of today. They pass before
   the change, and they must pass after it.
6. **No test deletes or weakens an existing test** without the approval record that the repo
   needs for a test change (`.claude/test-change-approvals`). C1 changes two assertions of stack
   A tests with that record `[stated ans:Q27]` (`prd/copy-sweep.md` §7).
7. **No test calls a network service.** The scoreboard tests use a fake claim client or an
   `httpx` mock transport. No test calls a model provider.
8. **A race test uses a fixed order** (two connections; A holds the lock; the test starts B;
   the test lets A commit). See `prd/copy-sweep.md` §7.

## 2. Levels

| Level | Use | Where |
|---|---|---|
| Unit | Rules of the sweep, state changes, settings, mappings, command arguments | SQLite, `apps/aigateway/tests/unit`, `apps/scoreboard/tests/unit`, `apps/screamingface-engine/tests/unit` |
| Integration, in process | The submit route with a fake claim client; the claim command; the claim pass at start | `apps/scoreboard/tests` with the `client` fixture `[existing apps/scoreboard/tests/conftest.py:32-40]` |
| Integration, Postgres | Row locks, lock timeout, `SKIP LOCKED`, the three races | `apps/aigateway/tests/integration`, marker `needs_postgres` `[existing .github/workflows/aigateway-tests.yml:91]` |
| End to end | None in the automated suite. The release checks of §5 take this place. | — |

The lock tests must run on Postgres. SQLite ignores `select_for_update`
`[existing apps/aigateway/src/aigateway/core/frozen_copy/store.py:5-7]`, so a unit test cannot
prove S10, S12, S13, S18 or S25 of `prd/copy-sweep.md`.

## 3. Risk register

Test ids: `S-n` = `prd/copy-sweep.md`, `K-n` = `prd/score-claim.md`,
`R-n` = `prd/expired-copy-replay.md`.

| # | Risk | Impact | Likelihood | Tests and checks that guard it |
|---|---|---|---|---|
| X1 | The sweep deletes the entries of a copy that a Score uses | High: a published Score can no longer be reproduced; no repair | Low | S-1, S-14, K-1, K-2, K-12, K-18, K-28; §5.2 |
| X2 | A Score has no claim, with no signal (a restore of the gateway database; no gateway URL; an old scoreboard image), and its copy expires | High: no repair after the sweep deleted the entries | Low to medium. The copy has only the time that remains in its period, which can be zero. After a restore of the gateway database, the sweep runs 1 to 5 minutes after the gateway start, usually before a claim pass | K-16, K-28, K-30; §5.4 (run `claim_copies` at once after a restore). This is the result of `[stated ans:Q19]` and `[stated ans:Q22]`; no mechanism is added |
| X3 | The sweep abandons a copy of a run that is still in progress, or a copy that the run sealed while the mark waited | High: the run loses its capture | Low with the default; high if the idle setting is set below the engine deadline `[stated ans:Q18]` | S-2, S-13, S-31; the query of §5.1 |
| X4 | The expiry rule deletes copies with no approval of a list | High | Certain: this is the owner's decision `[stated ans:Q22]` `[stated ans:Q23]` | What remains as protection: the claim before the store (K-12), the claim pass at each start (K-28), 90 days between the release of C1 and the first expiry, a clock that no person can set wrong (S-4, S-33), the run log record (S-25); §5.3 |
| X5 | (not used: the approved list does not exist `[stated ans:Q23]`) | — | — | — |
| X6 | A submit that is accepted today is refused after the change | Medium: the user must run again | Certain for two inputs | Accepted by the owner `[stated ans:Q10]`: a run whose seal failed, and a run on the local runtime with capture, get 422 (K-10). Also a repeat that fills the copy field with a copy that is not sealed (K-24), and a repeat with the same key for a Score that was stored before B2 and whose copy is not sealed (K-35). Not changed: a submit with no copy (K-13), and a scoreboard with no gateway URL (CH-3 of the claim PRD). |
| X7 | The claim route lets a caller that is not the scoreboard keep copies | Medium | Low | K-5, K-6, K-7 |
| X8 | The purge slows live captures | Medium | Medium (seen on 2026-11-16) | S-11, S-15, S-16, S-29; §5.1 (3) |
| X9 | A failed purge leaves a copy that a reader sees as usable, or a copy marked as purged that still has entries | Medium | Low | S-7, S-8, S-16 |
| X10 | The released SDK reads a new error code wrongly | Medium | Medium if the code changes | R-4, R-7, CH-3 (replay) |
| X11 | An older engine in production fails on the 410 | Medium | Medium | CH-3 (replay), R-1 |
| X12 | The dry-run document or a log record leaks account names | Low | Medium | S-25, K-23, K-31 |
| X13 | The sweep stops with no signal (for example after each start of the pod) | Medium: storage grows again | Low | S-23, S-24; the run log record; §5.1 |
| X14 | A Score that was stored before the new scoreboard is live names a copy that is open, abandoned or not known to the gateway | Low: that Score cannot be reproduced, as today | Low (none of 376 on 2026-11-16) | K-20, K-31; §5.2. The list is information for the owner; the Score stays `[stated ans:Q20]` |
| X15 | The scoreboard is not live with a gateway URL in the 90 days after the release of C1, so no copy of a Score that exists is claimed, and those copies expire | High: no repair | Low | The order of §7.1 of `00-overview.md` (stack B before C1); the merge rule of `00-overview.md` §2 (C1 is not merged until steps 3 and 4 of §7.1 are done in production, because a merge to `main` goes out with the next gateway release); K-28; §5.2 (3, 4) before C1. No code enforces the order `[stated ans:Q22]` |

## 4. Gates

Run the gates of each stack that a pull request touches, as `.claude/sdlc.local.md` lists them.
For `apps/aigateway`: `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`,
`uv run python scripts/check_no_enterprise.py`, `uv run pytest --cov=aigateway --cov-fail-under=80 -q`.
For `apps/scoreboard` and `apps/screamingface-engine`: the gates in the same file.

The chart checks of the scoreboard are not in those gates. The scoreboard tests have no Helm
test and no YAML library, and this spec adds none. The checks go into
`.github/scripts/verify_chart_wiring.py`, which the workflow `charts.yml` runs. Before a push
of B2, run it by hand from the repo root: `python3 .github/scripts/verify_chart_wiring.py` (it
needs `helm` and PyYAML).

The Postgres lane is not in that file. It runs in CI only
`[existing .github/workflows/aigateway-tests.yml:91]`. For stack A, for B1 and for C1, run it locally
before the push: `AIGW_TEST_PG=1 uv run pytest -m needs_postgres` (the lane starts a Postgres
container; it is skipped when `AIGW_TEST_PG` is not `1`).

## 5. Release checks in production

These checks are manual and read-only. No check is a gate with an approval: the sweep and both
rules run by themselves `[stated ans:Q22]` `[stated ans:Q23]`. The checks tell the operator
that a release did what this spec says.

### 5.1 Stack A (abandoned copies)

Before the release, if the operator wants to see what the first run will mark, this query gives
the open copies that are **not** idle (a copy that got an entry in the last 24 hours, or a copy
with no entry that was made in the last 24 hours). Each other open copy is marked by the first
run. If `AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS` is not the default, use its value in place of 24
hours. No step depends on this query.

```sql
SELECT c.id FROM frozen_copies c
WHERE c.status = 'open'
  AND (EXISTS (SELECT 1 FROM frozen_copy_entries e
               WHERE e.frozen_copy_id = c.id AND e.created_at > now() - interval '24 hours')
       OR (c.entry_seq = 0 AND c.created_at > now() - interval '24 hours'));
```

After the release:

1. Migration 0018 is applied.
2. The first run log record comes 1 to 5 minutes after the start of the pod. It shows the
   number of copies marked `abandoned`. After that, one record comes for each hour.
3. Each run purges up to 100 000 entries. To go faster, run
   `python -m aigateway.frozen_copy_sweep --run --max-entries <n>` by hand in a period of low
   load. Watch the latency of `POST /v1/chat/completions` in the gateway traces, and stop the
   command (Ctrl-C) if the p95 grows by more than 2 times; a later run continues.
4. When the purge is complete:
   ```sql
   SELECT status, count(*) AS copies,
          count(*) FILTER (WHERE swept_at IS NOT NULL AND purged_at IS NULL) AS not_purged
   FROM frozen_copies GROUP BY 1;
   ```
   Expected: `not_purged = 0` for each status, apart from copies that the last run marked.
5. The size of `frozen_copy_entries` on disk does not go down (`prd/copy-sweep.md` §4.3). The
   proof of success is that the size stays flat for some weeks while new copies arrive.

### 5.2 Stack B (claims)

1. Before the scoreboard gets its gateway URL: from a scoreboard pod, send a claim for a random
   UUID to that URL with the actor header. The answer must be 404 with
   `detail.code = frozen_copy_not_found`. This proves the URL, the NetworkPolicy and the claim
   list.
2. The release of the scoreboard (B2, B3) is complete on all pods.
3. The log of each scoreboard pod has the INFO record of a complete claim pass
   (`prd/score-claim.md` C21). Run this count in the scoreboard database two times: before the
   scoreboard starts with the gateway URL, and after the pass ends.
   ```sql
   SELECT count(*) FROM scores WHERE frozen_copy_id IS NOT NULL;
   ```
   The number of Scores in the record must be between the two counts (new submits change the
   count while the pass runs).
   A WARNING record that says the gateway did not answer means that the pass waits for its
   next attempt (C20): find the cause.
4. No copy of a Score is without a claim. Export the ids from the scoreboard database
   (`SELECT frozen_copy_id FROM scores WHERE frozen_copy_id IS NOT NULL`), and run this in the
   gateway database with that list. The scoreboard column is text (`varchar(36)`) and the
   gateway column is a uuid, so the list needs a cast:
   ```sql
   SELECT id, status FROM frozen_copies
   WHERE id = ANY(:ids::uuid[]) AND NOT (status = 'sealed' AND claimed_at IS NOT NULL);
   ```
   This check does not depend on the pass, so it also finds a Score that the pass did not
   read. (A copy that the gateway does not know gives no row here; the WARNING record of the
   pass names it as `not_found`.)
5. A row in check 4, or a WARNING record with a list of Scores (C21), means that a stored Score
   names a copy that is not sealed. Such a Score was stored before this release. Give the list
   to the owner for information `[stated ans:Q20]`. The Score stays on the board, its copy
   cannot be replayed, and nothing is deleted. No release step waits for an answer.
6. A submit of a test run with `capture=True` to a test board gives a Score, and its copy has
   `claimed_at` set.

Do the checks 3 and 4 before the merge of C1, and thus before its release. These are the order
rule and the merge rule of `00-overview.md` §2 and §7.1. No code enforces them.

### 5.3 Stack C (expiry)

1. Migration 0019 is applied. Each copy that was `sealed` at that time has the same
   `retention_from`:
   ```sql
   SELECT retention_from, count(*) FROM frozen_copies
   WHERE status IN ('sealed', 'expired') GROUP BY 1 ORDER BY 1;
   ```
   Expected: one value that is the time of the release, and `NULL` for the copies sealed after
   it.
2. The public docs with the new rule are published: C3 is merged after C1 is merged. The docs
   name no date `[stated ans:Q32]` (`prd/expired-copy-replay.md` R9).
3. For information: `python -m aigateway.frozen_copy_sweep --cutoff <that time + 90 days>`
   shows the copies that expire first. No person must approve this document. The numbers must
   be near the forecast of `00-overview.md` §9.3. If a copy of a Score is in the candidates,
   its claim is missing: do the checks of §5.2 again.
4. 90 days after the release, the run log record shows the number of copies marked `expired`.

### 5.4 After an event that can remove claims

This section is advice for the operator, not a rule that the code enforces
`[stated ans:Q21]`. The runbook of A3 repeats it. A claim that is missing is made again by a
claim pass: at the next start of the scoreboard `[stated ans:Q25]`, or by
`python -m scoreboard.claim_copies`. Until the pass, a copy with no claim has only the time
that remains in its period, which can be zero (`erd.md` §2.8). No mechanism stops the sweep
in that time `[stated ans:Q19]` `[stated ans:Q22]`.

**After a restore of the gateway database** (the case with the least time):

1. Run the migrate Job of the gateway chart, if the backup is older than a migration of this
   spec. The gateway does not migrate at start; until the Job runs, the queries of the new
   code on `frozen_copies` fail (`erd.md` §5.1).
2. When the gateway is up, run `python -m scoreboard.claim_copies` at once. The first run of
   the sweep is not earlier than 60 seconds after the start of the gateway. Do not wait for
   the next start of the scoreboard: it does not start again by itself.
3. Do the checks 3 and 4 of §5.2. A copy of a Score with the status `expired` lost its entries
   before the claim; give the list to the owner.

**After each of these events**, start the scoreboard again or run `claim_copies`, and do the
checks 3 and 4 of §5.2: a time in which the scoreboard ran with no gateway URL (the new image
writes one WARNING for each Score stored in that time; an old image writes nothing); a rollback
of the scoreboard to an image with no claim; a downgrade of migration 0018 (this case is safe,
because the second apply of 0019 starts each clock again).

## 6. What is not tested, and why

- **The size on disk.** No automated test measures it. See §5.1.
- **The engine's kill paths** (cancel, deadline, memory, drain). This spec does not change the
  engine's capture code. The sweep tests cover the result of each path: an `open` copy with no
  new entry.
- **The SDK.** It does not change. `[stated ans:Q8]` The tests R-4 and R-7 pin the code string
  that the released SDK reads.
- **The text of the docs.** The changes of `prd/expired-copy-replay.md` R2 to R4 are checked in
  the review, against the text in that PRD.
