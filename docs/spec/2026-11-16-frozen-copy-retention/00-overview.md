# Frozen copy retention — stop the unbounded growth of the pinned cache store

**Issue:** OME-1947 (`bug`, no parent epic; filed 2026-11-17) · **Status:** approved by the
owner on 2026-11-17, after review round 6 (its fixes were checked by the author only); the plan is next
**Date:** 2026-11-16
**Base:** `origin/main` at `e9db97cfb` (each `[existing …]` anchor is on this commit)

## 1. Summary

The production database of the AI Gateway grew to 47 GB. The table `frozen_copy_entries` holds
40.7 GB of it. A frozen copy (the SDK name is "pinned cache") is the full record of the model
answers of one captured run. Until now, nothing deleted a copy.

An audit of production on 2026-11-16 found three classes of copy:

| Class | Copies | Size (estimate) | Share |
|---|---|---|---|
| Sealed, and a leaderboard Score names it | 376 | 11.8 GB | 32% |
| Sealed, and no Score names it | 12 188 | 9.0 GB | 24% |
| Open, with no new entry for more than 24 hours | 327 | 14.9 GB | 40% |
| Open, recent | 19 | 1.4 GB | 4% |

The growth did not come from the new users. Of the 26 GB added from 2026-10-29, 22 GB came from
staff accounts, and the largest part was capture runs that did not complete.

This spec changes three things:

1. **Abandoned copies are deleted.** An open copy that gets no entry for 24 hours becomes
   `abandoned`. A background job in the gateway (the sweep) deletes its entries.
2. **Copies with no Score expire.** A sealed copy that no Score claims becomes `expired` 90 days
   after its clock starts. A copy that a Score claims is kept forever. The scoreboard claims the
   copy before it stores the Score. When it has a gateway URL, it stores a Score with a pinned
   cache only when the gateway confirms a sealed copy. At each start, the scoreboard also claims the copies of all
   stored Scores.
3. **The promise changes.** The public docs said "kept forever". They now state the rule. A
   replay of an expired copy gets a clear message. The SDK does not change.

The sweep and both rules are automatic. They have no switch, no date setting and no approval
step `[stated ans:Q22]` `[stated ans:Q23]`. The 90-day clock of the copies that exist starts
when the expiry rule is released; the release writes that time into the database
`[stated ans:Q24]`.

## 2. Subsystems and pull requests

| Subsystem | Change | PRs |
|---|---|---|
| `apps/aigateway` | Migrations 0018 and 0019; the sweep, its command and its periodic trigger; the claim route and its guard; the expiry rule; 410 for an expired copy; chart values; runbook in `DEPLOYMENT.md` | A1, A2, A3, B1, C1 |
| `apps/scoreboard` | Claim client; claim and refusals in the submit route; settings and chart; the claim pass at start and the command `claim_copies` | B2, B3 |
| `apps/screamingface-engine` | The message for an expired copy (same code) | C2 |
| `public-docs`, `CONTEXT.md`, E14 design record | The new rule in words | C3 |
| `packages/screamingface` | Nothing `[stated ans:Q8]` | — |
| `packages/url4` | Nothing | — |
| Infrastructure repo | Values for both services, NetworkPolicy peer | handoff, §7.3 |

**Stack A — abandoned copies (needs no other service)**
One pull request with one commit for each of A1, A2 and A3 (owner decision, 2026-11-17). Cause: the
owner's approval record for the changed migration test names one branch, and the pre-push
check compares each pushed branch with `main`, so stacked branches for A2 and A3 fail it.
- A1: migration 0018 (three columns, one index), the two new states, seal only an open copy.
  Tests CH-1, CH-2, S-9, S-28 of `prd/copy-sweep.md`.
- A2: the idle rule, the purge and the command; the three settings of stack A (idle time,
  purge budget, interval), because S-22 tests the limits of all three. Tests S-2, S-5, S-7, S-8, S-10 to S-13, S-15 to S-17, S-21, S-22, S-27, S-29, S-31,
  S-34, S-36 of `prd/copy-sweep.md`.
- A3: the periodic trigger (always on), the chart values for the three settings, the
  runbook. The runbook has the release checks and the advice of `test-plan.md` §5.4
  `[stated ans:Q21]`. Tests S-23 to S-25, S-32 of `prd/copy-sweep.md`.

