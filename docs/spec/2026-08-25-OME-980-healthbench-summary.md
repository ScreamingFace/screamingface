# OME-980 — HealthBench preparation success summary

Status: approved (owner, 2026-08-25) · Stack: screamingface-engine

## Problem

HealthBench preparation completes successfully, but its family CLI then reads the removed
`worst30_cases` summary key. The preparer now truthfully exposes the compile-time selection as
`declared_worst30_cases`, so rendering the success message raises `KeyError` after the assets have
already been written.

## Contract

- `_prepare()` continues returning `declared_worst30_cases`; the honest audit name is not reverted.
- `main()` reads that key when rendering its success message.
- The success path returns zero and reports both the professional-case and declared worst-30 counts.
- Dataset bytes, benchmark selection, registry behavior, and runtime evaluation do not change.

## Acceptance

- A HealthBench-specific CLI regression test exercises the real summary shape.
- The test fails on `origin/main` with the stale-key `KeyError` and passes after the lookup repair.
- The complete `screamingface-engine` quality gates pass.
