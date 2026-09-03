# report-intake Guardrails

The full picture — what each endpoint does, the caps table, the retry schedule, the chart — is
`README.md` beside this file. What follows is only the set of things an edit must not break, and
the traps that have already been paid for once.

Spec: `docs/spec/2026-08-26-OME-1004-report-intake-service.md`. Plan (its §2 is the frozen
cross-ticket contracts): `docs/plan/2026-08-26-OME-1002-report-intake-implementation.md`.

## Contracts

- **`Settings` is the sole authority on this service's environment, and the chart renders exactly
  its fields.** Every variable this service reads is a `REPORT_INTAKE_*` field on
  `config.Settings`; a new field and its reader land together, never one without the other.
  `extra="ignore"` makes every name mismatch silent — a chart rendering `..._IDENTITY_MODE` at a
  field called `auth_mode` boots happily with the DEFAULT posture — so both directions are
  enforced: `create_app` refuses to start on a `REPORT_INTAKE_*` name no field reads, and the
  chart-vs-`Settings` equality is asserted from both sides in `tests/unit/test_chart_environment.py`
  and `.github/scripts/verify_chart_wiring.py`. Adding a field means editing the chart in the same
  change. `FORWARDED_ALLOW_IPS` is the one name this service cares about that is deliberately not
  a field — it is uvicorn's, and `main.py` guards the relationship rather than reading it as config.
- **`X-User-Email` is named in exactly one module** (`identity/mesh_identity.py`) and the peer is
  checked BEFORE the header is read. It is a plain header: anyone who can reach the port can send
  one, and the trust is a property of the network, not of the code. `core/headers.read_allowed()`
  must never return it, and `tests/unit/test_mesh_header_containment.py` fails the build if a
  second module names it. The same rule holds for `Cf-Turnstile-Response` and `CF-Connecting-IP` —
  each is read once, by the module that evaluates it. Every additional reader is another place
  that has to repeat both conditions, and the one that forgets looks exactly like the ones that do
  not.
- **Core never imports an adapter.** `delivery/ports.py` defines `TicketSink`; `create_app` asks
  `delivery/registry.build_sink(settings)` for a sink by NAME and does not know `QueueSink` or
  `LinearSink` exists. Shutdown closes it through `close_sink`, which is a structural `Protocol`
  check and never an `isinstance` against an adapter class. Adding an adapter is one file plus one
  line in `SINKS` — never an import in `main.py`, and never a credential read outside the registry.
- **A sink is handed `TicketContent` — already-rendered strings — and never a report object.**
  That is the strong form of the §4 content rule: an adapter cannot leak a payload it was never
  handed. `PersistedReport` does not cross this seam. `delivery/render.py` is the one module that
  decides what leaves this service and it is an allow-list of named attributes, so `error.details`,
  `error.cause` and the unknown keys `client`/`context` preserve are excluded BY NAME rather than
  by guessing which values look like secrets.
- **Persist before deliver.** `StorePipeline.submit` commits the row and only then can reach the
  dispatcher — enforced by the call graph, not by a comment. A delivery failure is never a request
  failure: everything the dispatcher can answer is a `DeliveryOutcome`, and a `pending` row with a
  `202` is the honest answer for a report whose ticket does not exist yet. `503` is the one status
  that means *nothing was stored*. Calling the sink first and storing on success is the most common
  way a service like this drops reports and is prohibited here.
- **`StorePipeline` does not classify.** Spec §4 rejects content rather than storing it, and the
  only structural guarantee of that is that the refusal happens at the route, before anything
  capable of persisting is reachable. A classify call added to the pipeline is one edit away from
  persist-then-classify.
- **`/healthz` never touches storage, settings, or anything else.** A liveness probe that can fail
  for an external reason turns one bad database into a cluster-wide restart loop: every replica
  fails its kubelet probe at once and none can come back, because what they are waiting for is what
  they are being killed for. `/readyz` is the one that may fail closed, there is exactly one of it,
  and `routes/ready.py` is never edited — the seam is the single assignment to
  `app.state.readiness_check`.
- **The classifier is fail-closed and reads `scanned`, never `payload`.** `BoundedReport.scanned`
  is control-stripped but PRE-truncation; a classifier that only ever saw truncated text would make
  truncation the way to smuggle a prompt past the check. It does not consult what the client says
  it sent — undeclared content is still content — and there is no redact-and-accept. It also does
  not reject on size outside `/error/details` and `/error/cause`: everywhere else a long string has
  a cap, not a verdict, and a classifier that turned a 300-byte `client.version` into a `422` would
  contradict the caps table it exists to complement.
