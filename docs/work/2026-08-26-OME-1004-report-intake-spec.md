---
ticket: OME-1004
stack: repo
status: in_progress
started: 2026-08-26
finished:
---

# OME-1004 — Spec the report-intake service

## Intent

Write the design spec for `apps/report-intake` (epic `OME-1002`): a small FastAPI service
that accepts an error report from a ScreamingFace client, persists it, and files it into
the private Linear workspace so a reporter needs no account of their own. Spec before plan,
plan before code — no other item in the epic starts until this lands.

The API surface was narrowed during design review: two endpoints were proposed and both
pruned (`GET /v1/reports/{ref}`, `GET /v1/bundles/{id}`), leaving one real endpoint plus
two probes. That pruning is a load-bearing part of the spec, not trivia — dropping the
bundle store removed the entire storage layer for content.

## Planned changes

- `docs/spec/2026-08-26-OME-1004-report-intake-service.md` — the spec.
- This ledger.

## Test plan

Docs-only unit — no code, no tests. Verification is owner review against the ticket's
"must pin down" list, and the absence of any surviving "TBD".

## Acceptance

- The spec fixes the `POST /v1/reports` contract, the single success shape, the RFC 9457
  error catalogue, and **concrete numeric caps** (not "bounded").
- Classification is specified as a server-side decision that disbelieves the client.
- Persist-before-deliver, the data model, and idempotency semantics are unambiguous.
- The two unresolved forks (`OME-976` sink, `OME-973` auth) are recorded as open decisions
  with their consequences, rather than silently resolved by the author.
- A non-goals section carries the epic's scope guards.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — the spec plus this ledger.
- **Commits:** one docs-only commit on `OME-1004-report-intake-spec`; sha recorded in the
  Linear close comment after squash-merge.
- **Gates:** docs-only; no stack gates apply. Self-review run: no placeholders survive, the
  status codes used all appear in the error catalogue, and one real inconsistency was
  caught and fixed (`error.details` was bounded in the caps table but missing from the
  request schema).
- **Review round 1 (owner, 2026-08-26):** the `client` block was Python-shaped — a required
  `python` field, and a §2.1 sentence generalising the notebook's kernel-side posting rule
  into "never from a browser". Both were wrong for three of the four client surfaces
  (Studio/Electron, aigateway-ui/Next.js, portal/browser JS), and the second contradicted §7,
  which already treats aigateway-ui as the only client that knows its user's email. Fixed:
  `python` → `runtime {name, version}`; a surface→values table; documented-not-enforced
  vocabularies for `host`/`platform`/`runtime.name`; unknown-key policy split (forbid at top
  level, preserve inside `client`/`context`); a CORS paragraph the browser clients now
  require; caps rows for the new strings; head/tail truncation rationale made runtime-neutral
  (CPython renders the innermost frame last, V8 first). `error.traceback` is left named as-is
  and raised with the owner as the one remaining language-specific field name.
- **Deviations:** branched from `origin/main` at `5cba291b`, so the observability review
  spec (`docs/spec/2026-08-22-observability-traceability-review.md`, PR #688, still draft)
  is not present on this branch. This spec references it by path; the link resolves once
  #688 merges.
