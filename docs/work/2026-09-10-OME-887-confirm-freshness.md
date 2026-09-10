---
ticket: OME-887
stack: repo
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-887 — Confirm activity freshness behavior

## Intent

Record owner approval of three minutes without fresh activity, not a three-minute operation deadline. Use reassuring stale-call wording; long calls remain active with fresh heartbeats. Documentation only.

## Planned changes

- Activity spec, plan, task mirror and PR description.

## Test plan

Check consistent approved wording and diff hygiene; add the long-call scenario to the implementation plan. No runtime code changes.

## Acceptance

Fixed 60-second heartbeats keep a long call active. After 180 seconds without fresh evidence, show no recent update without cancelling, failing or timing out work. Replay cannot restore freshness.

## Outcome

- **Actual files:** spec, plan, task mirror and ledger; PR description aligned.
- **Commits:** docs: confirm activity freshness threshold and wording; Refs: OME-887.
- **Gates:** documentation consistency and diff hygiene checked. No runtime tests applicable.
- **Deviations:** none. Only this freshness decision is approved; no product implementation or merge authorized.