- **`delivery/dispatch.py` re-checks with `scan_text`, never `classify_report`.** The structural
  detectors are scoped by JSON pointer and a rendered body is one string, so handing it to
  `classify_report` marks EVERY report as content and nothing is ever delivered.
- **BOTH roads from a stored report to a ticket body run that re-check, and they run the SAME
  function.** `dispatch.content_in` is public and `queue_cli._printable` calls it; a body the sink
  refused is refused by `queue show` too, rather than printed under "what an agent pastes into
  Linear". The marker that makes this real exists only after rendering — `error.traceback` opening
  with one newline passes `classify_report`, and `render._fenced` supplies the second — so the
  route cannot stand in for it. Never redact instead of refusing, and never re-implement the check
  in the console: two spellings of a fail-closed check are two things to keep in step.
- **No status is raised ad hoc, and a `422` never echoes the value it rejected.** Every error comes
  from a constructor in `core/problem_catalogue.py`, whose catalogue is asserted to be exactly spec
  §2.3's set. `binding.py` reads pydantic's `loc` and `msg` by name and never serializes an error
  object whole; the classifier returns its own words and a bounded pointer, never the span it
  matched. The response is unauthenticated — quoting free text back over it is the leak this
  endpoint exists to avoid.
- **No client-controlled value reaches a rendered artifact as free-form Markdown.** Free text is
  fenced with a computed fence; anything rendered as a bullet or a table cell goes through
  `render.one_line`. A newline inside a `trace_id` otherwise forges a `## Reporter` section above
  the real one — and that section is the only place a triager sees who the mesh authenticated.
  Neither detector catches it: both look for prompt markers, not Markdown structure.
- **`reply_to` is accepted even when it is not an address, and the ticket says so.** Never add a
  syntax check: a `422` would lose the error, the traceback and the trace id over the one field
  nothing is authorized on. The existing `max_length` is a COLUMN-width refusal, not a precedent
  for a syntax one. `delivery/render.py` labels a value that does not look like an address; that
  label never rewrites or drops the value.
- **Nothing is ever authorized by `trace_id`, `run_id` or `Idempotency-Key`.** An id in a report is
  a claim, not a credential (`OME-966`), and the idempotency key is resolved per caller — plus,
  for a caller with no verified identity, per REPORT. The scope alone separates nobody on the
  public route: the peer is the mesh proxy on every request and `httproute-public.yaml` strips
  `CF-Connecting-IP`, so one scope covers the whole internet and a guessed key was still a bearer
  lookup for somebody else's `ref` (and, with a sink that files tickets, their private issue url).
  `scoped_dedup_key` mixes the payload digest in when `caller_email is None`, so a replay resolves
  only against a byte-identical submission. Spec §5 is untouched by that — a double-click and a
  client retry send the same bytes — and a mesh-verified caller keeps the plain scope.

## Traps already paid for

- **`main.py` has a `lifespan=`, so `app.router.on_startup` is a silent no-op** on the pinned
  starlette — `Router.lifespan_context` is set directly and `router.startup()` is never called. A
  background loop appended there never runs in production while its unit tests keep passing. Every
  startup task goes in `_lifespan`, and both loops are OWNED (a bare `create_task` is weakly
  referenced and can be collected mid-sweep).
- **`app.routes` is not the list of paths this app serves.** `include_router` is wrapped behind a
  delegating entry with no `path` and no `routes`, reaching the real ones only through
  `original_router`. A test that counts `/readyz` routes must flatten both shapes; written as
  `<= 1` the mistake is a permanently green test that could never see a duplicate.
- **`REPORT_INTAKE_DELIVERY_TIMEOUT_S` is coupled to `retry.CLAIM_GRACE`.** The inline attempt
  holds no lease, so raising the timeout far enough re-opens a window where a sweeper on another
  replica claims a report the request path is still delivering — one bug report, two tickets.
  `create_app` refuses to start on the bad relation; the unit test pins the DEFAULT only.
- **`0001_initial` carries every column and no later item has added a migration.** The table is
  greenfield exactly once; a migration for a column that one already knew about is how two
  deployments end up on different schemas for one release. There is no `delivered_at`, and `queued`
  is a real `delivery_state` rather than an absent timestamp — the drafts overloaded
  `next_attempt_at IS NULL` and it inverted between two items.
