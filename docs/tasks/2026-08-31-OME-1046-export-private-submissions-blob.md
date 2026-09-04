---
id: OME-1046
linear_url: https://linear.app/openmined/issue/OME-1046/export-private-leaderboard-submissions-to-object-storage-on-a-schedule
status: in_progress
type: task
priority: 3
labels: [scoreboard, agentic, autonomous]
created: 2026-08-31
closed:
---

# Export private leaderboard submissions to object storage on a schedule

Internal (non-technical) team members currently have no way to see all submissions on a
private leaderboard. The only existing path is `export_private_submissions.py`
(`apps/scoreboard/src/scoreboard/export_private_submissions.py`), a DB-connected CLI
script. That script was deliberately built with no admin API — its own docstring states
"the owner decision was deliberately NOT to build an admin API: there is then nothing to
secure, guess, or accidentally expose" (`OME-894`). This ticket keeps that decision: no
new query API.

## Scope

Run the existing export script on a schedule and upload its output to object storage,
reusing the self-hosted S3-compatible store (Garage) already proven by
`apps/screamingface-engine/src/screamingface_engine/artifacts/s3.py` — no new cloud
account, no new credential type.

- Scheduled job (cron/CI) invokes `export_private_submissions.py` per private benchmark
- Uploads the JSONL output to the Garage-compatible bucket
- Bucket/objects stay private — not publicly reachable

## Out of scope (this ticket)

- Any new admin/query API
- The viewer UI/portal work (a later, separate ticket — team explicitly deferred it:
  "focus on dumping things first")
- Public access to the bucket

## Open questions for the spec

- Bucket provisioning: new bucket on the existing Garage instance, or reuse an existing
  one? (likely an owner action)
- Credential issuance path
- Export cadence (hourly? daily?) and per-benchmark vs. all-private-benchmarks-in-one-run

## Context

Session: private-leaderboard-access. User confirmed direction: blob dump over admin API
("don't want an admin API, it's an overkill... especially for non technical people"),
scheduled refresh, Cloudflare Access allowlist for future readers (deferred to the UI
ticket).

## Owner answers — 2026-09-04

The three open questions are answered; see the spec's D8–D10 and §4.4/§4.5.

- **Bucket:** a new one, with a subfolder per benchmark.
- **Cadence:** instant on submission rather than polling. Kept a daily cron as the safety
  net, because in-process background work does not survive a pod restart or retry — without
  it a single dropped event leaves the bucket permanently stale.
- **Read access:** pre-signed URLs, chosen over the email allowlist first suggested. This is
  bearer access, not an identity check; recorded as a deliberate trade with a short expiry,
  and identity-based access stays with the viewer ticket.

Also found while recording these: the engine's S3 helper keys every object by
`sha256(content)`, so it cannot produce the `{benchmark_id}/` layout. Its request plumbing is
reusable; its write API is not.

Implementation still needs the plain-words go-ahead, plus the Garage bucket and a scoped
credential — owner/platform actions this spec does not provision.