**Stack B — claims (must be live in production before C1 is released)**
- B1: the gateway claim route and its guard. Tests K-1 to K-7 of `prd/score-claim.md`.
- B2: the scoreboard client, the submit route, settings, chart. Tests CH-1 to CH-3, K-8 to
  K-17, K-23, K-24, K-26, K-35 of `prd/score-claim.md`.
- B3: the claim pass at start and the command `claim_copies`. Tests K-18 to K-22, K-27 to K-34
  of `prd/score-claim.md`.

**Stack C — expiry (released after stack B is live in production)**
- C1: migration 0019 (the column `retention_from` and its stamp), the expiry rule in the
  sweep and its setting `AIGW_FROZEN_COPY_UNCLAIMED_TTL_SECONDS`, gateway 410 for an expired
  copy. Tests S-1, S-4, S-6, S-14, S-33, S-35, S-37 of `prd/copy-sweep.md` (S-6 before S-1),
  K-25 of `prd/score-claim.md`, and CH-1, R-1 to R-3 of `prd/expired-copy-replay.md`.
- C2: engine message. Tests CH-2, CH-3, R-4 to R-7 of `prd/expired-copy-replay.md`.
- C3: public docs, glossary, E14 rows Q33–Q36, model docstring. Checked in the review.

A1 is the base of all stacks. B1 depends on A1 only. C1 depends on A2 (the sweep) and on B1
(the claim store method that S-14 uses).

**Order rule.** C1 is released in production only after B2 and B3 run there, so that the
copies of the Scores that exist have their claim before the 90-day clock starts. No code
enforces this order `[stated ans:Q22]`. If the order is wrong, 90 days remain in which one
start of a scoreboard with a gateway URL claims the copies (`test-plan.md` X15).

Test ids that are not used: S-3, S-18, S-19, S-20, S-26, S-30 (`prd/copy-sweep.md` §7).

The detailed plan with file lists goes into `docs/plan/` (repo order: spec → plan → code).

## 3. Source tags

Each requirement carries one tag:

- `[stated prompt]` — the request of 2026-11-16: explain the growth of the production Postgres,
  find if it is "something like temp frozen copies not related to submissions", then "work in a
  spec to properly fix all of these".
- `[stated ans:Qn]` — the interview of §5.
- `[existing <path>:<line>]` — code or text on the base commit.
- `[implied]` — a necessary result of the lines above.
- `[proposed]` — an engineering detail that the owner did not decide. §6 lists the ones that
  remain.

## 4. Documents and reading order

1. `00-overview.md` — this file.
2. `erd.md` — the new columns, the two new states, the state table, the rules.
3. `prd/copy-sweep.md` — the background job and the command.
4. `prd/score-claim.md` — how a Score keeps its copy.
5. `prd/expired-copy-replay.md` — the answer for an expired copy, and the text changes.
6. `contracts.md` — each connection (K1–K10).
7. `test-plan.md` — rules, risk register, release checks.

Related specs: `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` (the
design of the frozen copy; this spec reverses its decision E14 Q15 and changes its invariant F2),
`docs/spec/2026-10-20-OME-1613-evaluate-pinned-cache.md` (the SDK surface for replay).

## 5. Interview ledger

### 5.1 Product decisions (rounds 1 and 2)

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | Which of the four problem areas must this spec cover? (frozen-copy lifecycle; storage visibility; request cache growth; side fixes) | "Frozen-copy lifecycle" only | Three areas not selected: §8 |
| Q2 | A sealed copy with no Score stays forever today (Q15 of E14; the docs say "kept forever"). What is the new rule? | "Expire after 90 days" | Recommended was 30 days. The option text included: copies linked to a Score stay forever; the docs promise changes; a submit after the period fails with a clear error. |
| Q3 | How do we remove the existing abandoned open copies (about 15 GB)? | "Sweep after dry run": ship the job; its first production run is a dry run with a report; the owner approves; then it deletes in small batches | See also §9.4. **Reversed by Q23** (round 5): the first run is automatic |
| Q4 | Copies linked to a Score grow about 0.6 GB each day. Where do they live in the long term? | "Postgres + alerts": keep them in Postgres; put the growth forecast in the spec; decide on a move later | The alert part is narrowed by Q6. The question used an early estimate; the measured rate is 0.75 GB each day (§9.2) |
| Q5 | After how much idle time does the sweep delete an open copy? | "24 hours" | Recommended was 48 hours |
| Q6 | How much visibility work goes into this spec? | "No visibility work": only the growth forecast in the spec text; no endpoint, no alert | Recommended was a stats endpoint and one alert |
| Q7 | For sealed copies that exist today: when does their 90-day clock start? | "Release date": each existing copy gets 90 days from the day the rule goes live | — |
| Q8 | How does a user learn that a pinned cache with no Score expires? | "Docs only": update the public docs and the error message; no SDK change | Recommended was docs and a new SDK field |

