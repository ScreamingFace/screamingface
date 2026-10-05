---
ticket: OME-932
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---
# Early-grade failure metadata

## Intent
Fix the reviewed MedXpert regression in #1096 without changing canonical failed-case output.

## Planned changes
Adjust shared typed-result validation to distinguish required selected metadata from optional grading enrichment on unscored failures. Preserve strict identity and conflicting-metadata rejection. Add real MedXpert round-trip parity tests. Keep unrelated API cleanup separate.

## Test plan
Reproduce grading-failure round trip against batch output, then cover successful metadata requirements and conflicting failure metadata. Run Engine gates.

## Acceptance
A failed grade remains a failed case, never a transport-induced run abort; no regrading or weakened identity checks.

## Outcome
- Reproduced the exact reported ValueError against the real MedXpert fixture before the fix.
- Four new regressions cover canonical failure parity, conflicting metadata on failed/scored results, and required enrichment on scored results. Eleven focused tests passed.
- Full Engine gates green: lint, format, types, layering, tests and coverage. The existing branch's approved fixture migrations require the append-only exception; this patch changes no previous tests.
- Wisdom/confidence review: base selected metadata and identity are validated before optional enrichment; unscored failures may omit enrichment but cannot contradict it. Canonical scoring/output unchanged, no new calls, public API cleanup deferred.
- Commit: `fix: preserve failed grades through incremental transport`.
- Deviations: none.
