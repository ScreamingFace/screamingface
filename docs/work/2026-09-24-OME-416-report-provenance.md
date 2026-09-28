---
ticket: OME-416
stack: screamingface
status: done
started: 2026-09-24
finished: 2026-09-24
---
# OME-416 — Returned Client version provenance

## Intent
Carry the Engine's existing run-scoped screamingface.client.version log attribute into CandidateResult.client_version and portable report JSON. Use the existing ticket, no new Engine contract or ticket.

## Design and planned changes
Decode only sequenced root-source provenance logs. Keep bounded ASCII version tokens (1–128 characters, letters, digits, dot, underscore, plus, hyphen). Ignore malformed values and child/advisory logs; conflicting root versions make provenance unknown. Never substitute the viewer's installed version. Carry the optional value through _RunOutcome and report construction. Public candidate construction validates optional version values. Always serialize client_version, null when absent. No generic report importer currently exists; do not invent one.

## Test plan / acceptance
New tests drive real CloudEvent decoding through report construction and JSON export. Cover absent/invalid/conflicting values, child/advisory logs, replay deduplication, independent runs, direct construction. Preserve prior tests, benchmark identity, scores and prompts. Run full Client gates. Draft PR only, no merge or Linear comments.

## Outcome
- Actual files: Client provenance validator, stream decoder, run outcome, report builder/public model, README, 21 new regression cases, spec/plan/task mirror.
- Validation: 21 focused tests pass. Full gate suite: 1,824 passed, 26 skipped, 95.68% coverage; sole failure is deliberate public API snapshot addition. Lint, formatting, typecheck, notebook generation, build and distribution checks pass.
- Two earlier full runs were interrupted while diagnosing long reconnect tests; completed run took 298 seconds.
- Wisdom review: version is bounded and per-run; no current-install fallback, no new dependency, no Engine imports, no Scoreboard payload changes. Both transports preserve the optional field during dataclass replacement and artifact fetching. No existing behavioral test changed.
- Owner approved the snapshot migration with the request to open both drafts. Snapshot gains only client_version in the two CandidateResult exports; changelog updated. Final Client gate runner ALL GATES GREEN using the explicit --skip-append-only exception for that fixture-only migration. No existing test assertion changed.
- Commit: feat(client): preserve run Client version in reports (see git history). Draft PR follows; no merge.
- Deviations: no report importer exists, so round-trip coverage uses JSON/file export rather than adding an importer. No Linear comments or new issue.
