# OME-1002 — Report-intake implementation plan

**Spec:** `docs/spec/2026-08-26-OME-1004-report-intake-service.md` (`OME-1004`, PR #748).
**Review context:** `docs/spec/2026-08-22-observability-traceability-review.md` (`OME-936`, PR #688).
**Plan ticket:** `OME-1015`. **Epic:** `OME-1002`.

The spec fixes *what the service does*. This plan fixes *how it gets built in this repo*:
build order, which in-repo pattern each item copies, and — the part that matters most — the
contracts between items, frozen here so seven parallel work units cannot each invent their
own.

## 0. Settled before planning

Three forks were decided by the owner on 2026-08-26 and are not re-litigated below.

- **Sink** — `TicketSink` port plus `QueueSink`. `LinearSink` is a deferred follow-up gated
  on `OME-976`. Product code holds no Linear credential in this pass, so no new secret class
  is introduced. The port is the seam; `LinearSink` later is one adapter file plus one
  registry entry.
- **Auth** — anonymous submission **is** admitted, with Cloudflare Turnstile and an edge rate
  limit. `OME-973` is closed; `OME-1011` drops `design-session`.
- **`OME-967` is a degradation, not a blocker.** `correlation` is all-nullable, so a report
  without a trace id is weaker, not invalid. Until it lands, reports join on
  *(endpoint, approximate timestamp)* only.

## 1. Build order

```
OME-1005  scaffold + CI lane
└─► OME-1006  schema + caps
       │      └─► OME-1007  classification
       │             └─► OME-1008  persist + idempotency
       │                    └─► OME-1009  TicketSink port + QueueSink
       │                           └─► OME-1010  background retry
       │                                  └─► OME-1012  chart + release lane
       └─► OME-1011  identity + Turnstile + rate limit
              (parallel with 1007–1010; joins at OME-1012)
```

`OME-1011` runs in parallel with the `1007 → 1008 → 1009` chain: it needs only the scaffold
and the route from `OME-1006`. Everything else is a straight line, because each item edits
`create_app` and a shared route module.

**`OME-1012` depends on `OME-1010`, never the reverse.** The drafts produced a circular
dependency (`1010 ⇄ 1012`); it is broken in the `1010 → 1012` direction. `OME-1010`'s only
chart-shaped output is a values block, which `OME-1012` renders.

## 2. Frozen cross-ticket contracts

Everything in this section is a single-owner decision. An item that disagrees with it is
wrong, not negotiating. These exist because the drafting pass produced seven internally
coherent sections that contradicted each other at every seam — see §11.

### 2.1 Module paths — one owner each

| Module | Owner | Everyone else |
|---|---|---|
| `report_intake/core/problem.py` | `OME-1005` | **EDIT**, never re-create |
| `report_intake/core/problem_catalogue.py` | `OME-1006` | EDIT to add constructors |
| `report_intake/routes/health.py` | `OME-1005` | **never** grows a storage import |
| `report_intake/routes/ready.py` | `OME-1005` | **never** edited by anyone |
| `report_intake/routes/reports.py` | `OME-1006` | EDIT |
| `report_intake/config.py` | `OME-1005` | EDIT to add fields |
| `report_intake/main.py` | `OME-1005` | EDIT **as a diff**, never re-listed |

`main.py` is the one file every item touches. Each item's plan states its `create_app` change
as *"add X"*, never as a full re-listing of the function — a re-listing is what silently
dropped `include_router(ready.router)` in the draft pass.

### 2.2 The `TicketSink` port — one signature

```python
# report_intake/delivery/ports.py — OME-1009 owns this file
class TicketSink(Protocol):
    async def deliver(self, content: TicketContent) -> SinkResult: ...

SinkResult = Delivered | Queued          # Delivered carries ticket_id + ticket_url
class RetryableDeliveryError(Exception): ...
class PermanentDeliveryError(Exception): ...
```

**A sink receives `TicketContent` — already-rendered strings — and never a report object.**
This is the stronger security guarantee: an adapter cannot leak a payload it was never
handed. `PersistedReport` stays internal to the store and is never passed across this seam.
The error taxonomy lives in `delivery/ports.py`, not in a separate `delivery/errors.py`, so
there is exactly one place to look.

### 2.3 The `reports` table — one migration

`0001_initial` (`OME-1008`) is greenfield, so it carries every column any later item needs.
No item adds a migration for a column another item already knew about.

| Column | Notes |
|---|---|
| `ref` | PK, server-minted, never derived from client input |
| `idempotency_key` | unique, nullable |
| `payload` | validated, truncated report |
| `classification` | server verdict |
| `caller_email` | mesh only; nullable |
| `reply_to` | self-asserted; nullable |
| `delivery_state` | `pending` \| `queued` \| `delivered` \| `failed` |
| `attempts` | integer |
| `next_attempt_at` | NOT NULL, defaults to `created_at` at INSERT |
| `lease_expires_at` | NOT NULL, defaults to `created_at` at INSERT |
| `ticket_id`, `ticket_url` | nullable until delivered |
| `request_fingerprint` | for dedup diagnostics |
| `created_at`, `updated_at` | |

Two corrections the drafts needed:

- **`delivered_at` does not exist.** `updated_at` plus `delivery_state='delivered'` already
  carries the fact.
- **`queued` is a real state, not a NULL timestamp.** The drafts overloaded
  `next_attempt_at IS NULL` to mean "no further attempt is owed", which inverted between two
  items: every `QueueSink` success would have been retried six times and then alarmed as
  permanently failed, while `queue list` returned nothing and the queue was undrainable.
  A state is a state; a timestamp is a timestamp.

The column is `created_at`. Not `received_at`.

### 2.4 Environment surface — Settings is the sole authority

Every environment variable this service reads is a field on `report_intake.config.Settings`
with `env_prefix="REPORT_INTAKE_"`. The chart renders **exactly** this set and nothing else.

```
REPORT_INTAKE_HOST                     REPORT_INTAKE_AUTH_MODE          disabled | mesh_or_turnstile
REPORT_INTAKE_PORT                     REPORT_INTAKE_ALLOWED_NETWORKS
REPORT_INTAKE_LOG_LEVEL                REPORT_INTAKE_CORS_ORIGINS
REPORT_INTAKE_DATABASE_URL             REPORT_INTAKE_TRUST_CLIENT_IP_HEADER   default false
REPORT_INTAKE_TICKET_SINK              REPORT_INTAKE_TURNSTILE_SECRET         from a Secret
REPORT_INTAKE_DELIVERY_TIMEOUT_S       REPORT_INTAKE_TURNSTILE_VERIFY_URL
REPORT_INTAKE_IDEMPOTENCY_TTL_H        REPORT_INTAKE_TURNSTILE_TIMEOUT_S
REPORT_INTAKE_RETENTION_DAYS           REPORT_INTAKE_ANON_RATE_{LIMIT,WINDOW_S,MAX_KEYS,BURST}
FORWARDED_ALLOW_IPS                    (uvicorn's own; deliberately unprefixed — not a Settings field)
```

Names that appeared in the draft chart and **do not exist**: `IDENTITY_MODE`,
`TRUSTED_PROXY_NETWORKS`, `SINK`, `ANONYMOUS_ENABLED`, `TURNSTILE_ENABLED`,
`TURNSTILE_SITE_KEY`. The site key is a browser-side value this service never reads; rendering
it into the pod's environment is cargo cult.

Two enforcement mechanisms, because `extra="ignore"` makes every name mismatch silent and a
mismatch on `AUTH_MODE` means a production pod boots with **authentication disabled**:

1. **Startup guard** in `create_app`: scan `os.environ` for any `REPORT_INTAKE_*` key not in
   `Settings.model_fields` and raise `ValueError` naming it. Fail at boot, not at the first
   forged request.
2. **`verify_chart_wiring.py` assertion**: every `REPORT_INTAKE_*` key in the rendered
   ConfigMap resolves to a declared `Settings` field. This is the check that survives a
   future rename.

### 2.5 Readiness — one seam

`OME-1005` ships `routes/ready.py` backed by `app.state.readiness_check`. `OME-1008` changes
**one line** in `create_app` to install a real storage probe. Nobody adds a second `/readyz`,
and `routes/health.py` never imports the store — `/healthz` must answer even when the
database is gone, or one bad database becomes a cluster-wide restart loop.

### 2.6 Problem catalogue

`{400, 403, 413, 422, 429, 503}` — matching the spec's §2.3 table as amended (§12).

`403` and `503` are **not** interchangeable, and the split is the reason `403` exists at all:
`403` means the Turnstile token was missing or rejected, so the client fetches a fresh one;
`503` means siteverify was unreachable, so nothing was stored and the client retries
unchanged. One constructor each — `bot_gate_required()` and `bot_gate_unverifiable()` — and
neither is raised ad hoc at a route.
A new status means a new constructor in `problem_catalogue.py`; no item raises
`ProblemException` with an ad-hoc status at a route.

### 2.7 Classification seam

`OME-1006`'s `BoundedReport` carries a fourth field, `scanned: Mapping[str, Any]` — the
post-control-character-strip, **pre-truncation** mapping. It exists solely so `OME-1007` can
scan text that truncation would otherwise have removed, and it is never persisted. Both
objects are held for one request over a body already capped at 64 KiB.

`OME-1007` exports two entry points:

- `classify_report(document) -> Verdict` — the request-path classifier.
- `scan_text(text: str) -> str | None` — string-level detectors only, for `OME-1009`'s
  fail-closed re-check on a rendered ticket body.

`OME-1009` calls `scan_text`, never `classify_report`. Passing a rendered string to the
document classifier fails in the worst direction: it marks **every** report as content, so
no report is ever delivered, and the retry path is short-circuited as permanent.

## 3. OME-1005 — Scaffold `apps/report-intake` with its CI lane

**Pattern:** `apps/scoreboard` as the whole-app template — it is the cleanest of the three
Python apps. `pyrightconfig.json` copied byte-for-byte.

There is **no uv workspace** in this repo; every app is a standalone uv project with its own
lockfile and `.venv`, and every `uv` command runs with cwd = the app root.

- Distribution `report-intake`, import package `src/report_intake/`, console script
  `report-intake = "report_intake.cli:main"`.
- **Strict complexity tier** — `max-complexity = 8`, `max-statements = 26`, `max-branches = 7`,
  `max-returns = 3`, matching scoreboard and the engine. aigateway's looser numbers are an
  explicitly labelled Day-1 grandfathering of a pre-existing codebase; a greenfield app has
  no legacy to grandfather. Ship `docs/complexity-baseline.md` beside it, as the ruff comments
  point at that path.
- **`config.py` copies scoreboard, not aigateway.** Single `env_prefix`, plain field names.
  aigateway's dual-prefix `validation_alias` scheme is drift from a rename, not a pattern.
- **`NoDecode` on every list/tuple setting.** pydantic-settings JSON-decodes complex types
  from the environment, so `REPORT_INTAKE_ALLOWED_NETWORKS=10.0.0.0/8` fails as malformed
  JSON *before* any validator runs. Annotate `Annotated[tuple[...], NoDecode]` and split on
  commas in a `mode="before"` validator. Parse CIDRs with `strict=True` so a host-bits-set
  entry is refused rather than silently widened.
- **`logs.py` copies the engine's, not scoreboard's.** Scoreboard has the
  `logging.lastResort` bug — its records fall through to stderr message-only and its
  `SCOREBOARD_LOG_LEVEL` governs only uvicorn's loggers, never the app's. The engine wrote
  `logs.py` specifically to escape that trap. Call `configure()` from `create_app`, not only
  from `cli.main`, so a pod gets configured logging.
- **Fail-loud startup guards live in `create_app`, not in `Settings`** — cross-field checks
  and checks on env vars owned by someone else (`FORWARDED_ALLOW_IPS`). Every guard message
  names the exact variable, what would go wrong, and the fix.
- **No `lifespan=` yet.** An empty lifespan is the render-a-value-nothing-reads trap.
  `OME-1008` adds it with `db.py`.
- `/healthz` static; `/readyz` behind the `app.state.readiness_check` seam, failing closed
  until storage is wired.

**Registration** — the six-step new-component checklist: path-filtered
`.github/workflows/report-intake-tests.yml`, `CODEOWNERS`, `dependabot.yml`,
release-please entry, `CONTRIBUTING.md`, and the routing table in the
`working-in-this-repo` skill.

**Build the image in CI.** aigateway and scoreboard do not, and their Dockerfiles carry a
comment admitting it is a deploy-time surprise. A new app should not inherit a known defect.

## 4. OME-1006 — Report schema and hard caps

**Pattern:** RFC 9457 plumbing mirrored (not imported — apps never import each other's
internals) from the engine's `auth/problem.py`.

- Pydantic models for §2.1 exactly, including the **language-neutral** `client` block:
  `name`, `version`, `host`, `platform`, `runtime{name,version}`, `frontend{name,version}`,
  `user_agent`. No field names a language.
- **Unknown keys**: `extra="forbid"` at the top level; preserved verbatim inside `client` and
  `context`, counted against the depth and key-count caps, never interpreted.
- **Every row of the §2.4 caps table.** Truncate-and-mark for oversized individual strings;
  reject only on total body cap and structural violations. Traceback truncation keeps head
  **and** tail.
- **`X-User-Email` is not in the general header allowlist.** `read_allowed()` must not return
  it. It is named in exactly one module — `OME-1011`'s `mesh_identity` — and reached only
  after the peer check. Ship the structural test *now*, not with `OME-1011`: assert
  `"x-user-email"` appears in exactly one module and that `routes/reports.py` and
  `reports/store.py` contain no occurrence. Until `OME-1011` lands, `caller_email` is
  unconditionally `None`.
- A pre-routing body-limit middleware enforces the 64 KiB cap before parsing.

## 5. OME-1007 — Classify content server-side

**Pattern:** `apps/scoreboard/src/scoreboard/classification/openness.py` — the repo's one
fail-closed classifier.

- The server decides. Client-declared intent is not consulted.
- Scan for prompt text, model responses, cell source, log bodies, url4 expressions.
- Content present → `422`. Undeclared content is still content; **never fail open**.
- **No redact-and-accept.** Partial redaction of free text creates false confidence.
- **The `oversized-leaf` detector excludes `/client` and `/context`.** Those strings are
  governed by §2.4's truncate-and-mark, not by classification. Scoping it otherwise makes a
  300-byte `client.version` a `422`, directly contradicting the spec's normative caps table.
  Scope the detector to `/error/details` and `/error/cause`, where a large leaf really is a
  captured body.
- Export `scan_text` for `OME-1009`'s re-check (§2.7).

## 6. OME-1008 — Persist before deliver, idempotent replay

**Pattern:** scoreboard's `scores/store.py` for the 24 h idempotency window
(`IDEMPOTENCY_TTL`, `expires_at` filtering); the engine's reaper for the purge loop.

- `0001_initial` carries every column in §2.3.
- **Persist before deliver** is structural, not a convention: the record is committed before
  any sink is reachable.
- 24 h idempotency window: replay returns `200` with the original record; `202` for new.
- **90-day purge runs inside `_lifespan`**, never via `app.router.on_startup`. On the pinned
  fastapi 0.141.1 / starlette 1.3.1, passing `lifespan=` sets `Router.lifespan_context`
  directly — `router.startup()` is never called and an appended handler is dropped with no
  exception and no warning. Starlette 1.3.1 removed `on_startup` from `Router.__init__`
  entirely, so not even the deprecation warning survives. The purge would silently never run
  while every unit test calling `purge_expired()` directly still passed.
- **Dedup key design**: scoreboard's content-hash dedup returns *another run's* id
  (`OME-970`). The lesson is that a dedup key must identify the submission, not its content.
  Key on `Idempotency-Key` only; `request_fingerprint` is diagnostic, never authoritative.
- **Storage-down `503`.** `OME-1008` owns `StorePipeline`, replaces `OME-1006`'s
  `BindOnlyPipeline` in `create_app`, and maps `StorageUnavailable → storage_unavailable()`
  at the route. Ship the test the spec names: with the store patched to raise, `POST` returns
  `503` with `application/problem+json` and the table is empty. This is the one status that
  tells a client to fall back to disk, and the draft pass left it owned by nobody.
- `/readyz`: install the probe on the existing seam. Do not touch `routes/ready.py`.

## 7. OME-1009 — `TicketSink` port and `QueueSink`

**Pattern:** the engine's port/adapter/registry trio.

- Core defines the port; core never imports an adapter; wiring via registry.
- `QueueSink` marks the record `queued` for agent MCP filing during triage. No ticket id
  comes back — the spec's success shape already models this.
- **Ticket content:** envelope, `trace_id`, `ref`, note, `reply_to`, mesh caller email.
  **Never** prompt-bearing content. Linear is third-party SaaS; full bodies are permitted only
  in the Access-gated SigNoz sink.
- Inline delivery timeout **3 s** (the spec's number, not the draft's 10 s), after which the
  record stays `pending` and the response is still `202`.
- Fail-closed re-check on the rendered body via `scan_text` (§2.7).
- **`LinearSink` is a follow-up**, gated on `OME-976` *and* on a decision about where the
  credential lives and who rotates it. File it as an issue rather than leaving it implicit.

## 8. OME-1010 — Background retry

**Pattern:** the engine's sweeper/reaper — a pure policy object with an injected clock,
`sweep()` split from the loop so tests run with zero sleeping.

- Exponential backoff, 6 attempts, ~24 h total. The schedule
  `720 + 2160 + 6480 + 19440 + 57600 = 86400 s` is exactly 24 h.
- Due-scan is `delivery_state='pending'` only. `queued` is terminal-success and is never
  retried (§2.3).
- Terminal `failed` emits a metric or log line. A report we permanently failed to file is an
  operational event, not a shrug.
- Claim rows by conditional UPDATE with a lease, so `replicaCount > 1` cannot double-deliver.
- Retries must not stampede the sink's rate limits.

## 9. OME-1011 — Identity, Turnstile, rate limit

**Pattern:** aigateway's mesh-identity trio — `cloudflare_identity.py` (including the
IPv4-mapped-address handling), the peer recheck in `core/auth/admin.py`.

- `X-User-Email` honoured **only** when the peer is inside `allowed_networks` *and* Envoy
  injected it. Named in exactly one module.
- `reply_to` is self-asserted and is never identity.
- **Nothing is ever authorized by `trace_id` or `run_id`** (`OME-966`).
- Turnstile bot gate plus rate limit for anonymous callers; mesh-verified callers bypass.
- **CORS**: browser clients are first-class, JSON bodies preflight. Allow the real origins,
  allow `Content-Type` and `Idempotency-Key`, allow **no** credentials. The origin allowlist
  is not an authorization control.

Three corrections the drafts needed, all security-relevant:

- **`/healthz` and `/readyz` are exempt from the local-only middleware, unconditionally.**
  The aigateway middleware being copied gates *every* path and requires both a loopback peer
  and a loopback `Host` header. Kubelet dials the Pod IP, so a deployed pod would 403 its own
  liveness probe and CrashLoopBackOff — the exact failure mode the epic cites as the reason
  this service cannot live inside scoreboard. It would also break the CI image smoke test and
  the `helm test` pod.
- **The rate-limit key must not be attacker-controlled.** Trusting `CF-Connecting-IP`
  whenever the peer is inside `allowed_networks` means trusting it always, since Envoy is
  always the peer. Rotating the header yields a fresh bucket per request *and* evicts
  legitimate callers' windows from a capped key table. Default
  `REPORT_INTAKE_TRUST_CLIENT_IP_HEADER=false`, key on the TCP peer, strip `CF-Connecting-IP`
  at the edge alongside `X-User-Email`, and make key-table overflow **refuse-new-as-throttled**
  rather than evict-oldest, so filling the table fails closed.
- **The existing `client` fixture must be updated in the same change**, to
  `TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))`. Starlette's
  TestClient defaults to a non-loopback client and `http://testserver`, so introducing the
  local-only middleware without touching the fixture turns ~40 route tests red at once.
  aigateway has this exact workaround in its `conftest.py`.

## 10. OME-1012 — Chart, deployment wiring, release lane

**Pattern:** `apps/aigateway-ui/charts/aigateway-ui/` for layout; the `charts.yml` gate and
`verify_chart_wiring.py` for the assertions.

- **Two hostnames, not one.** Public intake hostname: no Access application, no
  SecurityPolicy, an *unconditional* `RequestHeaderModifier` removing `X-User-Email` and
  `CF-Connecting-IP`, Turnstile required. Identity hostname: Access application, fail-closed
  SecurityPolicy, `claimToHeaders` setting `X-User-Email`.

  The one-route alternative with `spec.jwt.optional: true` is a **full identity bypass**:
  with `optional: true` the JWT filter is skipped for a token-less request, so
  `claimToHeaders` never runs and a client-supplied `X-User-Email` reaches the backend
  untouched. Do not "simplify" the two routes back into one.
- **Default `anonymous.enabled: false` in `values.yaml`**, true only in `values-cloud.yaml`
  alongside `turnstile.enabled: true`. The draft defaulted anonymous on with Turnstile off,
  which trips the chart's own render-refusal guard — meaning `helm lint`, a bare
  `helm template`, and `verify_chart_wiring.py`'s default render all fail on a clean
  checkout. The predictable resolution under CI pressure is deleting the guard, which is the
  single render-time refusal protecting the repo's first unauthenticated write.
  Set `networkPolicy.enabled: false` explicitly for the same reason.
- Split liveness and readiness probes.
- ConfigMap renders §2.4's list mechanically and nothing else.
- Release lane for image and chart; add the chart to the `charts.yml` path filter.

## 11. Conflicts resolved from the drafting pass

Recorded so they are not re-introduced. Each was found independently by two or three
reviewers reading the repo rather than the drafts.

| # | Conflict | Resolution |
|---|---|---|
| 1 | RFC 9457 module at three import paths | `core/problem.py`, `OME-1005` owns (§2.1) |
| 2 | `TicketSink` declared three incompatible ways | `OME-1009`'s `TicketContent` signature (§2.2) |
| 3 | Chart env names ≠ Settings fields, silently dropped | Settings is authority + two enforcement checks (§2.4) |
| 4 | `/readyz` registered twice, one in the storage-free module | One seam, `OME-1005` owns (§2.5) |
| 5 | Chart defaults fail the chart's own guard | `anonymous.enabled: false` by default (§10) |
| 6 | `jwt.optional: true` vs two-route topology | Two routes; `optional: true` is an identity bypass (§10) |
| 7 | `next_attempt_at` / `delivered_at` used before they exist | All columns in `0001_initial`; no `delivered_at` (§2.3) |
| 8 | `next_attempt_at IS NULL` overloaded as a state | `queued` is a real `delivery_state` (§2.3) |
| 9 | Local-only middleware 403s `/healthz` → CrashLoop | Probes exempt unconditionally (§9) |
| 10 | Classifier fed a rendered string → 100% false positives | `scan_text` vs `classify_report` (§2.7) |
| 11 | `oversized-leaf` contradicts the §2.4 caps table | Detector excludes `/client` and `/context` (§5) |
| 12 | Sweeper on `on_startup` is a silent no-op | Start inside `_lifespan` (§6) |
| 13 | `X-User-Email` in the general header allowlist | One module only; structural test in `OME-1006` (§4) |
| 14 | Rate-limit key attacker-controlled | Don't trust `CF-Connecting-IP`; fail closed on overflow (§9) |
| 15 | Storage-down `503` owned by nobody | `OME-1008` owns `StorePipeline` + the test (§6) |
| 16 | `OME-1006` re-lists `create_app`, dropping `/readyz` | `main.py` changes stated as diffs (§2.1) |
| 17 | `OME-1010 ⇄ OME-1012` circular dependency | `1010 → 1012` only (§1) |
| 18 | Inline delivery timeout 3 s vs 10 s | 3 s, the spec's number (§7) |

## 12. Spec amendment — landed

`OME-1011` introduces **`403`** ("bot gate not satisfied"), which spec §2.3's table did not
list. The client SDK codes against that table, and an undocumented status is what turns
"my retry stopped working" into a support question.

**Amended on the `OME-1004` branch (PR #748, `a53f812a`).** §2.3 now carries the `403` row
and extends `503` to an unevaluable gate; §7 is rewritten around the two caller classes; §9
records both settled forks; §8 and §10 gain the matching rows. Nothing in this plan is
waiting on it.

Implementation still owes the code side: extend `PROBLEM_CATALOGUE` to
`{400, 403, 413, 422, 429, 503}` in the same change that adds `bot_gate_required()` and
`bot_gate_unverifiable()`, and update `OME-1006`'s catalogue-exactness test in that PR rather
than leaving it to redden.

## 13. Verification

- **Per item:** `uv run pytest`, `uv run ruff check`, `uv run pyright` green in
  `apps/report-intake`; behaviour-named tests in house style.
- **Chart:** `verify_chart_wiring.py` passes, including the new Settings-field assertion; a
  bare `helm template` with default values succeeds; `--set anonymous.enabled=true` with
  `turnstile.enabled=false` is refused.
- **Cross-item:** a forged `X-User-Email` from outside the mesh is not honoured; a report
  over the body cap is rejected with the cap named in the detail; a sink outage leaves a
  `202` intact with the record `pending`; storage down returns `503` and stores nothing;
  `/healthz` answers 200 from a non-loopback client in every auth mode.
- **End to end on a dev deploy:** submit a report anonymously through the public hostname
  with a Turnstile token, confirm the row, confirm `queue list` shows it, file it via MCP,
  confirm the ticket carries the envelope and no prompt-bearing content.

## 14. Out of scope

`LinearSink` (follow-up, gated on `OME-976`). The client-side report builder and notebook
widget — a separate epic on `py-screamingface`, gated on `OME-967`. Any bundle or blob store:
Class C content is rejected, not stored, which is what removes content-addressing, TTL
sweeps, and an Access-gated read surface from this service entirely.
