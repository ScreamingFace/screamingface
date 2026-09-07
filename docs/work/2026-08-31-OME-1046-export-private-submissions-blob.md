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

## Split into two units — 2026-09-07

**This is a named Fusion Monsters launch item**, and the launch is today. Irina's 2026-08-31
`#scream-updates` post lists "provide a path to the FM program team to view the submission to
the entry challenge" among the last prod/eng elements. That connection was not made when this
ticket was written, and it changes the shape of the work.

Owner decision today: **separate the need from the machinery.**

1. **Today, manually.** `export_private_submissions.py` already works, with four passing
   tests. Run it per private benchmark, hand the file to the FM team. The launch item is then
   satisfied — the team can see every submission and decide who is upgraded.
2. **After the launch, automated on Azure Blob** — not Garage. §4.6 of the spec records why.

**The Garage choice was wrong, and it took reading the engine's chart to see it.** Its own
values file calls it "a single-consumer hand-off store for objects that live <48h, not a
durability tier" — one replica, 10Gi RWO. This ticket parks timestamped exports there
permanently. Worse, Garage belongs to the *engine's* chart and holds the engine's artifact
spill store, so filling that volume degrades benchmark runs. The scoreboard chart has no
object storage at all, so "reuse the existing store" meant reaching across an app boundary
into a scratch disk.

**A silver lining worth naming:** Azure Blob supports Entra ID, so access by email address —
what the owner asked for on 2026-09-04 and what D10 traded away for pre-signed URLs — comes
back. D10's compromise existed only because Garage credentials are S3 keys, not identities.

**Cost of the reversal:** D8's SigV4 helper reuse is void, since Azure Blob does not speak the
S3 API. A storage account and credential must be provisioned. The `{benchmark_id}/` key layout
survives unchanged.

### Recommended before the handover today

The script emits JSONL with full email addresses. That is right for a machine and wrong for
the FM program team, who need to read names and scores to make upgrade decisions and cannot
open JSONL in a spreadsheet. A `--format csv` flag is small and contained, and is what makes
the manual path usable by the people it is for. Not blocking; worth doing.

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
