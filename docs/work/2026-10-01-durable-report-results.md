---
ticket: OME-1448
related: OME-1422
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# Durable report results

## Intent
Prevent loss of paid completed results and bound SDK/report memory use. User approved
combined scope, automatic retention until deletion, fail-closed disk errors, per-candidate
recovery, and lazy case access after a design interview.

## Planned changes
SDK result storage/recovery, transport materialization, result decoding, Report case
collection, notebook browser, tests, public usage documentation, existing draft PR.

## Test plan
Start with disk-case behavior and export identity tests; add streamed transport integrity,
recovery after process death, partial results, disk errors, and large fixture RSS tests.

## Acceptance
Both issue acceptance requirements and approved spec, SDK gates, notebook demonstration.

## Outcome
Implemented SDK-only automatic retention and recovery, streamed artifact downloads,
incremental JSON-to-SQLite indexing, lazy case access, streamed full export, and a
pagination-only notebook browser. The Engine API and report.v1 export are unchanged.

### Evidence
- Fresh-process crash/recovery test terminates during indexing, then recovers and
  checks complete exported JSON against the original.
- Sync and async protocol tests recover remote artifacts without starting model work.
- Tests cover integrity failures, expiry with age, disk-full failure, alternate-directory
  recovery, incomplete evaluations, case identity/indexing, and unchanged export bytes.
- Synthetic 11 × 4,182-case workload: each candidate is 201,892,405 bytes; full export
  is 2,219,533,910 bytes; fresh-process peak RSS is 62,832,640 bytes (~60 MiB), below
  the 512 MiB regression threshold. This measures recovery, indexing, and export;
  it is not a paid benchmark or production network load test.
- JupyterLab restarted its kernel and reopened the saved 46,002-case Report. Verified
  Next (26–50), Previous availability, and full 48,000-character input in text pages.
  Screenshot: `docs/work/assets/OME-1422-report-browser.png`.

### Approved contract changes and verification adjustments
The user explicitly requested pagination only and approved disk-backed result loading.
Existing filter/CSV expectations and artifact-body expectations were updated to that
contract. Public API snapshot regeneration records `sf.runs` and `save_results`.
The gate runner uses `--skip-append-only` for these approved changes; lint, format,
typing, coverage, notebook, build, and distribution gates remain enforced.
Two pre-existing disconnect tests now use a zero reconnect budget so they exercise
the same terminal-disconnect assertions without waiting for the production retry window.

### Limits
Saved raw files, indices, and exports consume disk space and contain original prompts.
They remain until explicit deletion. Undownloaded remote results still depend on Engine
retention; a crash before the SDK receives and records completion is outside this client-only
fix. Explicit whole-data conversions can still use substantial RAM. Custom transports own
their persistence. No Engine deployment or paid model call was performed.

Final verification: `uv run .claude/scripts/run_gates.py screamingface --skip-append-only`
passes lint, format, Pyright, the SDK suite (2,113 passed, 26 skipped, 26 paid tests
excluded), 95.73% coverage, notebook checks, wheel/sdist build, and distribution checks.
`git diff --check` passes. Implementation is committed as
`fix(client): retain and recover large evaluation results` in draft PR #1156;
no merge or issue closure is claimed.

### Design review
Persistence stays at the existing transport boundary; the existing Report remains the
public result type. A small SQLite index provides positional and identity lookup without
adding a server protocol, a second Report schema, or a query/filter framework. Recovery
stores JSON metadata, no credentials or pickle. Downloads verify size/hash before atomic
publication; index publication is also atomic. The tests exercise observable recovery and
export behavior. The intentional public additions and lazy-case behavior are documented.

Presentation follow-up: the owner rejected the added detail/full-content tabs.
See `2026-10-01-report-presentation.md` for the restored original case layout and
disabled asynchronous export state. Earlier text-page verification is historical.