### 5.2 Engineering decisions (round 3, after two design reviews; Q20 and Q21 in round 4)

| Id | Question | Answer | Note |
|---|---|---|---|
| Q9 | A submit has a pinned cache, and the gateway does not answer the claim call. What does the scoreboard do? | "Fail with 503": the Score is not stored; the SDK makes 3 attempts | — |
| Q10 | A submit carries a pinned cache id that is not a usable copy (open, abandoned, or not known to the gateway). What does the scoreboard do? | "Refuse with 422": a Score can name only a sealed copy that the gateway confirms. Cost accepted: a run whose seal failed, and a local-runtime run with capture, cannot be submitted with no SDK change. | Recommended was "store as today" |
| Q11 | An operator deletes a Score. What happens to its claimed copy? | "Stays claimed": kept forever; no code path removes a claim | — |
| Q12 | When the sweep deletes the entries of a copy, what happens to the copy row? | "Keep the row" (about 100 MB each year of small rows) | — |
| Q13 | Does this spec also change the engine to close a copy at once? | "No engine change" | — |
| Q14 | How does the gateway decide that the caller of the claim route is allowed? | "Own allow list" | — |
| Q15 | How is the 90-day rule turned on? | "Date + switch": one setting starts the clock; a second setting lets the periodic job expire copies, and is set only after the owner approved the first list | **Reversed by Q22** (round 5): no switch and no date setting. Q24 gives the clock start |
| Q16 | Does each sweep run write one log line with its counts? | "Yes, one log line" (counts only) | — |
| Q17 | With no alerts, how does the system make sure that the expiry rule never deletes the copy of a stored Score, also when the claim at submit stops with no signal? | "Claim at submit only": no daily job, no table, no interlock. Cost accepted: if the claim path stops and nobody sees it, the copies of Scores stored in that time expire 90 days later. | Recommended was a daily job with an interlock. Result: `erd.md` §2.8. **Changed by Q25** (round 5): the scoreboard also claims the copies of all Scores at each start. Still no daily job, no table, no interlock |
| Q18 | Does the gateway refuse to start when the idle setting is below 18 hours? | "No minimum": the operator can set each value | Recommended was a minimum of 18 hours |
| Q19 | How do we close the window in which a copy of a Score with no claim can expire? | "Accept the window": no rule | Recommended was a runbook rule. **Narrowed by Q25** (round 5): a claim pass at the next start of the scoreboard repairs a missing claim. Until then, the copy has only the time that remains in its period (`erd.md` §2.8) |
| Q20 | A release check needs each copy of a Score to be sealed and claimed. A Score that was stored before the new scoreboard is live can name a copy that is open, abandoned or not known to the gateway. What does the operator do? | "Owner accepts a list": the check passes when each such Score is on a written list that the owner accepts. The Score stays on the board; its copy cannot be replayed. Nothing is deleted from the scoreboard. | Asked after review round 4. **Changed by Q22 and Q23** (round 5): no check blocks a release. The list is information for the owner; the Score stays, and nothing is deleted. `test-plan.md` §5.2 (5) |
| Q21 | With Q19 ("no rule"), does the advice to run `claim_copies` after an event that can remove claims stay in the spec? | "Keep as a recommendation": it stays as advice for the operator, not a rule, and the runbook of A3 repeats it | Asked after review round 4. **Stays** after round 5, with the new repair text: start the scoreboard again, or run `claim_copies`. `test-plan.md` §5.4 |

Not asked: one earlier item (an open copy that a Score names is swept). After stack B is live,
no new Score can name an open copy (Q10), and no Score named one on 2026-11-16. The old
scoreboard can still store such a Score before stack B is live. The idle rule then sweeps that
copy, and the claim pass reports the Score in its list (Q20).

