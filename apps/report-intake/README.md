# report-intake

Accepts an error report from a ScreamingFace client, persists it, and files it into the
private tracker. Its reason to exist is that a reporter should need no account of their own:
a researcher in a notebook can send a diagnosable bug report without a GitHub login, a Linear
seat, or an email we can verify.

Spec: `docs/spec/2026-08-26-OME-1004-report-intake-service.md`.
Implementation plan: `docs/plan/2026-08-26-OME-1002-report-intake-implementation.md`.
Epic: `OME-1002`.

## Run it

```bash
cd apps/report-intake
uv sync
uv run tortoise migrate                    # apply the schema; a second run is a no-op
uv run report-intake                       # http://127.0.0.1:9109
curl -sf http://127.0.0.1:9109/healthz
curl -sf http://127.0.0.1:9109/readyz      # 503 until the migration above has run
```

Out of the box that is `REPORT_INTAKE_AUTH_MODE=disabled`, which asks callers for nothing and
therefore **serves loopback only** — `curl` from another machine gets a `403`. The probes answer
regardless, from any peer.

**The service never migrates itself.** Auto-migrating at startup means every replica racing the
same DDL on a fresh database, and this service is deployed with more than one. Until the
migration has run, `/readyz` fails closed — which is the correct answer for a pod whose database
has no schema, and what keeps it out of the load balancer.

## Gates

```bash
uv run .claude/scripts/run_gates.py report-intake   # from the repo root
```

or, from here: `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`,
`uv run pytest`.

## What exists today

All of `OME-1002`. The scaffold (`OME-1005`), the report schema and its caps (`OME-1006`),
content classification (`OME-1007`), storage (`OME-1008`), delivery through the `TicketSink` port
(`OME-1009`), the background retry queue (`OME-1010`), identity, the bot gate, the rate limit and
CORS (`OME-1011`), and the Helm chart plus the release lane (`OME-1012`). The endpoint admits the
caller, accepts, bounds, classifies, **persists**, and attempts to file the report; a report the
sink could not take is retried until it lands or the budget runs out; and a `report-intake-v*` tag
publishes an image and a chart that deploy it.

`LinearSink` remains the one deliberate follow-up (spec §9), gated on `OME-976` and on a decision
about where that credential lives and who rotates it.

| Endpoint | Today |
|---|---|
| `POST /v1/reports` | validates, bounds, classifies, stores and files the report; `202` for a new one, `200` for an idempotent replay, `503` if nothing could be stored |
| `GET /healthz` | liveness, static, never touches storage |
| `GET /readyz` | readiness, answers from `app.state.readiness_check` — the `reports` table being queryable |

## Storage (spec §5)

One table, `reports`. The service has state, but it is a retry queue, not a document store.

- **Persist before deliver.** The row is committed before any sink is reachable, so a sink
  outage is a retry rather than a lost bug report. Calling the sink first and storing on success
  is prohibited here — it is the most common way a service like this drops reports.
- **Idempotency window: 24 h**, keyed on `Idempotency-Key` and on nothing else. A replay inside
  the window returns `200` with the original record; after it, the same key is a new report.
  `request_fingerprint` is written for diagnostics and never resolves a replay — the scoreboard
  deduplicates on a content hash, and `OME-970` is what that cost.
- **Row retention: 90 days**, purged from a loop the ASGI lifespan owns. Never register that
  loop on `app.router.on_startup`: with `lifespan=` set, the pinned starlette drops an appended
  handler with no exception and no warning, so the purge would never run in production while its
  unit tests kept passing.
- **`503` means nothing was stored.** It is the one status that tells a client to keep the
  report on disk and retry, rather than assume it was filed.

Caps are spec §2.4, in `reports/caps.py`. The split matters more than the numbers: **only the
total body cap and structural violations reject a report.** An oversized individual string is
truncated and marked, because a truncated report is worth more than no report — an oversized
`client.version` must not be the reason a user cannot file a bug. A traceback keeps its head
**and** its tail, because CPython renders the innermost frame last and V8 renders it first.

| Limit | Value | On breach |
|---|---|---|
| total body | 64 KiB | `413`, naming the cap |
| `note` / `error.message` / `error.details` | 4 / 8 / 8 KiB | truncate, mark |
| `error.traceback` | 32 KiB | truncate head **and** tail, mark |
| `notes[]` | 16 items | drop excess, record it |
| any `client` / `context` string | 256 B (`user_agent` 1 KiB) | truncate, mark |
| JSON depth / keys per object | 6 / 64 | `422` |

## Classification (spec §4)

