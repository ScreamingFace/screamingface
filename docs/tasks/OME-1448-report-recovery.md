# OME-1448 — A finished evaluation is lost when the notebook runs out of memory while building its report

Status: In Progress
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

2026-10-01: one PR for all of OME-1448 (owner decision), branch `OME-1448-report-recovery`, opened as a
draft. It holds PR A (streaming, atomic `Report.export`) and PR B (durable local artifact folder);
PR C (record) and PR D (recover, notice, CLI) are added to the same branch before it leaves draft.
Ledgers: ../work/2026-10-01-report-recovery-export.md, ../work/2026-10-01-report-recovery-local-dir.md.
