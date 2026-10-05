---
ticket: OME-1422
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# Saved accounting context and numeric report search

## Intent

Reuse derived accounting facts across report reopening and diagnose the owner's five-second numeric search without changing full-content search silently.

## Planned changes

- Versioned, atomic derived accounting cache beside immutable case indices; populate when decoding saved reports, reuse in the browser.
- Validated numeric-grade count and compact failure rows in SQLite; upgrade existing indices transactionally with read-only fallback.
- Preserve original accounting and full report export; rebuild stale or malformed cache and tolerate an unwritable cache directory.
- Search follow-up depends on clarification of case identity versus combined result position.

## Test plan

- Saved context reuse avoids case decoding on subsequent report/browser opens.
- In-memory reports retain current behavior; metadata/version changes invalidate cache.
- Missing, corrupt and unwritable cache preserves exact accounting and readable reports.
- Reproduce numeric search and verify intended lookup without full-content regressions.

## Acceptance

Repeated report openings reuse only small derived facts. No original results are changed or dropped. Numeric search behavior is clear and timed; all SDK gates pass.

## Outcome

- New tests first failed for absent accounting cache, then exposed repeated case validation and summary scans. Fixed by retaining validated counts and compact failure rows without retaining prompts in memory.
- Accounting context cached as small atomic JSON beside the SQLite index. Missing/version-stale/checksum-invalid/malformed cache is rebuilt; write failures preserve reporting. Original raw JSON and report export are unchanged.
- Synthetic 46,002-result fixture: warm report reopening 0.773 seconds; browser construction 0.177 seconds. These exclude initial migration and frontend paint, and are not a real-world latency guarantee.
- Substring-index probe preserved full-content semantics and accelerated selective queries, but was discarded after the owner clarified that the input should navigate to a case number, not search text. Browsing UX remains under discussion; do not claim it has shipped.
- Wisdom: optional derived facts stay separate from primary results; schema upgrades are in the same iteration, transactional and backward compatible. No new dependency, public API or exported field. Cache format version must advance when accounting projection rules change.
- All SDK gates green (lint, formatting, types, full tests with 95% coverage threshold, notebook examples, build and distribution). Fifteen focused cache/upgrade tests pass. Local-server tests need execution outside the filesystem sandbox to bind loopback; the required gate run exercised them successfully.
- Commit: `perf(client): reuse saved report accounting and coverage`.