**The server decides, and content is rejected rather than stored.** `classification/content.py`
scans the report for prompt text, model responses, cell source, log bodies and url4 expressions;
a hit is a `422` and nothing is persisted. There is no bundle store to put content in, no
redact-and-accept, and no consulting what the client says it sent — undeclared content is still
content. A responder who needs the prompt asks the reporter, which is what `reply_to` is for.

Two things the classifier deliberately does **not** do:

- **It does not reject on size outside `/error/details` and `/error/cause`.** Everywhere else a
  long string has a cap, not a verdict — a 300-byte `client.version` is truncated and marked, and
  a classifier that turned it into a `422` would contradict the caps table above.
- **It does not read `payload`.** It reads `BoundedReport.scanned`, which is control-stripped but
  **pre-truncation**. A classifier that only ever saw truncated text would make truncation a way
  to smuggle a prompt past the check — it survives into the report a human reads while the
  scanner sees the marker that replaced it.

`scan_text` is the string-level half, used for the fail-closed re-check of a rendered ticket body
in `delivery/dispatch.py`. The dispatcher calls that, never `classify_report`: a rendered body is
one string, and the structural detectors are scoped by JSON pointer, which a bare string has none
of. Handing one rendered string to `classify_report` marks **every** report as content, so nothing
is ever delivered.

## Identity and the bot gate (spec §7)

Two caller classes reach the same endpoint, and they are not two peers: in a deployment the mesh
proxy is the peer on **every** request, and the identity header is the only thing that tells them
apart. That is what plan §10's two-hostname topology produces — an identity hostname behind
Cloudflare Access whose Envoy route sets `X-User-Email`, and a public one that strips it.

| | Mesh-verified | Anonymous |
|---|---|---|
| gate | none — identity suffices | Turnstile (`403`) inside a rate limit (`429`) |
| `caller_email` | the mesh-injected address | `None` |
| content | rejected | rejected |

- **`X-User-Email` is honoured only after the peer check**, and it is named in exactly one module,
  `identity/mesh_identity.py`. The peer is checked FIRST, so a request from outside
  `REPORT_INTAKE_ALLOWED_NETWORKS` never has its claim read at all. The trust is a property of
  the network, not of the code: the header is forgeable by anyone who can reach the port.
- **`reply_to` is self-asserted and is never identity.** It matters more than it looks — the
  Python client parses only `exp` from its Access token, so it has no email of its own and an SDK
  report could not otherwise be answered.
- **Nothing is ever authorized by `trace_id` or `run_id`.** An id in a report is a claim, not a
  credential.
- **`403` and `503` are not interchangeable, and that is why `403` exists.** `403` means the
  Turnstile token was missing or rejected, so the client fetches a fresh one; `503` means the gate
  could not be *evaluated* — siteverify unreachable, too slow, unreadable, or rejecting **our**
  secret — so nothing was stored and the client retries unchanged. Collapsing them makes one of
  those two client behaviours wrong.
- **The rate limit runs before the bot gate.** Verifying a token is an outbound request this
  service makes on an anonymous caller's say-so; checking the budget first means a flood costs a
  dictionary lookup rather than a round trip to Cloudflare per request.
- **The rate-limit key is the TCP peer, and `CF-Connecting-IP` is not trusted by default.**
  Trusting it whenever the peer is inside `allowed_networks` means trusting it always, since the
  proxy is always the peer — a rotated header would then buy a fresh bucket per request. Read the
  consequence honestly: with the default key the anonymous budget is effectively **one bucket for
  all anonymous callers**. Per-caller limiting belongs at Cloudflare's edge, which can see the
  real client; this is the service-side backstop behind it.
- **A full key table throttles rather than evicting.** Evict-oldest would make filling the table
  the way to clear somebody else's window. The only entries ever dropped are buckets that have
  refilled to capacity, which release no budget — that is exactly what a first-time caller gets.
- **The probes are exempt from the loopback guard, unconditionally.** A kubelet dials the Pod IP,
  so a probe behind an auth check is a pod that fails its own liveness probe; the CI image job
  reaches the container through a published port and hits the same non-loopback peer.
- **CORS allows no credentials.** The origin allowlist decides which origins a browser will let
  read a response; it decides nothing about who may file a report. `REPORT_INTAKE_CORS_ORIGINS`
  is empty by default and no CORS middleware is installed at all when it is — an empty allowlist
  is not an allowlist of everything.

## Deploying it (spec §7, plan §10)

`charts/report-intake/` — see [its README](charts/report-intake/README.md) for the values. Three
things about the chart are properties of this service rather than of Helm:

- **Two hostnames, and it is not a simplification to merge them.** The identity hostname sits
  behind Cloudflare Access, and an Envoy `SecurityPolicy` re-verifies that assertion and SETS
  `X-User-Email` from the verified `email` claim; the public hostname has no Access at all and its
  route strips `X-User-Email` and `CF-Connecting-IP` unconditionally. One route with
  `spec.jwt.optional: true` is a **full identity bypass**: the JWT filter is skipped for a
  token-less request, so `claimToHeaders` never runs and a client-supplied header arrives intact —
  and since the peer is the mesh proxy, the in-process check believes it.
- **The chart renders exactly `Settings`' field set.** Both directions are asserted, in
  `tests/unit/test_chart_environment.py` here and against the rendered manifest in
  `.github/scripts/verify_chart_wiring.py`, because `extra="ignore"` makes a mismatch silent and
  `create_app`'s boot guard only fires once a real pod has already been scheduled.
- **A bare install is loopback-only, and that is the point.** `values.yaml` renders a pod with no
  edge and `authMode: disabled`, so `helm lint`, `helm template` and the wiring verifier are all
  green on a clean checkout — which is what keeps the chart's render-time refusals from being
  deleted the first time a default render goes red. The deployable posture is `values-cloud.yaml`.

`replicaCount > 1` is safe and needs a shared database: the retry sweep runs in every replica and
the conditional-UPDATE lease is what stops one bug report becoming two tickets, but the image's
default sqlite file is per-Pod. The schema comes from a `pre-install`/`pre-upgrade` Job, never
from the service itself.

## Delivery (spec §6)

`TicketSink` is a port. Core defines it (`delivery/ports.py`), core never imports an adapter, and
wiring happens through `delivery/registry.py` — `create_app` asks for `settings.ticket_sink` and
does not know `QueueSink` exists.

- **A sink is handed `TicketContent` — already-rendered strings — and never a report object.**
  That is the strong form of the §4 content rule: an adapter cannot leak a payload it was never
  handed, so the guarantee is a property of the port's signature rather than of a convention every
  future adapter is trusted to keep. `PersistedReport` does not cross this seam.
- **`delivery/render.py` is the one module that decides what leaves this service**, and it is an
  allow-list of named fields. `error.details` and `error.cause` do **not** travel — they are
  arbitrary client-shaped JSON — and neither do the unknown keys `client` and `context` preserve,
  which is what excludes an `api_key` a client dropped into an extension point structurally, by
  name, rather than by guessing which values look like secrets. Everything free-text is fenced
  with a computed fence, because a `note` is user prose and `## Error` inside one would otherwise
  forge a section heading.
- **`QueueSink` is v1, and it is not a placeholder.** The `reports` table *is* the queue: the row
  is marked `queued` and an agent files it via MCP during triage. That is what keeps a Linear API
  token out of this service's environment entirely. `LinearSink` is a follow-up gated on `OME-976`
  **and** on a decision about where that credential lives and who rotates it.
- **A sink never fails a reporter's request.** Delivery is attempted inline under a **3 s**
  deadline after the commit; a slow, dead or broken sink is a `pending` row and a `202`, not a
  `5xx`. Raising `REPORT_INTAKE_DELIVERY_TIMEOUT_S` does not make delivery likelier — it only
  makes filing a bug slower.
- **The two delivery errors mean different things**, and the split is the retry policy's only
  input: `RetryableDeliveryError` leaves the row `pending` for `OME-1010`'s sweep,
  `PermanentDeliveryError` leaves it `failed`, which is terminal and alarmed on. An adapter unsure
  which it is holding raises the retryable one.

## Retry (spec §6)

`reports/retry.py` is a policy object with the loop split off, exactly like the retention purge:
`sweep()` is one pass and does no waiting, `run()` is the forever-loop the ASGI lifespan owns.
Both loops start in `_lifespan` and nowhere else.

- **Six attempts across roughly 24 h**, the gaps being `720 + 2160 + 6480 + 19440 + 57600 s`, and
  then terminal `failed` with a log line — a report we permanently failed to file is an
  operational event, not a shrug. The budget counts **every** attempt including the inline one,
  because `attempts` is one column and an operator reading it has been told how hard the report
  was tried.
- **The due-scan reads `pending` only.** `queued` is terminal *success* — the row is in the queue
  for an agent to file — so a sweep that read it as "no attempt is scheduled" would re-deliver
  every filed report six times and then alarm on it.
- **Rows are claimed by a conditional UPDATE against `lease_expires_at`**, so the database
  arbitrates and `replicaCount > 1` cannot file one bug report as two tickets. The lease is also
  what makes a pod dying mid-attempt survivable: the row is claimable again once it expires.
