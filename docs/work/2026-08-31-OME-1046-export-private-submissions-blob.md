---
ticket: OME-1046
stack: sdlc-python
status: in_progress
started: 2026-08-31
finished:
---

# OME-1046 — Export private leaderboard submissions to object storage on a schedule

## Intent

Internal, non-technical team members currently have no way to see every submission on a
private leaderboard — the only path today is `export_private_submissions.py`, a
DB-connected CLI script. The team explicitly rejected adding a new admin/query API
(reversing that would undo a deliberate OME-894 decision) and asked to scope this ticket
to just the data side: run that existing script on a schedule and land its output in
object storage, reusing the self-hosted S3-compatible store (Garage) already proven by
`apps/screamingface-engine/src/screamingface_engine/artifacts/s3.py`. The viewer UI is a
separate, later ticket.

## Planned changes

Per `docs/spec/2026-08-31-OME-1046-export-private-submissions-blob.md` — pending owner
answers to §7 and explicit approval before `docs/plan/` and code:

- `apps/scoreboard/src/scoreboard/export_private_submissions.py` — add
  `list_private_benchmark_ids()` and `--all-private`
- `apps/scoreboard/src/scoreboard/export_and_upload_private_submissions.py` — new module,
  export + S3-compatible upload
- `apps/scoreboard/src/scoreboard/config.py` — `export_s3_*` Settings fields
- `apps/scoreboard/charts/scoreboard/templates/cronjob-export-private-submissions.yaml` —
  new, gated by `exportPrivateSubmissions.enabled`
- `apps/scoreboard/charts/scoreboard/values.yaml` (+ `values-prod.yaml` if applicable) —
  new `exportPrivateSubmissions` block

Added after the owner's 2026-09-04 answers (D9/D10):

- `apps/scoreboard/src/scoreboard/routes/scores.py` — schedule the export after a successful
  submission to a **private** benchmark, via `BackgroundTasks`, never inline
- a small per-benchmark debounce so a burst coalesces into one export

## Owner answers — 2026-09-04

The three §7 questions are answered; the spec is updated and the decisions table now carries
D8–D10.

| Question | Answer |
|---|---|
| Bucket | A new bucket, subfolder per benchmark. The key shape in §4.2 already matched |
| Cadence | Instant on submission rather than polling — now D9 |
| Read access | Pre-signed URLs, chosen over an email allowlist — now D10 |

**Two things found while recording them, neither previously known:**

1. **The engine's S3 helper cannot produce the key layout this needs.** `s3.py:120` derives
   every key from `sha256(content)` — the store is content-addressed by design, so it cannot
   express `{benchmark_id}/`. The SigV4 plumbing is still reusable; the `write_text` API is
   not. Recorded as D8. Had this stayed unnoticed until implementation, "reuse the proven
   helper" would have looked like a small task and turned out not to be one.
2. **Instant export cannot be purely event-driven.** In-process background work does not
   survive a pod restart and does not retry, so one dropped event leaves the bucket
   permanently stale with nothing to notice. The cron is kept as the convergence guarantee,
   demoted from mechanism to safety net. §4.4 records this.

**Deviation from the owner's stated intent, recorded deliberately.** The answer to "who can
read it" was *"should be openmined team people, but some sort of whitelisting by email"*; the
decision taken was pre-signed URLs. Those are not the same thing — a pre-signed URL is bearer
access with no identity check and no per-person revocation, so anyone forwarded a live link
reads every submission on that private board. Chosen knowingly for simplicity, with a short
expiry as mitigation. Identity-based access stays with the viewer ticket. Flagged here so the
gap is a decision on the record rather than something discovered later.

## Test plan

See spec §5, including the six cases D9/D10 added. The load-bearing one: a failing upload
must not fail the submission. Every other new case is a staleness bug; that one is data loss.

## Acceptance

Spec approved through §7. Implementation still needs the plain-words go-ahead, plus the
Garage bucket and its scoped credential, which are owner/platform actions this spec does not
provision.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** —
- **Commits:** —
- **Gates:** —
- **Deviations:** —
