---
ticket: OME-1715  # the spec and plan land with E5a
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-21
finished:
---

# e5-history-cleanup-spec — the spec for purging the retired Profile storage (Stage E, E5)

## Intent

Stage E of `OME-1138` ended Profile authority (E4a–E4c, closed with `OME-1209`), but the storage it
left behind is still in `credential_blobs`: the per-account Profile index documents and the
credential blobs no Connection addresses. The epic spec (§6.2 "History", D6) and the Stage E spec
(R5, §7 Q4) make their deletion a separately authorised cleanup whose reference check and deletion
share one atomic boundary that also fences concurrent reference creation. This unit writes that
spec (and then its plan); no code and no data change here.

## Planned changes

- Draft in `.docs/2026-10-21-e5-history-cleanup-spec.md` (gitignored scratch) until the owner
  approves it; then `docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md` and
  `docs/plan/2026-10-21-OME-1715-e5-history-cleanup.md` (named after the E5a leaf).
- Owner approval 2026-10-21: every §7 proposal (Q1-Q6). The plan then corrected the spec's §4 and
  §5 for E5a (plan §6): `profile_names` and `DEFAULT_LEGACY_NAME` leave in E5a, `profile_admin.py`
  is deleted, the apply precondition is E5a, and E5a moves 21 prior tests, not two.
- Owner approval 2026-10-22 of the plan as written (one E5a PR, then the purge command); the spec
  and plan land with the E5a PR.

## Test plan

- Docs only. The spec names the tests each landing writes first (its §5).

## Acceptance

- Owner approves the spec in plain words, including its open questions (§7).
- Every claim about the code cites a file verified on `origin/main` `b0ce28150`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
