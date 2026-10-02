---
id: OME-1445
linear_url: https://linear.app/openmined/issue/OME-1445/sdk-tests-fail-at-random-when-the-clock-reads-a-time-containing-05
status: done
type: bug
priority: medium
labels: [bug, client-sf, agentic, autonomous]
created: 2026-10-01
closed: 2026-10-02
---

# SDK tests fail at random when the clock reads a time containing "0.5"

The archive-money test searched the whole serialized submission for the text `0.5`, which the
run's timestamp can contain. It now checks values, so a timestamp can never match.

Ledger: `docs/work/2026-10-01-OME-1445-archive-money-test-flake.md`.
Spec: `docs/spec/2026-10-01-OME-1445-archive-money-test-flake.md`.
Plan: `docs/plan/2026-10-01-OME-1445-archive-money-test-flake.md`.

- 2026-10-01: filed by Khoa after CI on #1149 failed on `ran_at_local` `…08:40:30.507912Z`; fixed
  the same day.
- 2026-10-02: merged via #1195 (`1c5ead9e`), approved by Keelan and Khoa; closed in Linear with the close comment.
