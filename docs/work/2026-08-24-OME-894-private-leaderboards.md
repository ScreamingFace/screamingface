---
ticket: OME-894
stack: scoreboard
status: in_progress
started: 2026-08-24
finished:
---

# OME-894 — Private leaderboards (HealthBench worst-30 first)

## Intent

HealthBench worst-30 is the public entry challenge, so its submissions must not be publicly
visible: staff see everyone's, participants see only their own. Implemented as a general
`Benchmark.visibility` capability rather than a special case, and enforced in the **API** across all
four read paths — the portal is static JavaScript against a public API, so hiding rows in the page
would leave `curl /v1/leaderboard/healthbench-worst30` serving everything.

Three of the four read paths leak today: the board, per-spec history, and the frontier aggregate.

## Owner decisions taken (2026-08-24)

- **D2 — fail closed under `auth_mode: "disabled"`.** No verified identity means nothing readable on
  a private board. No API escape hatch: tests and local dev already exercise the owner path through
  the real `cloudflare_headers` mechanism, so a hatch would buy nothing and would be one more
  setting whose misconfiguration publishes the challenge.
- **D3 — `rank` becomes `int | None`**, null on a private board.
- **D6 — staff access is a read-only operator module**, not an admin API.
- **D4 / D5 — answered by Irina on the ticket:** a private benchmark IS listed in the public
  catalogue and marked private; participants see no aggregate, nothing beyond their own submissions.

## Facts established before design

Full table in the spec (§2), verified against `origin/main` at `0b6a970c`. The three that drive it:

- **F3** — stored `submitted_by` keeps the full email; the local-part trim is a JSON-only
  serializer. So server-side ownership matching is exact, and no fuzzy matching is needed.
- **F5** — `_ranked_entry` splats one `extra="forbid"` DTO into another, so a field added to one and
  not the other is a runtime 500 on the read path, not a type error.
- **F7** — `auth_mode` defaults to `"disabled"`, the chart sets it, and `values-prod.yaml` does not
  override it. Under D2 that makes the private board readable by nobody through the API until infra
  enables `cloudflare_headers` (`OME-895`). Staff still have the D6 module. **The deployed value is
  not verifiable from this repo** (the platform team keeps its own values file, `OME-730`) — confirm
  with Stephen before the challenge is announced.

## Planned changes

Per `docs/plan/2026-08-24-OME-894-private-leaderboards.md`: regression guard → schema+migration →
optional read identity → store owner scoping → four read paths → staff operator module → close-out.

## Running deviations

1. **The read-identity dependency was split across two files, not the one the plan named.** The
   plan said `core/auth/read_identity.py`. The trust decision landed as a pure
   `optional_identity()` in `core/auth/cloudflare_identity.py` — free of FastAPI and of Settings,
   so it is testable without constructing a request — and only the adapter that lifts the four
   inputs off the request lives in `routes/dependencies.py`. Putting a `Request` import into
   `core/auth` would have coupled the port to the framework, which the existing module
   deliberately avoids by taking `Mapping[str, str]`.

## Test plan

The regression guard is written **first**, before any privacy behaviour exists, because the main
risk here is breaking the public board while securing the private one — not failing to hide the
private one.

Then per path: anonymous vs private, owner vs private, non-owner vs private; history 404 not 403;
frontier 404; no rank and no leading marks; the caller's non-registered-revision rows still listed
(D8); `disabled` mode yields nothing.

## Acceptance

See spec §7.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
