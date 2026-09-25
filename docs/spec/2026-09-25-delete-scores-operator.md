# Delete named scores from a public board

For `OME-1384`, under epic `OME-1251`. Ledger: `docs/work/2026-09-25-delete-scores-operator.md`.

## §1 The command

```
python -m scoreboard.delete_scores --benchmark <id> (--id <uuid> ... | --submitted-before <iso>) \
    --expect <n> [--yes]
```

Run inside the scoreboard pod, the way `OME-986` ran `retire_benchmark`:

```
kubectl -n sf-scoreboard exec deploy/scoreboard -- python -m scoreboard.delete_scores \
    --benchmark draco-3pass --submitted-before 2026-09-09T00:00:00Z --expect 7 > backup.jsonl
```

## §2 Rules

| Rule | Why |
| -- | -- |
| **Nothing is deleted without `--yes`.** | The house rule for destructive operator modules (`retire_benchmark`). |
| **`--expect` is required and must equal the match count, or nothing happens.** | A filter that matches more than the operator saw is the failure that matters. The count is the operator's statement of what they reviewed. |
| **Exactly one selector: ids, or a submitted-before cutoff.** Always scoped to one benchmark. | Ids are the precise form; the cutoff is what an operator can type without a score-id listing, which the public API does not provide. |
| **Private boards are refused.** | They have their own export-verified path, `purge_private_benchmark` (`OME-1027`). This must not become a way around it. |
| **The backup goes to stdout, in both modes.** It is the `export_private_submissions` JSONL of exactly the selected rows. Messages go to stderr. | A file written in the pod is lost with the pod. Stdout survives `kubectl exec` and lands on the operator's disk. Reusing the export format means one format for "every field of a score". |
| **Selection, count check and delete run in one transaction.** A delete count that differs rolls back. | A row landing between the read and the write must not be deleted unseen, and a partial delete must not happen. |
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