### 5.3 Round 5 (2026-11-17, after the owner read the overview of the solution)

| Id | Question | Answer | Note |
|---|---|---|---|
| Q22 | Does the sweep have switches? | "No need for the switches, consider it the only behavior": the sweep and both rules are always active | Reverses Q15. Removes the settings `AIGW_FROZEN_COPY_SWEEP_ENABLED`, `AIGW_FROZEN_COPY_UNCLAIMED_EXPIRY_ENABLED` and `AIGW_FROZEN_COPY_UNCLAIMED_EXPIRY_FROM` |
| Q23 | Is the first run approved by hand? | "No need [for] the first run either, it must be automatic" | Reverses Q3. Removes the approved list: `--execute`, `--candidates`, `--expect-sha256`, the digest, exit status 3 of the sweep command |
| Q24 | With no date setting, when does the 90-day clock start for the sealed copies that exist? | "Release stamps it": the database migration marks each existing sealed copy with the time of the release. No setting, so no date can be set wrong | Keeps Q7. `erd.md` §2.1, §5 |
| Q25 | With the 90-day rule automatic, how do the Scores that exist get their claim? | "Scoreboard claims at start": each time the scoreboard starts, it claims the copies of all stored Scores in the background | Changes Q17, narrows Q19. `prd/score-claim.md` C18 to C23 |

The answers Q2, Q5, Q7 and Q8 go into the E14 design record as rows Q33–Q36
(`prd/expired-copy-replay.md` §4.3).

## 6. What stays `[proposed]`

The owner decided the items of §5. These implementation details stay `[proposed]`. None of them
changes what a user sees.

| Item | Where |
|---|---|
| No column for the time of the last entry; the newest entry gives the idle time | `erd.md` §2.1 |
| One index on `(status, purged_at)` | `erd.md` §2.6 |
| The sweep has no global lock; each mark is under the row lock; chunks use `SKIP LOCKED`; `purged_at` has its own check | `prd/copy-sweep.md` S18; `contracts.md` K8 |
| Chunk of 500 entries, pause of 200 ms, lock timeout of 2 s, budget of 100 000 entries, stop when chunks are slow | `prd/copy-sweep.md` §4.2, S24 |
| The command: dry run by default; `--run` for one full pass by hand | `contracts.md` K6 |
| The column `retention_from` for the clock start, and two migrations (0018 in A1, 0019 in C1) | `erd.md` §2.1, §5 |
| The claim pass at start tries again every 10 minutes until one pass completes | `prd/score-claim.md` C20 |
| One WARNING record (not one for each Score) for the Scores whose copy is not sealed | `prd/score-claim.md` C21 |
| A 404 with no code from the gateway is "unavailable" (503), not "unknown copy" (422) | `prd/score-claim.md` C7 |
| The claim guard accepts each caller in `disabled` mode (local development) | `prd/score-claim.md` C13 |
| One WARNING record for each Score that is stored with no claim because the scoreboard has no gateway URL | `prd/score-claim.md` C9 |
| The text of the error messages | `contracts.md` K3, K5; `prd/expired-copy-replay.md` R1 |

## 7. Release order

### 7.1 Steps

No step needs an approval. `[stated ans:Q22]` `[stated ans:Q23]`

| Step | Action | Check (not a gate) |
|---|---|---|
| 1 | Release stack A. The sweep starts by itself. The first run marks the idle open copies, and each hourly run purges up to 100 000 entries. | `test-plan.md` §5.1 |
| 2 | Release B1. Set the claim list and the NetworkPolicy peer. | — |
| 3 | Test the claim route from a scoreboard pod (a random UUID must give 404 `frozen_copy_not_found`). Release B2 and B3 with the gateway URL and actor. At start, each scoreboard pod claims the copies of all Scores. | `test-plan.md` §5.2 (1, 2) |
| 4 | Verify the claims: the summary record of the pass, and the SQL check that each copy of a Score is `sealed` and claimed. Give the list of exceptions to the owner for information `[stated ans:Q20]`. | `test-plan.md` §5.2 (3 to 6) |
| 5 | Release C1 (migration 0019 stamps the clock) and C2. Publish C3 with the date of the production release of C1. | `test-plan.md` §5.3 (1 to 3) |
| 6 | 90 days after step 5, the first copies expire with no further action. | The run log record shows the count; `test-plan.md` §5.3 (4) |

