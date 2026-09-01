---
ticket: OME-1002
stack: python
status: done
started: 2026-08-26
finished: 2026-08-27
---

# OME-1002 — Apply the four-reviewer findings on report-intake

## Intent

Four independent reviewers read `apps/report-intake` after `OME-1005`–`OME-1012` landed on the
epic branch and returned 19 findings — three of them blockers. This unit applies the ones that
are right and records, with spec/plan citations, why the rest are not.

The three blockers are the ones that decide whether this service can be deployed at all:

1. The wire returns `delivery.state: "queued"`, a fourth state spec §2.2's enum does not carry,
   on **every** successful submission — so a typed SDK breaks on the happy path.
2. `Idempotency-Key` is a single global namespace on an unauthenticated write, so any caller who
   guesses a key another caller used is answered `200` with that caller's row — an enumeration
   leak in one direction and a silent report-suppression channel in the other.
3. `_bullets` interpolates client-controlled values into the ticket body with newlines intact, so
   a `trace_id` can forge a `## Reporter` section carrying a fabricated **mesh-verified caller**
   line above the real one — forged identity in the artifact a human acts on.

## Planned changes

- `src/report_intake/routes/reports.py` — map storage `queued` → wire `pending` at the response
  boundary; bound `Idempotency-Key` at the route; carry the dedup scope from `admit`.
- `src/report_intake/identity/gate.py` — `admit` returns `Admission(caller_email, dedup_scope)`.
- `src/report_intake/reports/pipeline.py` — `scoped_dedup_key()`; `Submission.dedup_key`.
- `src/report_intake/reports/schema.py` — `reply_to` bounded to the column width.
- `src/report_intake/reports/caps.py` — cap `error.cause` like its sibling; make `_cap_details`
  budget against the re-serialized wrapper.
- `src/report_intake/classification/content.py` — raise the oversized-leaf threshold to the cap
  §2.4 already truncates at.
- `src/report_intake/delivery/render.py` — a bullet is structurally one line.
- `src/report_intake/reports/store_pipeline.py` — log the out-of-band truncation record.
- `src/report_intake/main.py` — boot guard tying `delivery_timeout_s` to `CLAIM_GRACE`.
- `charts/report-intake/values-cloud.yaml`, `templates/_helpers.tpl`,
  `templates/httproute-{public,identity}.yaml`, `values.yaml`, `README.md` — cloud posture.
- `.github/dependabot-ignores.yml`, `.github/workflows/charts.yml`,
  `.github/scripts/verify_chart_wiring.py` — registration and gate coverage.
- `charts/report-intake/templates/httproute-{public,identity}.yaml` — publish `/v1/reports` only.
- Tests for every behavioural change.

## Test plan

- A successful submission answers a `delivery.state` spec §2.2's enum lists.
- An over-long `Idempotency-Key` is `400`, not `503`, and stores nothing; the boundary length is
  still accepted.
- An over-long `reply_to` is `422` naming the field, not `503`, and stores nothing.
- Two callers sending the same literal `Idempotency-Key` get two different `ref`s.
- A `trace_id` carrying `\n## Reporter` renders as one bullet, and the body carries exactly one
  `mesh-verified caller` line.
- A capped `error.details` re-serializes inside `ERROR_DETAILS_BYTES`; `error.cause` is capped
  the same way.
- The 1500-byte `reason` in spec §2.1's own documented `cause` shape is accepted.
- `create_app` refuses a `delivery_timeout_s` that outlasts the sweeper's claim grace.
- The dispatcher-sharing test asserts identity in both directions.
- Both HTTPRoutes publish only the write endpoint.

## Acceptance

- Every finding either applied with a test, or rejected against a spec/plan citation.
- `uv run pytest -q`, `uv run ruff check`, `uv run pyright` green in `apps/report-intake`.
- `uv run .claude/scripts/audit_dependabot_ignores.py --offline` reports no drift.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `charts/report-intake/templates/httproute-{public,identity}.yaml`
  (scope both routes to `/v1/reports`), `charts/report-intake/templates/networkpolicy.yaml` (the
  comment claiming the policy is "hardening and not the authentication boundary" was backwards for
  the cloud posture), and `tests/unit/test_ticket_render.py` (see Deviations).
- **Commits:** one on `OME-1002-report-intake-service`; sha recorded in the Linear close comment
  after squash-merge.
