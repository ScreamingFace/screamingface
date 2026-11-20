---
ticket: OME-1958
stack: screamingface
status: done
started: 2026-11-20
finished: 2026-11-20
---

# Regrade environments — select both services before a dev replay

## Intent

Continue OME-1958 after #1926 merged. The batch accepts a Scoreboard override but leaves the
Engine at its production default. Make the dev acceptance command choose both endpoints.
Production deployment and the actual batch remain separate owner rollout steps.

## Planned changes

- `packages/screamingface/scripts/regrade_batch.py`: add `--engine-url`, pass it to Client,
  and require both service overrides together when `--apply` overrides either one.
- Add CLI regression tests without modifying prior tests. Update the script's operator example.
- Correct `bbh` and `medmcqa` transition keys and the test that repeated the prefix error.
  Owner explicitly approved this existing-test correction on 2026-11-20.

## Test plan

Prove the CLI rejects either half of an apply override before constructing a Client; both
explicit endpoints reach the Client; ordinary production defaults remain unchanged; read-only
preview and local resolution may still select only a Scoreboard. Run SDK and repo gates.

## Acceptance

A dev apply command uses explicitly selected dev Engine and Scoreboard endpoints. No model
calls or production writes are part of these changes.

## Outcome

Implemented. The six endpoint tests first produced four failures; the corrected board-ID test
then caught exactly the two wrong keys. All 45 focused batch tests pass with the fixes.
Full SDK gates (lint, format, types, tests with 95% coverage floor, JavaScript tests, notebook
checks, build and distribution) and repository gates pass. Review confirmed that all 47
source/target pairs remain unchanged, endpoint pairing is checked before Client construction,
and read-only preview/local resolution remain available with a Scoreboard-only override.

Three independent reviews completed at `bfa2c9c50`: the PR diff had no actionable findings
and independently passed all 45 batch tests; the safety review reproduced the six remaining
issues below; the deployment review confirmed that the batch is operator-run but a Scoreboard
upgrade's seed hook can activate the new Engine revisions. Hold revision activation until the
batch fixes and acceptance are ready. Both public catalogues still served all 44 source
revisions at review time. These reviews do not approve production replay.

Read-only live inventory on 2026-11-20: 44 public affected boards, all still on source revisions
in dev and prod. Production has 193 ranked source entries across 31 boards: 183 cached and 10
uncached. Dev has zero source entries. These are snapshots; recount at rollout. The three WMDP
boards are deliberately unlisted by OME-1714, with public revision routes returning 404.
Use an explicit public-board selection for rollout, retaining strict missing-target validation.
Engine catalogues require authentication. Infra #2382 is inaccessible to our GitHub connection.

### Post-merge review: production batch must wait

Dmitry/HupBaHa's review 5996682856 on #1926 (2026-11-20 17:21 UTC) identifies six additional
issues in the merged batch. Local probes with fake regraders and temporary files reproduce all
six; this change does not fix them:

- `_recover` truncates even a complete valid final JSON record if its newline is missing.
- `entry_key` does not distinguish score IDs from spec IDs; CLI splitting also loses keys
  containing `=`. Keys need typed, escaped identity components.
- `_outcome` neither pins the SDK replay to the declared target nor checks the returned
  revision. Add an expected target to SDK planning and validate before posting the result.
- `_source_entries` treats a missing source summary as empty. Require positive evidence of
  zero results; all 44 public sources currently have explicit revision summaries.
- `flock` protects the open log inode; replacing the pathname creates an unlocked new inode.
  Keep a stable lock and detect journal replacement before recording further results.
- `resolve` rejects any already resolved entry, so retrying a multi-entry resolution after a
  crash cannot finish. The identical recorded owner decision should be an idempotent no-op.

Keep OME-1958 open. No production regrades or model calls were made. Dev acceptance also needs
a captured source entry and authenticated access; no browser login was launched.