Step 1 needs no other step. It can be released as soon as stack A is merged.

Step 5 comes after step 4. This is the order rule of §2. No code enforces it.

### 7.2 Compatibility during the release

- An old engine with a new gateway: safe (`prd/expired-copy-replay.md` R6).
- A new scoreboard with no gateway URL: it works as today, and makes no claim
  (`prd/score-claim.md` C9, C22).
- A new gateway with an old scoreboard: no copy is claimed. Before C1 this has no effect,
  because the gateway has no expiry rule. After C1, 90 days remain until the first expiry
  (`test-plan.md` X15).
- After step 3, the user-visible change of Q10 is live: a submit with a pinned cache that is
  not a sealed copy gets 422.
- A rollback of the gateway image to one with no claim route: each submit that carries a copy
  gets 503 until the new image is back (`prd/score-claim.md` C7). The old image has no sweep.
- A rollback of the scoreboard, or a restore of the gateway database: `erd.md` §2.8 and
  `test-plan.md` §5.4.
- A local or development gateway also runs the sweep and both rules (`prd/copy-sweep.md`
  §4.1).

### 7.3 Handoff to the infrastructure repo

- Gateway values: the four sweep settings (`prd/copy-sweep.md` §4.1; the defaults are
  correct for production) and `AIGW_FROZEN_COPY_CLAIM_EMAILS`. Three settings come with stack
  A, and `AIGW_FROZEN_COPY_UNCLAIMED_TTL_SECONDS` comes with C1. No switch and no date.
  `[stated ans:Q22]`
- Gateway NetworkPolicy: one `allowFrom` element for the scoreboard pods (`contracts.md` K4).
- Gateway trusted networks: confirm that the address range of the scoreboard pods is in
  `AIGW_ALLOWED_NETWORKS`.
- Scoreboard values: `SCOREBOARD_GATEWAY_URL` (the gateway Service address across namespaces),
  `SCOREBOARD_GATEWAY_ACTOR` (an address that cannot log in through Cloudflare Access),
  `SCOREBOARD_GATEWAY_TIMEOUT_S`.
- Engine: confirm that the run deadline in production (`URL4_CLOUD_JOB_DEADLINE_S`) is 16 hours
  or less. The idle setting must stay above it; no code checks this `[stated ans:Q18]`.
- Database server: confirm the provisioned storage size and the auto-grow setting against the
  forecast of §9. The audit identity could not read them.

## 8. Out of scope

**Not selected in Q1.** Each item needs its own ticket if the owner wants it:

- Request cache growth: `request_cache_entries` is 6.3 GB, grows about 0.3 GB each day, and has
  no expiry in use and no eviction.
- Storage visibility: size metrics, a stats endpoint, alerts. `[stated ans:Q6]`
- Side findings of the audit: the selector of the `url4-cloud` Deployment also matches the
  Garage pod; the runner pods cannot export traces to the collector (about 21 000 errors each
  day); `docs/observability-state-of-play.md` is out of date on `traceparent`.

**Decided as out of scope in rounds 3 and 5:**

- A job on a schedule that claims the copies again, a table for it, and a rule that stops the
  expiry when claims are missing. `[stated ans:Q17]` (The claim pass at each start of the
  scoreboard is in scope, Q25.)
- A switch for the sweep or for a rule, a date setting, and an approval step before a delete.
  `[stated ans:Q22]` `[stated ans:Q23]`
- A release of the claim when a Score is deleted. `[stated ans:Q11]`
- Deletion of the small rows of swept copies. `[stated ans:Q12]`
- Cleanup in the engine at cancel. `[stated ans:Q13]`
- A lower limit for the idle setting. `[stated ans:Q18]`

**Future considerations:**

- A move of sealed copies to object storage, or compression in Postgres. `[stated ans:Q4]`
- A quota for each account.
- A field in the SDK result that shows the expiry date. `[stated ans:Q8]`
- A way to submit a run whose seal failed, or a local-runtime run with capture (it needs an SDK
  change, or an upload of the local copy; see Q14 of the E14 design).

## 9. Evidence and forecast

### 9.1 Audit of 2026-11-16 (production, read-only)

