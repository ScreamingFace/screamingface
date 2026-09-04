# OME-1046 — Export private leaderboard submissions to object storage on a schedule

**Ticket:** [OME-1046](https://linear.app/openmined/issue/OME-1046/export-private-leaderboard-submissions-to-object-storage-on-a-schedule)
· **Ledger:** `docs/work/2026-08-31-OME-1046-export-private-submissions-blob.md`
· **Stack:** scoreboard · **Date:** 2026-08-31

## 1. Problem

Internal, non-technical team members currently have no way to see every submission on a
private leaderboard. The only path today is `export_private_submissions.py`
(`apps/scoreboard/src/scoreboard/export_private_submissions.py`), a CLI script requiring
DB and shell access — unusable by anyone who isn't already comfortable running Python
against production.

The team explicitly rejected building an admin/query API to close this gap — that would
reverse OME-894's own decision (D6: "Staff access is a read-only operator module, never an
admin API"), made specifically because a query surface is "something to secure, guess, or
accidentally expose." This spec keeps that decision: the fix is to make the *existing*,
already-safe script's output land somewhere non-technical people can reach, not to add a
new way to query the database live.

Viewing UI is a separate, later ticket — out of scope here (§6).

## 2. Established facts

Verified against this worktree at `ea4c866a` (branched from `origin/main`); none assumed.

| # | Finding | Evidence |
|---|---|---|
| F1 | The export script takes exactly one `--benchmark <id>`, is read-only, and prints JSONL to stdout with the submitter's **full** email (not the local-part-trimmed public form) | `export_private_submissions.py:66-71, 45-56` |
| F2 | There is no existing helper to list *all* private benchmark ids — only `set_visibility`/seed-time filters exist | `scores/store.py:444-472` (grepped, no list-by-visibility) |
| F3 | `Benchmark.visibility` is a nullable `CharField`, default `"public"`; `None`/unset also means public | `scores/models/benchmark.py:32-41` |
| F4 | The repo already has a self-hosted S3-compatible object store (Garage) in production use, with an established config/env-var pattern | `apps/screamingface-engine/src/screamingface_engine/artifacts/s3.py`, `job_env.py:264-279` (`ARTIFACT_S3_ENDPOINT_URL/BUCKET/REGION/ACCESS_KEY/SECRET_KEY`, region default `"garage"`) |
| F5 | Scoreboard's own `Settings` uses `env_prefix="SCOREBOARD_"` and already has exactly one comparable secret-backed field (`database_url`, injected via `secretKeyRef` in the chart) | `config.py:28-38`; `charts/scoreboard/templates/job-seed-benchmarks.yaml:39-43` |
| F6 | Scoreboard already ships two Helm-templated one-shot `Job`s from the same container image (migrate, seed) — no existing `CronJob` | `charts/scoreboard/templates/job-migrate.yaml`, `job-seed-benchmarks.yaml` |
| F7 | No GitHub Actions workflow in this repo runs on a `schedule:` against app-level, per-service work — the two existing `schedule:` workflows are repo-wide checks unrelated to any app's database | grep across `.github/workflows/*.yml` |

F4+F6 together are the load-bearing pair: the object-storage pattern to reuse already
exists (F4), and the deployment mechanism to reuse for *running* the export also already
exists as a Helm-templated Job pointed at the same image (F6) — a `CronJob` is the same
shape with a `schedule:` added, not a new deployment concept. F7 rules out GitHub Actions
as the runner: a CI job would need direct production DB credentials shipped to CI, a worse
posture than a Job already running inside the cluster with the access the app already has.

## 3. Decisions

| # | Decision | Source |
|---|---|---|
| D1 | ~~The runner is a Kubernetes `CronJob`~~ — **superseded by D9.** A CronJob still exists, but as the safety net behind the event trigger, not the primary mechanism | F4, F6, F7; revised by owner 2026-09-04 |
| D2 | Reuse the existing self-hosted Garage-compatible object store; no new cloud account. **A new bucket**, not a prefix in an existing one | user, this session ("perhaps... blob storage") + F4; bucket confirmed by owner 2026-09-04 |
| D3 | No new HTTP/query surface of any kind — this stays a batch write, keeping OME-894 D6 intact | user, this session ("don't want an admin API") |
| D4 | The bucket is private; nothing here makes it network-reachable outside the export job's own upload | ticket scope |
| D5 | ~~Export cadence: hourly~~ — **superseded by D9** | revised by owner 2026-09-04 |
| D6 | One run exports **every** private benchmark, one object per benchmark, not one object per submission | keeps the object count bounded and the script's existing per-benchmark shape (F1) |
| D7 | Object key includes an export timestamp; the job does not overwrite in place | lets a bad run be diffed against the previous one before anything downstream reads it |
| D8 | Reuse the engine's S3 **request plumbing** (`_signed_headers`, `_request`, `_url_path`), **not** its `write_text`/`write_bytes` API | `s3.py:120` keys every object by `sha256(content)`. That store is content-addressed by design, which cannot express the `{benchmark_id}/` layout D2 and §4.2 require. Discovered 2026-09-04 |
| D9 | **Export is triggered by the submission itself, debounced, with a daily CronJob as the safety net** | owner 2026-09-04 ("can't it be instant after submission instead of polling?"). See §4.4 for why it is not purely event-driven |
| D10 | Read access is by **time-limited pre-signed URL**, not an identity check | owner 2026-09-04. Explicitly chosen over a Cloudflare Access email allowlist; the trade is recorded in §4.5 |

## 4. Design

### 4.1 Enumerate private benchmarks

`export_private_submissions.py` gains a small, still read-only helper (F2 is the gap):

```python
async def list_private_benchmark_ids() -> list[str]:
    return await Benchmark.filter(visibility="private").values_list("id", flat=True)
```

And a `--all-private` mode alongside the existing `--benchmark <id>` (F1 stays exactly as
today — no behavior change for the existing single-benchmark call). `--all-private` calls
`collect_submissions` once per id, in the same request as today: still one DB read pass,
still zero writes.

### 4.2 Upload step

A new, separate module — `scoreboard.export_and_upload_private_submissions` — composes the
existing export function with an S3-compatible `PUT`, deliberately kept apart from
`export_private_submissions.py` so that module's read-only, no-network-write invariant
(its own docstring's INVARIANT, F1) stays true by construction; the upload lives next to
it, not inside it.

Config, following F5's exact prefix pattern and F4's field names verbatim (so the two
adapters read as the same idea in two apps, not two conventions):

```python
# scoreboard/config.py — new fields on Settings
export_s3_endpoint_url: str = ""
export_s3_bucket: str = ""
export_s3_region: str = "garage"
export_s3_access_key: str = ""
export_s3_secret_key: str = ""
```

Env vars: `SCOREBOARD_EXPORT_S3_ENDPOINT_URL`, `_BUCKET`, `_REGION`, `_ACCESS_KEY`,
`_SECRET_KEY` — the secret key injected via `secretKeyRef`, mirroring how
`SCOREBOARD_DATABASE_URL` already is (F5).

Object key: `private-submissions/{benchmark_id}/{iso8601_timestamp}.jsonl` (D7).

### 4.3 CronJob

New `charts/scoreboard/templates/cronjob-export-private-submissions.yaml`, structurally
identical to `job-seed-benchmarks.yaml` (F6) with `kind: CronJob` and a `schedule:`:

```yaml
{{- if .Values.exportPrivateSubmissions.enabled -}}
apiVersion: batch/v1
kind: CronJob
metadata:
  name: {{ include "scoreboard.fullname" . }}-export-private-submissions
spec:
  schedule: {{ .Values.exportPrivateSubmissions.schedule | quote }}
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: export-private-submissions
              image: {{ include "scoreboard.image" . | quote }}
              command: [python, -m, scoreboard.export_and_upload_private_submissions]
              env:
                - name: SCOREBOARD_DATABASE_URL
                  valueFrom: {secretKeyRef: ...}   # same secret as job-seed-benchmarks.yaml
                - name: SCOREBOARD_EXPORT_S3_ENDPOINT_URL
                  value: {{ .Values.exportPrivateSubmissions.s3.endpointUrl | quote }}
                - name: SCOREBOARD_EXPORT_S3_BUCKET
                  value: {{ .Values.exportPrivateSubmissions.s3.bucket | quote }}
                - name: SCOREBOARD_EXPORT_S3_ACCESS_KEY
                  valueFrom: {secretKeyRef: {name: ..., key: access-key}}
                - name: SCOREBOARD_EXPORT_S3_SECRET_KEY
                  valueFrom: {secretKeyRef: {name: ..., key: secret-key}}
{{- end }}
```

Disabled by default (`exportPrivateSubmissions.enabled: false`), matching how
`seedBenchmarks` gates its own Job — a deploy that doesn't set the values gets no new
behavior.

### 4.4 Trigger: event-first, cron as the backstop (D9)

The owner asked for instant export rather than polling. That is the right default — staff
reviewing a live challenge should not wait an hour — but a *purely* event-driven design
loses three guarantees the cron gave for free, so the trigger is both.

**Why not events alone**

1. **The export must never fail a submission.** It runs after the response is sent, never
   inline. Garage being slow or unreachable must not turn a stored submission into a 5xx.
2. **In-process background work does not survive a pod restart, and does not retry.** One
   dropped event leaves the bucket permanently stale with nothing to notice it. A periodic
   run self-heals; events do not.
3. **Bursts and races.** D6 keeps one object per benchmark holding every submission, so each
   trigger re-exports the whole benchmark. Ten submissions in a minute means ten full
   re-exports, and two concurrent ones can finish out of order, leaving an older snapshot as
   the newest object.

**Shape**

- On a successful submission to a **private** benchmark, schedule an export of *that*
  benchmark after the response (FastAPI `BackgroundTasks`).
- **Debounce per benchmark** — coalesce triggers arriving inside the window into one export,
  which removes both the burst cost and the out-of-order race.
- A **daily** CronJob runs `--all-private` regardless. This is the convergence guarantee: it
  is what makes a lost event a delay rather than permanent staleness.

**"Submission" includes corrections.** `OME-1054` lets a resubmission update an existing
row's authors without inserting one. The trigger must fire on that path too, or a corrected
credit line never reaches the bucket — the exact case that ticket exists to serve.

### 4.5 Read access: pre-signed URLs (D10)

The owner's first answer was an email allowlist for OpenMined staff; the decision taken was
pre-signed URLs instead. Recording the trade honestly, because the two are not equivalent:

- Garage credentials are S3 access keys, not identities. An email allowlist needs something
  that authenticates *people* in front of the objects — Cloudflare Access over an HTTP
  surface — and D3 forbids adding one here. The pattern exists in the org (`aigateway`'s
  case-insensitive allowlist, `core/auth/admin.py:50`), so this is a question of where it
  lives, not whether it is known.
- **A pre-signed URL is bearer access.** Anyone holding the link reads every submission on
  that private benchmark for as long as the link is valid, including someone outside
  OpenMined who was forwarded it. There is no identity check and no per-person revocation.
- Mitigation, not a fix: keep the expiry **short** (hours, not days) and re-issue rather than
  extend. Never paste a link anywhere with broader reach than the people who need it.
- Identity-based access remains the viewer ticket's job. This decision is what ships now, not
  the end state.

## 5. Test plan (for the plan/implementation stage)

- `list_private_benchmark_ids` returns only `visibility="private"` ids, and an empty list
  when there are none (never raises).
- `--all-private` produces the same per-benchmark JSONL as calling `--benchmark <id>` once
  per id — byte-for-byte, to prove no divergence was introduced.
- The upload module: given a fake/local S3-compatible target (moto or a local Garage/MinIO
  test double — match whatever `apps/screamingface-engine`'s own S3 tests already use), one
  object per private benchmark lands at the expected key; a benchmark with zero submissions
  still uploads an empty JSONL (so "no object" is never confused with "export never ran").
- Config: env vars parse under the `SCOREBOARD_` prefix exactly like `database_url` does.
- Chart: `exportPrivateSubmissions.enabled: false` renders no CronJob (mirrors the
  `seedBenchmarks` gate test, if one exists — reuse its shape).

Added by D9/D10 — the event path carries the risk, so it carries the tests:

- **A failing upload must not fail the submission.** With the object store raising on every
  call, `POST /v1/scores` still returns its normal 201/200 and the row is still stored. This
  is the one test that must exist; everything else is a staleness bug, this one is data loss.
- **A public benchmark triggers no export.** The whole point is that private boards are the
  only ones dumped; a trigger that fires on public submissions leaks nothing but wastes work
  and would mask a scoping error.
- **Debounce coalesces a burst.** N submissions to one benchmark inside the window produce
  **one** export, not N.
- **A correction triggers an export.** Resubmitting an already-stored recipe with a changed
  author list (the `OME-1054` update path, which returns 200 rather than 201) must still fire
  the trigger — otherwise the corrected credit line never reaches the bucket.
- **The cron still converges.** With the event trigger disabled entirely, `--all-private`
  alone brings the bucket up to date. This is what proves the safety net is real.
- **Pre-signed URLs expire.** A generated link stops working past its TTL, asserted against a
  clock the test controls rather than by sleeping.

## 6. Out of scope

The viewer UI/portal integration (separate ticket — user: "focus on dumping things first")
· any new HTTP query surface (D3) · public/anonymous access to the bucket · retention/
lifecycle policy on old export objects (left to the bucket's own lifecycle rule, per the
same reasoning `s3.py`'s AIDEV-NOTE already gives for artifact objects) · alerting on a
failed CronJob run.

## 7. Owner answers (2026-09-04) and what is still open

All three questions from the first draft were answered by the owner on 2026-09-04.

| Question | Answer | Lands as |
|---|---|---|
| Bucket provisioning | **A new bucket**, with a subfolder per benchmark | D2; the key shape in §4.2 already matched |
| Cadence | **Instant on submission**, not polling | D9 + §4.4 |
| Who can read it | **Pre-signed URLs**, chosen over an email allowlist | D10 + §4.5 |

### Still open — owner or platform actions, not spec gaps

- **Garage bucket + credentials.** Whoever runs Garage must create the new bucket and issue
  a credential scoped to it (read/write on that bucket only). This spec assumes the
  credential exists by deploy time and deliberately does not provision it.
- **Pre-signed URL expiry.** §4.5 recommends hours, not days, and re-issuing rather than
  extending. The exact TTL is a product call and becomes a config value.
- **Who mints and distributes the links.** D10 gives bearer access, so distribution *is* the
  access control. Worth agreeing where links may be pasted before the first one is issued.
- **Debounce window (D9).** A concrete value belongs in the plan stage, chosen against real
  submission rates on a private board rather than guessed here.

### Raised by the owner's answers, for the viewer ticket

The owner's first instinct on access was an **email allowlist for OpenMined staff**, and the
decision taken was pre-signed URLs instead. Those are not equivalent (§4.5). Identity-based
access should be picked up by the viewer ticket rather than treated as settled by D10.
