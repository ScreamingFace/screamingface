---
ticket: OME-1309
stack: scoreboard
status: in_progress
started: 2026-11-10
finished:
---

# SAD profile and dev acceptance

## Intent

Finish the owner-approved qualifying external-result test on dev using the previously audited SAD results. No production writes or paid model calls. Keep Linear unchanged until approved.

## Planned changes

Carry forward the reviewed local SAD evidence, import fixture, and pinned comparison profile onto current main. Preserve historical observation timestamps. Keep this change separate from edit history and the Source-button redesign.

## Test plan

Run the existing seven SAD regression cases before adding the profile (expected failure), then the complete scoreboard gates. Recheck current dev scope, metadata fields and fail-closed ranking. A live import requires verified firecall access and deployment of the new profile through the normal review/release process.

## Acceptance

A current-main, tested SAD profile and import fixture are ready for review. Report local validation separately from live acceptance; never patch a running service to bypass profile review.

## Outcome

Public dev check: UI eligibility guard is deployed; SAT trial rows have ranking_eligible=false and the new metadata fields. SAD remains revision c55f043049f958b9, 249 cases, no imported rows. Previous firecall address presents a changed host key; current verified access requested.

The qualifying import case failed on current main without the profile, then all seven SAD cases passed with it. Full scoreboard and repository gates passed, including the complete Python suite, coverage, all portal tests, formatting, lint and types. The public source table was rechecked on 2026-11-10 and still reports the same values and full dataset coverage. No dependency, schema or UI change. Existing tests were preserved.

Review: the profile pins exactly one board revision and source question set. The two observations preserve their original source-read dates, full historical evidence, and documented prompt differences. They are not auto-seeded. No running service was patched and no live import has occurred. Live acceptance remains pending verified dev access and normal deployment of this profile.