- Database sizes: `aigateway` 47 GB; `scoreboard`, `engine`, `reportintake` about 0.01 GB each.
- `frozen_copy_entries`: 40.7 GB (38 GB TOAST), 2.24 million entries. On 2026-10-29 it was
  11.66 GB and 554 000 entries.
- `frozen_copies`: 12 908 rows (1 040 on 2026-10-29). One account made 11 219 of them from
  2026-11-09, with 1 to 10 entries each; they hold 0.14 GB.
- The gateway logs of the last 18 hours showed 1 925 copies opened and 1 915 sealed. The copies
  that stay open come from runs that end with a cancel, a kill or a second delivery.
- The sizes for each class are estimates from a 2% sample of the entries. The sum of the
  estimates is 37 GB; the table is 40.7 GB. Multiply an estimate by 1.1 for the size on disk.

### 9.2 Rates (week of 2026-11-09 to 2026-11-15, on disk)

| Class | Each day |
|---|---|
| Open, later abandoned | 1.4 GB |
| Sealed, no Score | 0.55 GB |
| Claimed by a Score | 0.75 GB |

This was the week with the highest use until now. Read the forecast as an upper estimate.

### 9.3 Forecast with the rules of this spec

- **Abandoned copies:** about 16 GB of the table is, or becomes, free space inside the table
  (§9.4). The size on disk does not go down; new entries use the free space.
- **From then until the first expiry:** the used data grows about 1.3 GB each day (claimed
  copies and unclaimed sealed copies). No sealed copy can expire before the release of C1
  + 90 days.
- **Example:** if C1 is released on 2026-12-01, the first expiry is on 2027-03-01. At the
  rate of §9.2, the used data on that day is about 160 GB. On that day the copies sealed before
  the release expire together (about 18 GB), with no approval step.
- **After that:** unclaimed sealed copies stay at about 50 GB (90 days × 0.55 GB). Claimed
  copies grow about 0.75 GB each day, about 270 GB each year, with no limit. `[stated ans:Q4]`
- **What this means:** the removal of abandoned copies gives the gain now. The 90-day rule puts
  a limit on one class but does not reduce the disk in the next months. The class with no limit
  is the claimed copies. A decision on object storage or a shorter period can become necessary
  when the provisioned storage is known (§7.3).

### 9.4 Manual cleanup of 2026-11-16

On 2026-11-16 the owner ordered a manual cleanup of production, before this spec was approved,
because the access window was short.

- **Scope:** copies with status `open`, that no Score and no reproduction record names, with no
  entry in the last 24 hours. 327 copies with 1 071 664 entries were in scope. 19 open copies
  with recent entries were kept.
- **Method:** direct SQL in the gateway database, 500 entries for each statement, then the copy
  row. No tombstone row was kept, because the code of this spec was not released.
- **First round (16:34 to 17:30 UTC):** 200 copies and 642 802 entries deleted. No copy was
  skipped. The 376 copies that Scores name stayed present and `sealed`. The gateway pod did not
  start again.
- **Why it stopped:** the time of one statement went from about 1 second to 10–15 seconds
  while the automatic vacuum of Postgres worked on the table. 127 copies with 428 862 entries
  remained.
- **Second round:** no delete ran. The automatic vacuum was still in progress when the access
  window ended at about 17:33 UTC. No copy was left with a part of its entries.
- **Final state:** 200 of 327 copies deleted (642 802 of 1 071 664 entries, about 8 GB of about
  16 GB by the audit's estimates). 127 copies with 428 862 entries (about 8 GB) are still in
  the database, with status `open` and no Score. They can be deleted in a later access window
  with the same scripts, or by the sweep of this spec.
- **Records:** `~/sf-backups/pg-growth-2026-11-16/` on the operator's machine (the list of the
  copies in scope with its SHA-256, the ids that were deleted, the scripts, the numbers).

Because of this cleanup, the first automatic run after the release of stack A (§7.1, step 1)
marks only the copies that the manual cleanup did not delete, and those that were abandoned
after 2026-11-16.

## 10. Assumptions

- No run lives longer than the engine deadline of 16 hours
  (`[existing apps/screamingface-engine/src/screamingface_engine/config.py:222]`) plus 90
  seconds, so a copy with no entry for 24 hours belongs to a run that ended. An entry is stored
  only when a call ends, so the time of one call is not the limit; the deadline is.
