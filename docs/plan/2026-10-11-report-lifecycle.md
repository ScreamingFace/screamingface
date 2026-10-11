# Report lifecycle extraction plan

1. Pin current main and the #1156 source, create an isolated worktree and ledger.
2. Port only the new lifecycle/recovery-notice regression tests and add lifecycle integration regressions; run RED against main.
3. Extract private lifecycle/discovery adapters. Adapt narrow integration hooks to current main instead of copying older implementations.
4. Verify focused tests, shared notice screenshots and all SDK gates. Run parallel Standards/Spec reviews and fix concrete findings.
5. Record outcome/wisdom, create the leaf under OME-1294 and publish/attach a draft PR with before/after screenshots. Do not merge or comment on GitHub.

## Active evaluation follow-up

Register the prepared evaluation itself in the shared tracker before yielding to execution. Classify handled errors by their existing candidates_failed code, rather than treating every ExecutionError as settled. Keep transport cleanup in finally. Add regressions for recovery/export/display finishing during execution, all settlement outcomes, and presentation surviving evaluation completion. Existing tests remain unchanged.

## Shared-store ownership and early recovery failures

Persist per-process operation snapshots and interrupted outcomes alongside the existing state/owner summary, merging them under a POSIX advisory lock before atomic replacement. Keep process-local bookkeeping for existing same-process overlaps and failed optional writes. Preserve foreign live operations, clear dead outcomes only on explicit recovery, and use the summarized owner/state for existing discovery. Destination copies bootstrap their own tracking rather than copying active source tokens.

Enter recovery tracking before Candidate selection, using lightweight membership identity for either evaluation or saved key. Classify only candidates_failed selection errors as handled settlement. Add real subprocess and all-corrupt sync/async regressions first, then run all existing SDK gates and both review axes.

Run-ID follow-up: retain lightweight evaluation-ID/saved-key membership resolution before decoding; when it finds no members, use the existing ResultStore.load run-ID lookup to identify the canonical evaluation before entering recovery. Leave selection errors to the existing public selection path so public contracts remain unchanged.
