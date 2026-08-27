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