- **A due row is left alone for `CLAIM_GRACE` first.** The inline attempt holds no lease — the
  row is committed `pending`, due at `created_at` and unleased, and only *then* is the sink
  called — so without the grace a sweeper on another replica would claim a report the request
  path is already delivering. That is the one door the lease does not cover.
- **The batch per interval is the rate limit, not the backoff.** A sink outage fails every row in
  the same sweep, which books all of their next attempts into the same instant; `BATCH_LIMIT`
  rows per `SWEEP_INTERVAL`, attempted one at a time, is a ceiling that holds whatever the
  backlog is.
- **A retry goes through the same `TicketDispatcher` the request path used**, re-validating
  `payload` into a `ReportDocument`. Not a second delivery path: same renderer, same fail-closed
  re-check, same deadline. A stored payload that no longer validates is terminal — five more
  attempts would re-read the same bytes — and its log line names the failing locations, never the
  value.

## Things that will bite you

- **`Settings` is the sole authority on this service's environment.** Every variable it reads
  is a field on `report_intake.config.Settings` with the `REPORT_INTAKE_` prefix, and the Helm
  chart renders exactly that set. `create_app` refuses to start on a `REPORT_INTAKE_*` name
  matching no field, because `extra="ignore"` would otherwise accept it, drop it, and run on
  the default — which for an auth-shaped setting means a pod serving with the wrong posture and
  no way to tell from the outside.
- **`FORWARDED_ALLOW_IPS` is the one name this service cares about that is *not* a `Settings`
  field.** It is uvicorn's, deliberately unprefixed. Setting `REPORT_INTAKE_ALLOWED_NETWORKS`
  makes `request.client.host` load-bearing, and uvicorn's proxy-headers middleware will rewrite
  that value from a client-supplied `X-Forwarded-For` for any peer inside
  `FORWARDED_ALLOW_IPS`. The two must be disjoint; `create_app` refuses to start otherwise.
- **`0001_initial` carries every column, and no later item has added a migration.** `attempts`,
  `next_attempt_at`, `lease_expires_at`, `ticket_id` and `ticket_url` are all written by
  `record_delivery`, the only writer of a delivery outcome. **The inline attempt counts and does
  not move the retry deadline**: it passes no `next_attempt_at`, so the row stays due at
  `created_at` and the sweep finds it, while the retry queue — the schedule's one owner — writes
  the outcome and the next deadline in a single statement. The table is greenfield exactly once;
  a later migration for a column this one already knew about is how two deployments end up on
  different schemas for one release. There is no `delivered_at` — `updated_at` plus
  `delivery_state='delivered'` already carries it — and `queued` is a real `delivery_state`,
  never an absent timestamp.
- **`/healthz` never grows a dependency.** A liveness probe that can fail for an external
  reason turns one bad database into a restart loop across every replica. `/readyz` is the one
  that may fail closed, and there is exactly one of it.
- **Nothing is ever authorized by `trace_id` or `run_id`.** An id in a report is a claim, not a
  credential.
- **`X-User-Email` is honoured only when the mesh injected it**, and it is named in exactly one
  module. Do not add it to a general header allowlist — `tests/unit/test_mesh_header_containment.py`
  fails the build if a second module names it, and `read_allowed()` must never return it. The same
  rule holds for `Cf-Turnstile-Response` and `CF-Connecting-IP`: each is read once, by the module
  that evaluates it.
- **`create_app` refuses to start a `mesh_or_turnstile` app that cannot run either half of its
  gate.** No `allowed_networks` and nothing can ever be mesh-verified; no `turnstile_secret` and
  siteverify rejects our own credentials, which this service correctly reads as an unevaluable
  gate — so every anonymous report is answered `503` while the pod reports itself healthy and
  ready. Both fail in the direction that looks like a working deployment.
- **`auth_mode=disabled` is not "no auth", it is loopback-only**, and both halves are checked: a
  loopback peer AND a loopback `Host`. The second is what stops a name resolving to 127.0.0.1
  from walking a browser into posting here from a page it loaded elsewhere.
- **No status is raised ad hoc.** Every error comes from a constructor in
  `core/problem_catalogue.py`, whose `PROBLEM_CATALOGUE` is asserted to be exactly the set spec
  §2.3 documents. An SDK switches on that table, and an undocumented status is what turns "my
  retry stopped working" into a support question.
- **A 422 never echoes the value it rejected.** Pydantic's error objects carry the offending
  input; `binding.py` reads `loc` and `msg` by name and never serializes one whole. The
  classifier holds the same rule from the other side: a detector returns its own words
  ("carries a chat transcript") and a bounded pointer, never the span it matched. Quoting free
  text back over an unauthenticated response is the leak this endpoint exists to avoid.
