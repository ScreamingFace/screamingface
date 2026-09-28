# OME-1027 — Privacy-aware rollback floor

## Problem

Private-board privacy is enforced by application code while the database retains the private rows.
Rolling back to privacy-blind code publishes them. The current preflight correctly detects private
boards, but incorrectly describes package semver as the floor; both privacy-aware and privacy-blind
images package version `0.1.1`. Its fallback runbook also names deletion without providing an
executable, export-verified path.

The development catalogue already marks `healthbench-worst30` private. Current anonymous reads
fail closed, but the rollback/recovery hazard is active now.

## Decisions

### D1 — Release identity is external and immutable

The safe floor is recorded as all three of:

1. the Helm release revision;
2. the deployed image reference;
3. the runtime `imageID` digest reported by Kubernetes.

Package semver remains diagnostic output only. The database preflight cannot inspect Helm history
and must not imply that it can identify a safe target.

### D2 — No Helm hook pretends to guard the rollback

Helm executes the target revision's rollback hooks. A privacy-blind target has no new hook, so the
gate remains an explicit operator procedure.

### D3 — Destruction requires proof of the exact export

Add `python -m scoreboard.purge_private_benchmark` for the exceptional rollback path. It:

- accepts one exact benchmark id, never a pattern;
- refuses a public or unknown benchmark;
- refuses while a baseline references the benchmark;
- computes the same canonical JSONL bytes as `export_private_submissions`;
- requires the operator-provided SHA-256 of the saved export;
- is dry-run by default and deletes only with `--yes`;
- locks the benchmark and verifies the digest before deleting scores and the benchmark in one
  transaction;
- reports exact deletion counts and verifies that the named benchmark is gone.

An export/digest mismatch refuses without deleting anything. The operator re-exports and retries;
this handles submissions arriving between the first export and the purge.

### D4 — Stop serving only after the private data is safely removed

Export and purge run through the still-privacy-aware pod. Purge locks and re-verifies the exported
snapshot, so it is safe while that code serves; after the benchmark is deleted, new submissions to
it cannot persist. The operator then:

1. re-runs the preflight and requires `SAFE`;
2. scales the deployment to zero;
3. waits for every selected pod to disappear;
4. verifies the Service has zero ready endpoint addresses;
5. rolls back;
6. restores the recorded replica count.

This ordering avoids the current impossible instruction to `kubectl exec` export/deletion commands
after all application pods have been removed.

### D5 — Operational evidence cannot be manufactured in code review

The issue is not Done when the PR merges. Closure additionally requires production evidence:

- a privacy-aware release is deployed;
- `helm history scoreboard` identifies the exact rollback target;
- every serving pod reports the expected immutable image digest;
- the preflight has run successfully inside a production pod;
- the operator records the evidence in Linear.

## Security invariants

- Never make a private board public to clear the preflight.
- Never delete a row absent a matching export digest.
- Never roll privacy-blind code into service while any private benchmark remains.
- Never call a mutable tag or package semver the rollback floor.
- The destructive command is unavailable through HTTP and has no bulk mode.

## Non-goals

- Automating `helm rollback`.
- Re-importing purged submissions.
- Changing benchmark visibility, authentication, or database schema.
- Executing destructive steps from tests or CI.