- **Applied, 16 of 19.** Three rejected against spec/plan citations, recorded below.
- **The cloud posture was the real finding, and two reviewers reached it independently.** Every
  value `values-cloud.yaml` could not know shipped empty and forced by a `required`/`fail` —
  except the two that decide who may forge `X-User-Email`. `config.allowedNetworks` shipped
  blanket RFC1918 + CGNAT, and `networkPolicy.enabled` shipped `false`. Both render, install, and
  work, which is exactly why nobody would ever have narrowed them: the peer check authenticates a
  *network*, the Service is a plain ClusterIP, and the HTTPRoute header-strip covers only traffic
  that goes through the edge. Both are now empty-and-required, with a fourth `report-intake.validate`
  refusal for the one an operator can still turn off (`networkPolicy.acknowledgeUnrestricted`).
- **`/healthz` and `/readyz` were published on the Access-free hostname.** Both routes matched
  `PathPrefix: /`. Neither probe is gated (spec §7: the bot gate never gates liveness) or
  rate-limited, and `/readyz` runs `Report.all().limit(1).exists()` per request — one unbudgeted
  database query per anonymous HTTP request, at the one endpoint deliberately outside the limiter.
  Removed at zero cost: the kubelet dials the Pod IP, `helm test` dials the Service.
- **Gates:** `uv run pytest -q` 438 passed; `uv run ruff check` clean; `uv run pyright` 0 errors.
  Beyond the three: `verify_chart_wiring.py` 75/75 (72 before, plus three new report-intake
  assertions), `helm lint` 0 failed, and
  `audit_dependabot_ignores.py --offline` reports no drift at 7 ignores / 7 entries (it printed
  `✗ UNDOCUMENTED /apps/report-intake python >=3.14` and exited 1 before the fix).
- **Deviations:**
  - `tests/unit/test_ticket_render.py::test_a_correlation_id_cannot_forge_a_section_of_its_own`
    was red on entry. It asserted `body.count("mesh-verified caller") == 1`, which the finding-9
    fix cannot satisfy and should not: `_one_line` *collapses* a bullet value, it does not redact
    it, because `dispatch.py`'s fail-closed re-check has to see what actually travels. Re-stated
    per LINE — exactly one `## Reporter` heading, exactly one `- mesh-verified caller:` bullet
    naming the real address, and every mention of the forged address confined to the trace-id
    bullet. That is the structural property; the substring count was a proxy for it that the
    correct fix fails.
  - Finding 6 asks to either trust `CF-Connecting-IP` or delete `trust_client_ip_header`. Both
    branches are foreclosed by frozen contracts (below), so the half that was genuinely missing was
    applied instead: spec §7 promises anonymous callers an edge rate limit and nothing provisioned
    one. The Cloudflare rate-limiting rule for `reports.screamingface.ai` is now a stated
    deployment prerequisite in the install snippet and the chart README.

### Rejected, with citations

