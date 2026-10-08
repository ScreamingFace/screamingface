---
ticket: OME-1486
stack: screamingface
status: in_progress
started: 2026-10-05
finished:
---

# streamed-atomic-report-export

## Intent

Extract the first independently mergeable client PR: case-streamed report.v1 serialization and durable atomic JSON export.

## Planned changes

SDK source and new regression tests only, with spec/plan/task mirrors and changelog documentation.

## Test plan

Write regression tests first and record their failure; run focused tests, preserved SDK tests, coverage, Ruff, Pyright, notebooks and distributions.

## Acceptance

Original JSON bytes and public API remain unchanged; no persistence or notebook dependency enters this PR; all SDK gates pass.

## Outcome

All SDK gates passed: append-only tests, Ruff, format, Pyright, full parallel pytest with the 95% coverage floor, deterministic notebooks, wheel/sdist build and distribution checks. New serializer tests failed before implementation; all 16 focused export/atomic tests pass. Independent Standards and Spec reviewers found no required export changes.

Based on origin/main aa582c12e30e17f527528d8bf649df1e696a2b51. Source export work credited to Ionésio from PR #1211, extracted from PR #1156. No public snapshot or dependency changes. Issue OME-1486 is the focused child of OME-1294.

Approved follow-on split (each PR based on main after prerequisites land): durable collection/indexing/explicit recovery/fusion totals; compact accounting context/cache; paginated notebook browser; lifecycle discovery. OME-1448 and OME-1422 retain the remaining umbrella scope. This draft is the first slice only.

## PR review follow-up

User authorized fixing review findings and checking other regressions on 2026-10-05.
Plan: bound sibling temporary filenames without changing existing short-name behavior;
add long ASCII/Unicode path, failure-boundary and JSON compatibility regressions;
run all SDK gates and update PR #1241. Preserve inherited tests and public APIs.

Follow-up outcome: bounded the temporary basename prefix to 32 characters (at most
128 UTF-8 bytes), preserving short-name behavior and accepting long export filenames.
Also fixed temporary-file/descriptor cleanup if buffered writer construction fails:
`closefd=False` keeps descriptor ownership explicit and it is closed before replacement.
Normalized the fixed WHY comment anchors. Ten added regression cases cover ASCII/Unicode
names, original JSON bytes, multiple Candidates, failures in chmod/fsync/replace,
writer construction, exact descriptor closure, and the post-replacement directory-fsync caveat.
The user explicitly approved adapting the existing full-disk fake's closefd signature;
all inherited assertions remain intact, with the transition pinned in OME-1486.json.

Validation: both regressions reproduced before correction; all SDK card gates green
(append-only including the approved helper transition, Ruff, formatting, Pyright,
full parallel tests at 96% coverage, deterministic notebooks, wheel/sdist and distribution
checks). Final focused atomic/export regressions: 22 passed. Independent corrective
Standards and Spec reviews found no remaining required changes. No additional behavior
regressions found in the reviewed slice. No public signature or dependency changes.

## Serialization throughput follow-up

User approved correcting the inherited serialization slowdown and updating PR #1241.
Design: stream only the Report/Candidate envelopes and Case sequence; encode each
already-materialized Case and ordinary field value with the standard JSON encoder.
This keeps one Case dictionary at a time, preserves report.v1 bytes, and avoids
per-scalar encoder allocation and writes. No public API or dependency changes.

Planned checks: add a deterministic regression proving one complete Case is emitted
before the next Case is materialized; run it RED, then all export regressions and SDK
card gates. Repeat the 5,000-Case throughput probe and compare tracemalloc peaks at
increasing Case counts, excluding construction of the immutable source Report.

Follow-up evidence (local CPython 3.14, 5,000 valid Cases with nested JSON/Unicode,
1,640,003 identical UTF-8 bytes; seven repetitions against the pre-fix PR serializer):
median `to_json()` improved from 0.4773s to 0.0358s (13.3x), and fsynced atomic
file export improved from 0.4334s to 0.0369s (11.8x). These are local fixture timings,
not a portable throughput guarantee. Tracemalloc started after source Report creation:
auxiliary export peak was 1,060,488 bytes for 1,000 Cases and 1,060,496 bytes for
10,000 Cases. Whole Cases are encoded as single chunks; the next Case is not
materialized until the current chunk is consumed. Byte compatibility, return paths,
symlinks, modes, failure retention and cleanup passed the production-path probes.
The new Case-boundary regression failed against the inherited scalar serializer and
passes after correction. A read-only SF corrective review found no required changes.

Validation outcome: all screamingface card gates passed (append-only check, Ruff,
formatting, Pyright, full parallel pytest with the 95% coverage floor, deterministic
notebooks, wheel/sdist build and distribution checks). All 26 focused export/atomic
regressions passed. The initial sandboxed focused run could not set the pre-existing
setuid fixture bit; the unchanged test passed outside the sandbox, as did the full
gate runner. No prior tests or assertions were changed, and no paid calls were made.
