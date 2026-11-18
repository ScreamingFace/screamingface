---
ticket: OME-1918
stack: scoreboard
status: done
started: 2026-11-17
finished: 2026-11-17
---

# OME-1918 — Short weight labels

## Intent

Show lowercase open, closed, and hybrid beneath leaderboard backends, as requested in OME-1918.

## Planned changes

- Add an optional is_hybrid flag to ranked responses, derived from the existing bounded model read and registry.
- Update portal labels and remove the weights suffix.
- Preserve binary openness/frontier calculations, operator overrides, unknown fallback, private-board behavior, and model-list privacy.

## Test plan

- Exercise actual mixed-model route responses, all-open/all-closed/unknown combinations, overrides, and unchanged frontier counts.
- Update only the two old capitalization assertions, authorized by the user's explicit request to implement the ticket; record exact test-file approval.
- Run scoreboard gates and inspect the real page with mixed fixture data at desktop/mobile in light/dark themes.

## Acceptance

Known mixed entries display hybrid; open and closed labels are lowercase without a weights suffix. Unidentified entries retain the dash. No migration or new database query.

## Outcome

- Actual files: classifier, ranked response, two portal scripts, existing route and label tests, exact JS test approval, spec/plan/task mirror.
- Commit: `feat(scoreboard): show open closed and hybrid weight labels` (this commit).
- RED: two route cases failed on the missing hybrid flag; three portal label cases failed on old copy/absent hybrid handling.
- GREEN: 17 route tests and 53 pure portal tests passed. Full `run_gates.py scoreboard --base origin/main` passed, including lint, formatting, type checking, Python suite with coverage, all named portal suites and exact test-change approval. Log: `/tmp/ome1918-gates.log`.
- Visual: actual portal with illustrative mixed data checked at 1440px and 390px in light and dark; labels fit, no page-wide overflow, no browser errors. Mobile uses the existing horizontally scrollable table. Screenshots: `/tmp/ome1918-{1440,390}-{light,dark}.png`. Local preview: http://127.0.0.1:9198/benchmark.html?id=demo.
- Review: no new query, migration, dependencies, exposed model list, or changes to frontier calculations. Hybrid detection shares the existing registry and snapshot; unknown routes and overrides are handled conservatively. Existing CSS provides the label tone.
- Deviations: no new screenshot binaries or fixture snapshots committed; visual evidence is local. Backend flag was necessary because the old API collapsed mixed submissions into closed.
- Ticket remains open pending PR review and merge.