- The gateway runs one replica in production. The design also works with more
  (`contracts.md` K7).
- Stack B is live in production before C1 is released.
- After a restore of the gateway database, the operator runs `claim_copies` at once
  (`test-plan.md` §5.4). The design does not protect a copy that lost its claim and is past
  its period (`erd.md` §2.8).
- Backups of the database server keep deleted entries until the backup retention ends.
- The expert skills that the planning guideline names (`swe-expert`, `system-design`,
  `qa-tester`) were not available in this session. The gap analysis used the checklist of the
  guideline directly.

## 11. Review record

**Round 1.** An independent design review of the first draft found two blockers and eight major
problems. The fixes that are in this version:

| Finding | Fix |
|---|---|
| The first expiry, or a wrong date, deletes with no approval | A separate switch for the expiry rule (Q15); release step 9 |
| The dry-run and execute steps did not work after the first mark | Execute from the approved list; a copy that changed after the dry run is skipped; purge is a separate mode (`contracts.md` K6) |
| A column for the time of the last entry is wrong after a rollback | No such column; the newest entry gives the time (`erd.md` §2.1) |
| A global lock could stay held and stop all runs | No global lock; `SKIP LOCKED` (`prd/copy-sweep.md` S18) |
| A seal by a caller that is not the owner could show the state of a copy | The owner filter stays first (`erd.md` §2.3) |
| A 404 from a wrong gateway URL was read as "unknown copy" | Only a 404 with the code `frozen_copy_not_found` is read that way (`prd/score-claim.md` C7) |

**Round 2.** A second review found one blocker and four major problems. The fixes that are in
this version:

| Finding | Fix |
|---|---|
| A release check passed when the command did not read some Scores | A check of the Score ids against the gateway, which does not depend on the command (`test-plan.md` §5.3, 5 and 6) |
| Two purges at the same time could mark a copy as purged while entries remained | `purged_at` is set by one statement that checks that no entry remains (`contracts.md` K8) |
| Two race tests could pass with no check under the lock | The tests assert the cause of the skip (`prd/copy-sweep.md` §7) |
| A wrong date was found only by chance | A dry run with no cutoff before the switch is set (`test-plan.md` §5.4, 3) |

**Round 3 (owner decisions).** The owner decided the items Q9 to Q19 on 2026-11-16. Two decisions take a
different way from the reviews, and the owner accepted the cost:

- **Q17, claim at submit only.** Review 1 named this as a blocker: if the claim path stops with
  no signal, the copies of Scores stored in that time expire 90 days later. Both reviews
  proposed a daily job with an interlock. The owner selected the simpler design. What remains
  as protection: the submit fails closed (Q9), a Score is stored only with a confirmed sealed
  copy (Q10), the expiry switch is set only after a check of each Score id (Q15,
  `test-plan.md` §5.4), and one WARNING record for each Score stored with no claim. The cases
  that these do not cover are in `erd.md` §2.8.
- **Q18, no minimum for the idle setting.** Review 2 confirmed that the default of 24 hours is
  safe, and review 1 asked for a lower limit of 18 hours.

**Round 4 (2026-11-17).** A third independent review read the text after round 3. It found no
blocker, three major problems and twelve minor ones. It found no remainder of the removed
design (daily job, table, interlock, idle minimum), and 70 of 72 line anchors correct. The
fixes that are in this version:

| Finding | Fix |
|---|---|
| The text did not say that a dry run ignores the two switches; a build with the switch check in the rule code makes the release checks of the expiry rule pass with an empty list | Stated in `contracts.md` K6 and `prd/copy-sweep.md` S7; test S-30 |
| The release checks needed exit status 0, but a Score stored before step 6 can name a copy that is not sealed | Owner decision Q20: a list that the owner accepts (`test-plan.md` §5.3) |
| The idle mark did not check `status = open` under the lock, so a seal that raced the mark could end as `abandoned` | Check added in `contracts.md` K8; scenario S25; Postgres test S-31 |
| Minor: two values for the pause between chunks; a race test in a pull request before the code that it needs; two wrong anchors; I1 and I6 too broad; five behaviors with no test; a copy with no entry and the purge order | 200 ms in each place; S-14 imitates the claim; anchors corrected; new text for I1 and F1; tests S-32 and K-24 to K-27; `purged_at` at the mark for a copy with no entry |
| §5.5 against Q19 | Owner decision Q21: the advice stays as a recommendation |

