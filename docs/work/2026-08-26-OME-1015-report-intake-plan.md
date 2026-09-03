---
ticket: OME-1015
stack: repo
status: in_progress
started: 2026-08-26
finished:
---

# OME-1015 — Plan the report-intake implementation

## Intent

Write the `docs/plan/` artifact for epic `OME-1002` — the hard prerequisite between the spec
(`OME-1004`, PR #748) and any code, per CLAUDE.md rule 3. Covers the seven fork-independent
sub-issues: `OME-1005` scaffold + CI lane, `OME-1006` schema + caps, `OME-1007`
classification, `OME-1008` persist-before-deliver + idempotency, `OME-1009` `TicketSink` port
+ `QueueSink`, `OME-1010` retry, `OME-1012` Helm chart + release lane.

The plan exists to answer questions the spec deliberately does not: build order, which house
pattern each item copies, and what the cross-item contracts are. The spec fixes *what the
service does*; the plan fixes *how it gets built here*.

## Owner decisions carried in (2026-08-26)

Three forks were settled before this unit started, so the plan is written against settled
ground rather than recording them as open:

- **Sink** — build the `TicketSink` port plus the rule-9-compliant `QueueSink`. `LinearSink`
  is a deferred follow-up gated on `OME-976`. Hexagonal isolation is what makes this cheap:
  the fork touches exactly one adapter.
- **Auth** — anonymous submission **is** admitted, with Turnstile and an edge rate limit.
  This resolves the `OME-973` fork toward anonymous and unblocks `OME-1011`.
- **Gate** — the plan pauses for owner approval in plain words before implementation starts.

## Planned changes

- `docs/plan/2026-08-26-OME-1002-report-intake-implementation.md` — the plan.
- This ledger.

## Test plan

Docs-only unit — no code, no tests. Verification is owner review against the acceptance list
on `OME-1015`, plus an internal check that every one of the seven items has a named house
pattern rather than a generic design.

## Acceptance

- All seven items planned, with build order and cross-item contracts explicit.
- Each item names the in-repo pattern it follows (`apps/aigateway` / `apps/scoreboard`
  structure, the path-filtered CI lane, `verify_chart_wiring.py`), not a generic design.
- The review spec's security constraints appear as plan constraints binding specific items:
  no `~/.screamingface/*`, no `Cf-Access-Token`, no run `topic`, no wholesale environment,
  allow-list named fields, never authorise on `trace_id` / `run_id`.
- The deferred `LinearSink` is named as a follow-up with its precondition, not omitted.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `docs/plan/2026-08-26-OME-1002-report-intake-implementation.md`
  plus this ledger.
- **Commits:** one docs-only commit on `OME-1015-report-intake-plan`; sha recorded in the
  Linear close comment after squash-merge.
- **Method:** a 15-agent workflow — 4 grounding sweeps over house conventions, 7 parallel
  ticket drafts, 3 adversarial critics (convention fidelity, spec completeness, security).
  2.64M subagent tokens, 34 min, 0 errors.
- **The critique pass is what earned the cost.** Seven agents drafting in parallel with no
  shared state produced seven internally coherent sections that contradicted each other at
  almost every seam: the RFC 9457 module at three import paths, the `TicketSink` port
  declared three incompatible ways, `/readyz` registered twice, chart env names matching no
  Settings field, and a circular `OME-1010 ⇄ OME-1012` dependency. Three critics found the
  same defects independently while reading the repo rather than the drafts. §2 of the plan
  (frozen cross-ticket contracts) exists specifically because of this, and §11 records all
  18 resolutions so they are not re-introduced.
- **Three defects would have shipped a broken service**, and all three fail in the safe-looking
  direction: (1) the chart renders env names no `Settings` field reads, and `extra="ignore"`
  drops them silently — a production pod configured for mesh auth boots with authentication
  disabled; (2) the copied local-only middleware gates `/healthz`, so a deployed pod 403s its
  own kubelet probe and CrashLoopBackOffs; (3) on the pinned starlette 1.3.1, registering the
  retention sweeper via `app.router.on_startup` alongside `lifespan=` is a silent no-op, so
  the 90-day purge never runs while every unit test still passes.
- **Gates:** docs-only; no stack gates apply. The ASCII dependency graph in §1 was generated
  and its alignment invariants asserted by script, not eyeballed. The retry schedule
  arithmetic was verified independently: 720+2160+6480+19440+57600 = 86400 s = 24 h exactly.
- **Deviations:** branched from `origin/main` at `451dc1a8`, so the report-intake spec
  (`docs/spec/2026-08-26-OME-1004-report-intake-service.md`, PR #748) and the observability
  review spec (PR #688) are both absent from this branch. The plan references them by path;
  the links resolve once those PRs merge.
