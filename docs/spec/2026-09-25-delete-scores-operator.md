# Delete named scores from a public board

For `OME-1384`, under epic `OME-1251`. Ledger: `docs/work/2026-09-25-delete-scores-operator.md`.

**Revised by review rounds 1 and 2 (owner, 2026-09-26).** The first contract wrote the backup to
stdout in both modes, after the delete had committed. It is replaced below: the delete is bound to
a backup already on the operator's disk, and the selected rows are locked until they are gone.

## §1 The command

```
python -m scoreboard.delete_scores --benchmark <id> (--id <uuid> ... | --submitted-before <iso>) \
    --expect <n> [--yes --expect-sha256 <digest>]
```

Run inside the scoreboard pod, the way `OME-986` ran `retire_benchmark`, in two steps:

```
# 1. dry run: the backup lands on the operator's disk before anything is deleted
kubectl -n sf-scoreboard exec deploy/scoreboard -- python -m scoreboard.delete_scores \
    --benchmark draco-3pass --submitted-before 2026-09-09T00:00:00Z --expect 10 \
    > draco-3pass-backup.jsonl
shasum -a 256 draco-3pass-backup.jsonl   # equals the sha256 the dry run printed
# 2. confirm with that digest; nothing is written to stdout
kubectl -n sf-scoreboard exec deploy/scoreboard -- python -m scoreboard.delete_scores \
    --benchmark draco-3pass --submitted-before 2026-09-09T00:00:00Z --expect 10 \
    --yes --expect-sha256 <digest>
```

## §2 Rules

| Rule | Why |
| -- | -- |
| **Nothing is deleted without `--yes`.** | The house rule for destructive operator modules (`retire_benchmark`). |
| **`--expect` is required and must equal the match count, or nothing happens.** | A filter that matches more than the operator saw is the failure that matters. The count is the operator's statement of what they reviewed. |
| **Exactly one selector: ids, or a submitted-before cutoff.** Always scoped to one benchmark. | Ids are the precise form; the cutoff is what an operator can type without a score-id listing, which the public API does not provide. |
| **Private boards are refused.** | They have their own export-verified path, `purge_private_benchmark` (`OME-1027`). This must not become a way around it. |
| **Only the dry run writes stdout: the backup, the `export_private_submissions` JSONL of exactly the selected rows.** Its SHA-256 goes to stderr. The confirmed run writes nothing to stdout. | A file written in the pod is lost with the pod; stdout survives `kubectl exec`. The confirmed run is not where the backup comes from, so a redirect on it could only truncate the reviewed file (round 1). |
| **`--yes` requires `--expect-sha256`, the reviewed backup's digest.** It is recomputed inside the deleting transaction; a mismatch deletes nothing. | The rows can only be deleted once a backup of exactly those rows is on the operator's disk, and a row that changed since the review is caught even when the count still matches (round 1). Same gate as `purge_private_benchmark`. |
| **The selected rows are locked (`SELECT ... FOR UPDATE`) from the digest check to the delete.** | The benchmark lock serialises submit and replay, but `ScoreStore.mark_verified` updates a score without it. Without a row lock, a row could change after its digest matched and before it was deleted (round 2). Pinned on PostgreSQL. |
| **Selection, count check, digest check and delete run in one transaction.** A delete count that differs rolls back. | A row landing between the read and the write must not be deleted unseen, and a partial delete must not happen. |
| **Idempotency keys go with their score.** | Already `ON DELETE CASCADE` (`models/idempotency_key.py:30`). Tested, not reimplemented. |

## §3 The backup is evidence, not a restore file

The JSONL carries every published field of each score. It does not carry the stored
`content_hash` or idempotency keys, so there is no automated restore. Recreating a score means
resubmitting it. That is acceptable for the one use this is built for: the rows being deleted are
wrong, and the replacement is a fresh run.

## §4 Out of scope

- an HTTP delete route: deliberately not built, as for `export_private_submissions`
- deleting baselines or benchmarks: `retire_benchmark`
- private boards: `purge_private_benchmark`
- running it on dev: an owner action through firecall, after merge and the dev deploy