- **11, part 2 (aggregate byte check under `/error/details` and `/error/cause`).** Part 1 — capping
  `cause` like its sibling — is applied and is the half that fixes the damage: measured, a
  50 × 960-byte marker-free `cause` inside a 48 805-byte body now stores 8 192 bytes with a
  `/error/cause` truncation mark, not 48 441. Part 2 would reject the whole node above
  `OVERSIZED_LEAF_BYTES`, which now equals `ERROR_DETAILS_BYTES` after finding 4 — so it would
  turn every oversized-but-ordinary `details` object into a `422`, which is precisely §2.4's
  *truncate, mark* row and precisely plan §11 conflict 11 ("`oversized-leaf` contradicts the §2.4
  caps table"), re-introduced one level up. The reviewer wrote it against the old 1 KiB threshold.
  What survives of `_oversized_leaf` is the claim it can actually make: a *single* leaf larger than
  the whole node is allowed to be is not a diagnostic field. Chunked text no longer buys more
  storage than one legitimate `details` object does.
- **6(a) — stop stripping `CF-Connecting-IP` on the public route and set
  `trustClientIpHeader: true`.** Spec §7 is explicit: "strip inbound copies of `CF-Connecting-IP`
  at the edge alongside `X-User-Email`". Plan §9 repeats it and §11 conflict 14 records it as a
  resolved conflict. Not negotiable at implementation.
- **6(b) — delete `trust_client_ip_header` and `CLIENT_IP_HEADER` as unreachable.** Plan §2.4
  freezes the environment surface and lists `REPORT_INTAKE_TRUST_CLIENT_IP_HEADER   default false`
  in it; §2.4 also makes `Settings` the sole authority, with the chart rendering exactly that set.
  Removing a field would break the `verify_chart_wiring.py` and `test_chart_environment.py`
  equalities in the direction they exist to catch. It is also not dead in general — it fails
  closed, is guarded twice (operator opt-in *and* a mesh peer), and this chart is not the only way
  the image is run. What was dead was the promise it stands in for, which is now documented.

---

## 2026-08-27 — second review pass (nine findings on the same branch)

A fifth reviewer read the branch after the round above landed and returned nine findings, four of
them on paths `OME-1009`/`OME-1010`/`OME-1012` added. All nine were applied; one was applied at a
different line than the reviewer named, and one deeper defect was found while confirming it.

### Applied

1. **`LinearSink` ruled on the HTTP status to completion before the body was ever decoded**, so the
   module's own documented retryable path — "a GraphQL `extensions.code` naming a rate limit or a
   server error" — was unreachable for every status except `200`. `HTTP 400` +
   `{"errors":[{"extensions":{"code":"RATELIMITED"}}]}` was PERMANENT with the `errors` array never
   opened, which marks the row `failed`, and `OME-1010`'s sweep never re-attempts a `failed` row: a
   dropped bug report with the reporter already told `202`. `deliver` now decides `401`/`403` and
   the retryable statuses on the status alone (no body is needed to know a credential was refused)
   and reads the body before ruling on anything else. Reading the body may only ever RESCUE a
   status: `_decoded_or_nothing` returns `{}` for a body it cannot decode, so an HTML-bodied `404`
   keeps its permanent verdict exactly as before.
2. **`queue show` was a second, unguarded road from a stored report to a ticket body.** It rendered
   through `render_ticket` and printed `content.body` verbatim with no `scan_text`, while
   `delivery/dispatch.py` runs a fail-closed check on that identical string. The gap is real and
   not theoretical: `error.traceback` opening with ONE newline passes `classify_report` at the
   route, `render._fenced` supplies the second, and the marker exists for the first time in the
   rendered body — so the sink refuses it, the row goes `failed`, and the command whose whole job
   is moving bodies into Linear printed it under `title:`. `dispatch._content_in` is now public
   (`content_in`) and `queue_cli._printable` calls it rather than re-implementing it. Refused, never
   redacted: the docstring's "verbatim" is now "verbatim or nothing".
3. **`Idempotency-Key` was still a cross-caller lookup for anonymous callers.** `gate.admit` scopes
   them by `rate_limit_key`, which is the TCP peer — and in the cluster the mesh proxy is the peer
   on every request while `httproute-public.yaml` strips `CF-Connecting-IP`, so one scope covers
   the whole internet. The round above fixed this only for the mesh-verified class. With a sink
   that files tickets the leak now also hands an anonymous caller a private Linear issue url, and
   pre-registering a common key (`1`, `retry-1`) suppresses a real reporter's report silently.
   `scoped_dedup_key` now takes `unverified_payload` — REQUIRED keyword, so no caller omits it by
   forgetting — and mixes the payload digest in when `caller_email is None`. Spec §5 is untouched:
   a double-click and a client retry send the same bytes and still resolve to one row and one
   ticket; a guessed key from a stranger matches nothing. `request_fingerprint` moved from
   `store.py` to `pipeline.py` (both callers are submission-identity, and `store` imports it back)
   rather than being written twice.
4. **An over-wide ticket reference was an unbounded duplicate-issue loop, not an error.** Tortoise
   validates `max_length` at `save` (confirmed by probe: `ValidationError ticket_id: Length … 94 >
   64`), every ORM failure leaves the store as `StorageUnavailable`, and BOTH writers swallow that
   by design — the report is durable and an unrecordable outcome must not turn a `202` into a
   `503`. The row therefore kept `delivery_state='pending'` with `attempts` at zero, and `attempts`
   is the retry budget's only input: the sweep re-claims it every five minutes for the whole 90-day
   retention window, filing a fresh issue each pass, never reaching `MAX_ATTEMPTS`, alarming
   nothing. Closed at both ends — `LinearSink._raise_for_unstorable_reference` refuses before the
   write (permanent, same reasoning as the unnameable-issue branch) and `ReportStore._record_delivery`
   clamps at it so no future sink can reopen it. The widths are now `TICKET_ID_MAX_LENGTH` /
   `TICKET_URL_MAX_LENGTH` on the model, imported by all three callers instead of restated.
5. **The migration Job rendered no `imagePullSecrets`.** `apps/scoreboard`'s job-migrate.yaml has
   the block in exactly that position; report-intake had it on the Deployment only. GHCR org
   packages are private by default and this Job is a `pre-install` hook at weight `-5`, so a
   private-registry install blocked the entire release at ImagePullBackOff before any Pod was
   scheduled.
6. **`init_db` sat outside the guard that maps storage failure onto `EXIT_STORAGE`** — see
   Corrections for where the failure actually surfaces.
7. **An empty `linear.existingSecret` rendered `secretKeyRef: {name: ""}`.** Legal at every layer
   (values.schema.json gives it no `minLength` on purpose, `verify_chart_wiring.py` itself sets it
   empty) and rejected by Kubernetes at APPLY — `optional: true` does not exempt `name` — after
   helm has already run the migration hook. The entry is now guarded on a non-empty name. The
   `ticketSink=linear` refusal is unchanged and still fires first, so the message naming rule 9
   still wins.
8. **`cli.py`'s entrypoint-subcommand tree diverges from this repo's precedent**, and diverged
   silently. `apps/scoreboard` keeps `cli:main` a bare uvicorn launcher and ships operator commands
   as `python -m scoreboard.seed` / `python -m scoreboard.retire_benchmark`, which makes "a
   subcommand made mandatory here breaks every pod in the fleet" structurally impossible instead of
   a property defended by an optional `add_subparsers()`. Kept the subcommand shape — plan §13
   writes the verification step as `queue list`, the image's `ENTRYPOINT` is already this script so
   `python -m` is the longer spelling of the same thing, and two tests pin the entrypoint — and the
   module docstring now states the departure, names the precedent, and names the two tests the
   extra risk was traded for. **This is the recorded deviation for `OME-1009`'s CLI shape.**
9. **The GitHub Release body said `values-cloud.yaml` needs "five" install-time values.** Measured
   against the chart it is eight, six of which stop the render; `DEPLOYMENT.md` and `charts.yml`
   were both corrected to eight in the round above and this lane's own `Render` step already passes
   eight `--set` keys. The note omitted `config.allowedNetworks` and `networkPolicy.clientPodNames`
   — the two that decide who may forge `X-User-Email` — and called `database.existingSecret` a
   refusal when it silently defaults. It is the one artefact a downstream installer reads without
   opening the repo. Both places corrected, and the count is now asserted rather than written:
   `verify_chart_wiring.py` compares the prose count word against the `--set` keys the same lane
   passes.

### Corrections to the findings as written

- **Finding 6 named the wrong line, and the real defect is larger.** `Tortoise.init` is LAZY for
  asyncpg — probed: `init_db("postgres://u:p@127.0.0.1:1/…")` returns cleanly. The connection is
  attempted at the first query, where it raises `ConnectionRefusedError`. That is an `OSError`, and
  `ReportStore._STORAGE_FAILURES` was `(BaseORMException, RuntimeError, TimeoutError)` — so it
  escaped the store untouched. In the console that was the traceback and exit `1` the reviewer saw;
  **on the HTTP path it was a `500` where spec §2.3 and §8 promise the one status meaning nothing
  was stored.** Fixed at the source: `_STORAGE_FAILURES` now carries `OSError` (which subsumes the
  `TimeoutError` it used to name — the builtin has been an `OSError` subclass since 3.3, so
  `STORAGE_TIMEOUT_S` is still covered), and `queue_cli` guards the same three types with `init_db`
  inside the guarded region as belt and braces.
- **Finding 3's `caller_email is None` test was kept, its placement was not.** The digest is
  narrowed inside `scoped_dedup_key` rather than at the route so the rule cannot be forgotten by a
  future second caller; the route only decides which caller class it is holding.

### Tests added

Twelve functions, fifteen cases with parametrization, all behaviour-named:

- `test_a_rate_limit_linear_spells_with_a_status_and_a_code_is_still_retried_not_failed`
- `test_a_4xx_whose_body_names_nothing_transient_stays_permanent`
- `test_a_4xx_with_a_body_this_adapter_cannot_read_keeps_the_status_verdict`
- `test_a_refused_credential_is_permanent_even_when_the_body_names_a_rate_limit`
- `test_a_ticket_reference_wider_than_its_column_is_permanent_not_a_second_issue`
- `test_a_ticket_reference_wider_than_its_column_is_recorded_clamped_not_left_pending`
- `test_a_database_that_was_never_reached_is_a_storage_failure_like_any_other`
- `test_a_report_the_sink_refused_as_content_is_refused_by_show_too_not_printed_for_pasting`
  (with `test_a_report_the_sink_would_accept_is_still_printed_in_full` as its other side)
- `test_a_database_that_cannot_be_reached_is_exit_3_not_the_code_a_mistyped_ref_gets`
- `test_a_caller_with_no_verified_identity_has_its_key_bound_to_the_report_it_sent`
  (with `test_the_same_report_replayed_under_one_key_still_resolves_to_one_row`)

Plus three chart assertions in `verify_chart_wiring.py`: the empty-secret render, `imagePullSecrets`
on every pod-carrying object, and the release-lane count word.

### Gates (2026-08-27)

- `uv run pytest -q` — **549 passed** (534 on entry, of which one was the route test whose call
  signature this pass changed; +12 new functions / 15 cases).
- `uv run ruff check` — clean. `uv run ruff format --check` — 88 files already formatted.
- `uv run pyright` — 0 errors, 0 warnings.
- `python3 .github/scripts/verify_chart_wiring.py` — **89/89** (86 on entry, plus the three above).
  The `75/75` in the round above was the count before `OME-1012`'s later chart assertions landed.
- `helm lint charts/report-intake` — 0 failed.

### Rejected

None. All nine findings were real; two were applied at a different line than the finding named,
which is recorded above rather than filed as a rejection.

### Confidence-Gate decision — five prior tests modified (owner, 2026-08-27)

`run_gates.py`'s append-only check failed: `test_chart_environment.py`, `test_cli.py`,
`test_config.py`, `test_reports_route.py` and `test_ticket_sinks.py` all carry edits to tests
written in an earlier cycle. SDLC rule 5 makes that a Confidence-Gate decision rather than
something an implementer settles, so it was put to the owner with the diffs and **approved**.

**Nothing was weakened.** Assertion deltas across the five files: `-4` removed, `+29` added.
Every removal is forced by a signature change rather than chosen:

- `build_sink(name: str)` became `build_sink(settings: Settings)`, because an adapter that talks
  to a third party needs credentials and the registry is the one module allowed to know which
  fields carry them. `build_sink("  Queue ")` cannot compile against the new signature.
- `test_an_unknown_sink_name_is_refused_naming_the_ones_that_exist` used `"linear"` as its
  example of a name nobody implements. `linear` now exists, so the case moved to `"jira"` — and
  gained `assert "linear" in str(raised.value)`, which is strictly stronger than what it replaced.
- `test_the_two_secret_valued_settings_are_never_in_the_configmap` became `..._three_...`: the
  Linear API key is the third credential that must never reach a ConfigMap.
- `test_the_idempotency_key_reaches_the_pipeline_scoped_to_its_caller` changed because
  `scoped_dedup_key` gained `unverified_payload`. See below — this one is not cosmetic.

**The dedup-key correction is the reason this pass mattered.** The earlier round recorded
"Idempotency-Key scoped to the caller" as closing a blocker. It did not close it for anonymous
callers: on the public route the peer is the mesh proxy on **every** request and
`CF-Connecting-IP` is stripped at the edge, so one scope covers the entire internet. A stranger
sending `Idempotency-Key: 1` was answered `200` with the previous caller's record. Binding the
digest to the report's own bytes is what actually separates them, and
`test_the_same_report_replayed_under_one_key_still_resolves_to_one_row` pins the half that must
survive: a double-click and a client retry send identical bytes and must still be one report.

Adding `LinearSink` is what turned this from untidy into a leak. Under `QueueSink` the replay
returns an opaque `ref`; with a sink that files real tickets it returns the other caller's
private Linear issue URL. A latent flaw in one module was escalated by a change in another, and
only a reviewer holding both at once would see it.
