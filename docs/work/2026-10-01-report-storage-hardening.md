---
ticket: OME-1448
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# Report storage hardening

## Intent

Integrate implemented export and local-runtime storage improvements from Ionésio's PR #1211 (12b8a390), retaining our case-level streaming, recovery, and notebook UI. User authorized incorporating these improvements; coordination remains with the user.

## Planned changes

- Adopt `_atomic_file.py`, runtime config/server/CLI artifact-folder wiring, and tests from #1211.
- Adapt `_report_export.py` to that writer with parent-directory fsync after replacement.
- Route `Report.to_json()` through the same case-streaming serializer.
- Document attribution, behavior, and limitations in the spec/changelog and PR.

## Test plan

- Run adopted atomic/runtime tests against current code first (missing helper/config must fail).
- Add byte-identity, bounded serialization, fsync, and failure-preservation regressions.
- Run focused tests, small crash/recovery simulation, and all SDK gates.

## Acceptance

- Case-at-a-time serialization remains lossless; failed writes retain prior exports.
- Runtime reader and writer share a persistent folder and respect explicit overrides.
- Gates pass; draft PR updated with attribution to #1211.

## Outcome

- **Actual files:** `_atomic_file.py`, `_report_export.py`, `report.py`, runtime config/server/CLI, three new test files, README/changelog/spec, and the storage-hardening validation JSON.
- **Commits:** `fix(screamingface): harden report exports and persist local artifacts` (this iteration).
- **Gates:** All SDK gates green, including append-only check versus HEAD, Ruff, formatting, Pyright, full tests with >=95% coverage, notebooks, build and distribution. Focused tests: 41 passed, including the small end-to-end crash/recovery simulation.
- **Large validation:** Existing 11 x 4,182 fixture exported 2,219,533,910 bytes at 54,493,184 bytes peak RSS; SHA256 a4988fb137e6a998c439d5e9bb9f257f659c45e176c095a0f867dde8e8f050b7 matches the prior export exactly. Export plus both checksum reads took 21.25 seconds. Files retained in the original fixture directory.
- **Wisdom review:** Preserve case-level streaming and the existing recovery API; adopt implemented durability improvements rather than copying future recovery plans. No dependency, schema, hosted deployment or UI layout changes. Persistent Engine storage remains subject to TTL.
- **Deviations:** Adapted Ionésio's tests to a local umask helper; added POSIX parent-directory fsync. Initial sandbox denied setuid test setup and loopback simulation; all tests passed under the existing authorized escalation. No prior tests changed. User will coordinate with Ionésio; no messages sent.
