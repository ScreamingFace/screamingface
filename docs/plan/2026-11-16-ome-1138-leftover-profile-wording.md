---
status: approved   # owner, 2026-11-16
issue: OME-1940, OME-1941   # gateway, SDK; both under OME-1138
parent: OME-1138
date: 2026-11-16
---

# OME-1138 follow-up — retire the leftover Profile wording: plan

Implements `docs/spec/2026-11-16-ome-1138-leftover-profile-wording.md`. One branch and one PR
carry both leaves, as L6 did (#1613).

## Steps

1. **Ledger.** `docs/work/2026-11-16-retire-leftover-profile-wording.md`, `ticket: unfiled`.
2. **RED.** Add new tests; no prior test changes in this step.
   - For each of the four OAuth plugins: an empty store raises `CredentialNotFoundError` with the
     §2.1 text; a rejected refresh raises `ReauthRequiredError` with the §2.1 text. Each test also
     asserts that "profile" and "Electron" are absent. The tests go next to each plugin's existing
     auth tests and reuse their fixtures.
   - The Gemini chat handler with no credential and no environment key answers 401 with the
     §2.1 text.
   - Run them and confirm they fail on the old wording.
3. **GREEN.** Change the nine message literals (§2.1). Run the full gateway suite.
4. **Comments.** Edit the §2.2 comments, one wording pass. No code token changes; `ruff` and
   `pyright` confirm it.
5. **Test doubles.** Delete the eight unused `mutate` methods (§2.3). `pyright` and the suite
   confirm nothing calls them.
6. **SDK.** Change the fixture scope (§2.4).
7. **Gates.** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` and
   `uv run .claude/scripts/run_gates.py screamingface --base origin/main`. Until the manifest
   exists, the append-only check stops on the steps 5 and 6 files; that is expected.
8. **Commit and push** the branch under its slug.
9. **PR-open**, after the owner confirms the two leaves:
   - file leaf 1 (`aigateway`) and leaf 2 (`client-sf`) under `OME-1138`, self-assigned;
   - rename the branch to `OME-<leaf 1>-retire-leftover-profile-wording`;
   - add `.claude/test-change-approvals/OME-<leaf 1>.json` with the base and approved blobs of the
     nine changed test files, plus the two `docs/tasks` mirrors;
   - rerun both gates, push, and open the PR from `pr_template.md` with
     `Refs: OME-<leaf 1>, OME-<leaf 2>`.
10. **Close.** After the owner merges: a close comment on each leaf, mirrors and ledger to `done`.

## Risks

- A plugin message might reach a client verbatim. Nothing in the repository matches on it, and
  the new wording names no internal identifier beyond the credential name the old one already
  showed.
- Comment edits are reviewed by reading the diff; no guard test is added, because the kept history
  comments would need an allow-list larger than the change.