- **The retry sweep reads `pending` only.** `queued` is terminal SUCCESS — the row is in the queue
  for an agent to file — so a sweep that read it as "no attempt is scheduled" would re-deliver
  every filed report six times and then alarm on it.
- **`mark_filed` does not increment `attempts`.** That column is the retry backoff's only input and
  reads as how hard THIS SERVICE tried; a person filing a ticket by hand is not the sink having
  been called.
- **The three triage reads are console-only.** Spec §1 removed `GET /v1/reports/{ref}`, and
  `report-intake queue list|show|mark-filed` is not it under another name —
  `tests/unit/test_triage_read_containment.py` fails if a `routes/` module so much as mentions one.
  `report-intake` with no arguments still runs uvicorn byte for byte, because that is the
  container's `ENTRYPOINT` rather than a default.
- **`LinearSink` ships but is not selected**, and shipping it is not selecting it: `queue` is the
  default, nothing imports the adapter but one registry line, and `build_sink` refuses to boot a
  `linear` deployment missing a key or a team id. Selecting it is governed by repo CLAUDE.md rule 9
  (`OME-976` has not amended it) and is an owner decision, not an implementation one. Inside that
  adapter: **HTTP 200 is not success** — `errors` is read BEFORE `data` and `success is not True`
  is a failure — and the API key never reaches a log record, a `repr` or an exception message,
  which is asserted rather than trusted.
- **The status is not ruled on before the body is read**, except for `401`/`403` and the retryable
  statuses, which need no body. One condition — a rate limit — is spelled two ways and Linear may
  send both at once: an `HTTP 400` carrying `extensions.code: RATELIMITED` was PERMANENT with the
  `errors` array never opened, and `failed` is a state `OME-1010`'s sweep never re-attempts.
  Reading the body may only ever RESCUE a status, never soften one — a body this adapter cannot
  decode leaves the status verdict exactly where it was.
- **A ticket reference wider than its column is refused before the write and clamped at it.** Both
  writers of `ticket_id`/`ticket_url` swallow `StorageUnavailable` by design, so tortoise's own
  `max_length` validator was an UNBOUNDED loop rather than an error: the row stayed `pending` with
  `attempts` at zero, `attempts` is the retry budget's only input, and every sweep filed another
  issue for the whole 90-day window. The widths live on the model (`TICKET_ID_MAX_LENGTH`,
  `TICKET_URL_MAX_LENGTH`) and are imported by the three callers, never restated.
- **`_STORAGE_FAILURES` includes `OSError`, and that is not tidiness.** `Tortoise.init` is lazy for
  asyncpg, so an unreachable Postgres is not a startup failure — it surfaces at the FIRST query as
  `ConnectionRefusedError`, which is no `BaseORMException`. Escaping the store it was a `500`, and
  spec §8 gives a client exactly one status meaning *nothing was stored*. `queue_cli._UNREACHABLE`
  guards the same types for the same reason, and `init_db` is inside that guard — outside it, an
  unreachable database exited `1`, the code a mistyped `ref` gets.
- **`auth_mode=disabled` is not "no auth", it is loopback-only**, and both halves are checked: a
  loopback peer AND a loopback `Host`. The probes are exempt unconditionally — a kubelet dials the
  Pod IP, so a probe behind an auth check is a pod that fails its own liveness probe.
- **`403` and `503` on the bot gate are not interchangeable.** `403` means the token was missing or
  rejected, so the client fetches a fresh one; `503` means the gate could not be EVALUATED, so
  nothing was stored and the client retries unchanged. Collapsing them makes one of those two
  client behaviours wrong.
- **The rate limit runs before the bot gate**, and its key is the TCP peer. Verifying a token is an
  outbound request made on an anonymous caller's say-so; and trusting `CF-Connecting-IP` whenever
  the peer is inside `allowed_networks` means trusting it always, since the mesh proxy is the peer
  on every request. A full key table throttles rather than evicting — evict-oldest would make
  filling the table the way to clear somebody else's window.
- **Tests are behaviour-named and several of them are containment scans.** Never rename a test to
  something shorter and never weaken one to land a change: the header-containment, triage-read and
  chart-environment tests are the enforcement mechanism for three of the contracts above, and each
  fails in a direction that looks like a working deployment.
