# OME-1448 — A finished evaluation is lost when the notebook runs out of memory while building its report

Status: Backlog
Parent: OME-1294 (E5 · Improve managing runs in SF Client)
Linear: https://linear.app/openmined/issue/OME-1448

Design ticket. The scope chosen in the interview is options A (recovery record + `sf.recover` /
`screamingface recover`, whole-Evaluation, with recover-to-file bounded by one Candidate), D
(streaming `Report.export()`, same bytes), and a durable local artifact folder
(`~/.screamingface/artifacts`). B and C are later work. All changes are in `packages/screamingface`.

Spec: ../spec/2026-10-01-OME-1448-report-recovery/00-overview.md
Plan: ../plan/2026-10-01-OME-1448-report-recovery.md (waits for approval)
Work ledger: ../work/2026-10-01-report-recovery.md

2026-10-01: spec written on branch `OME-1448-report-recovery`. OQ-1 resolved: a successful
recover marks the record `delivered` (7-day keep). OQ-2: hosted bucket retention goes to a
separate infra ticket, postponed (not filed). OQ-3: no conflict with the E5 runs API; proceed. Plan written: 4 PRs.