The fixes of round 4 were checked by the author only.

**Round 5 (owner decisions, 2026-11-17).** The owner read the overview of the solution and
decided Q22 to Q25 (§5.3). The sweep and both rules are now the only behavior.

- **Q22 and Q23 remove the fix for the round-1 blocker** "the first expiry, or a wrong date,
  deletes with no approval". The two parts of that finding now have these answers:
  - *A wrong date* can no longer occur. No setting holds a date; the release writes the clock
    start into the database (Q24).
  - *The first expiry has no approval.* This is the owner's decision. The guards that remain:
    the scoreboard claims a copy before it stores a Score (Q9, Q10); the scoreboard claims
    the copies of all stored Scores at each start (Q25); stack B is released before C1 (the
    order rule of §2, not enforced by code); 90 days pass between the release of C1 and the
    first expiry; each run writes one log record with its counts (Q16).
- **Q25 changes Q17.** For the risk that review 1 named for Q17 (a claim path that stops with
  no signal), a claim pass at the next start of the scoreboard is now the repair. Until that
  pass, a copy with no claim has only the time that remains in its period (`erd.md` §2.8).
- **Earlier fixes that round 5 replaced.** The rows of rounds 1, 2 and 4 above describe the
  text of that time, and their section numbers are those of that time.

| Earlier fix | State after round 5 |
|---|---|
| Round 1: a separate switch for the expiry rule; release step 9 | Removed (Q22) |
| Round 1: execute from the approved list; purge as a separate mode | Removed (Q23). The command has a dry run and `--run` |
| Round 2: a check of the Score ids against the gateway | Stays as a check, not as a gate (`test-plan.md` §5.2, 4) |
| Round 2: a dry run with no cutoff before the switch is set | Removed. The clock start cannot be wrong (Q24) |
| Round 4: the dry run ignores the two switches; test S-30 | Removed with the switches |
| Round 4: Q20, a list that the owner accepts | The list is information only |
| Round 4: S-14 imitates the claim | S-14 is now in C1 and uses the claim store method of B1 |

**Round 6 (2026-11-17).** A fourth independent review read the text after round 5. It found
no blocker, three major problems and nine minor ones. It found no remainder of the removed
design (switches, date setting, approved list), about 80 line anchors correct, and the plan
of pull requests correct. The fixes that are in this version:

| Finding | Fix |
|---|---|
| The window of a missing claim was stated wrongly ("the scoreboard does not start for 90 days"). The clock of a copy does not start again when a claim is lost, and after a restore of the gateway database the sweep usually runs before a claim pass | The window is "the time that remains in the period of the copy, which can be zero" (`erd.md` §2.8); risk X2 rated again; the operator runs `claim_copies` at once after a restore (`test-plan.md` §5.4). No new mechanism: this is the result of Q19 and Q22 |
| The time format of the stamp of migration 0019 was not defined; `CURRENT_TIMESTAMP` gives text with no zone on SQLite | The stamp is a `RunPython` step that passes one timezone-aware UTC time as a parameter; test S-33 checks the value through the model (`erd.md` §5) |
| Two wrong statements: a restore to a time before 0019 does not run the migration again by itself; an old scoreboard image writes no WARNING record | Migrations run only in the Helm Job, and the migrate Job is the first step after a restore (`erd.md` §5.1, `test-plan.md` §5.4); `erd.md` §2.8 case 1 states both facts |
| Minor: the column drop of a downgrade on SQLite; the test seam of the trigger; two release checks (count, uuid cast); tests that could not fail where they were; the pull request of the period setting; the shutdown order of the scoreboard; two wording gaps in §1 and §2; a repeat with the same key for an old Score | `RunSQL` drop in both downgrades; `sleep` and `now` bound in the constructor and `app.state.frozen_copy_sweep_trigger`; count before and after, `::uuid[]`; K-25 moved to C1, S-6 before S-1, K-26 narrowed, new test S-36; the setting and S-37 in C1; cancel, then client, then database, with test K-34; text corrected; C12 extended with test K-35 and risk X6 |

The fixes of round 6 were checked by the author only.
