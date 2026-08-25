---
ticket: OME-894
stack: scoreboard
status: in_review
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

## Test plan

The regression guard is written **first**, before any privacy behaviour exists, because the main
risk here is breaking the public board while securing the private one — not failing to hide the
private one.

Then per path: anonymous vs private, owner vs private, non-owner vs private; history 404 not 403;
frontier 404; no rank and no leading marks; the caller's non-registered-revision rows still listed
(D8); `disabled` mode yields nothing.

## Acceptance

See spec §7.

## Outcome

- **Actual files:** as planned, plus two beyond it — `routes/dependencies.py` (the adapter half of
  deviation 1) and `tests/unit/routes/` (a new package for it). 20 files, +1535/-21.
- **Commits:**
  - `05a2b0d8` docs(scoreboard): spec and plan private leaderboards
  - `f774e3ab` test(scoreboard): guard the public board against private-leaderboard work
  - `4bf2786f` feat(scoreboard): make visibility a property of a benchmark
  - `975f1d89` feat(scoreboard): resolve an optional caller identity on read paths
  - `42388fdf` feat(scoreboard): scope leaderboard reads to one owner
  - `b33ffef6` feat(scoreboard): enforce private benchmarks on every read path
  - `2a5d6fdb` feat(scoreboard): add a read-only export for reviewing a private board
- **Gates:** `run_gates.py scoreboard --base origin/main` green after **every** commit —
  append-only ✓, ruff check ✓, ruff format ✓, pyright ✓, pytest --cov=scoreboard
  --cov-fail-under=80 ✓, node --test portal ✓. No gate was skipped and no prior test was modified.
- **Verification beyond the suite:**
  - `tortoise makemigrations` reports no drift against `0008`.
  - **Public anonymous responses are additive-only.** Probed the pre-change shapes, then re-probed
    after: `visibility` added to the benchmark DTO, `scoped_to_caller` to the board response,
    **nothing removed**; entry, history and frontier shapes byte-identical; public rank still `1`,
    submitter still trimmed to its local part, public frontier still `200`.
  - **Real uvicorn run** (not ASGITransport) with `auth_mode: cloudflare_headers`, two seeded
    participants: anonymous private board `200 entries=[] scoped=True`; alice sees only
    `spec-alice` with `rank=None`; bob only `spec-bob`; own history `200`; another participant's
    history `404`; a nonexistent spec `404` with an **identical body**; frontier `404`; the public
    board unaffected at `scoped=False` and its frontier `200`.
  - **Staff export, invoked for real:** returned both participants with **full** addresses
    (`alice@example.test`, `bob@example.test`), and exits `2` on an unknown benchmark.
- **Deviations:** two, both recorded above and below.

## Deviations

1. **The read-identity dependency was split across two files, not the one the plan named.** The
   plan said `core/auth/read_identity.py`. The trust decision landed as a pure
   `optional_identity()` in `core/auth/cloudflare_identity.py` — free of FastAPI and of Settings,
   so it is testable without constructing a request — and only the adapter that lifts the four
   inputs off the request lives in `routes/dependencies.py`. Putting a `Request` import into
   `core/auth` would have coupled the port to the framework, which the existing module
   deliberately avoids by taking `Mapping[str, str]`.

2. **A private board 404s a NONEXISTENT spec too, which the ticket did not say.** The ticket
   specified 404-not-403 for another participant's spec, reasoning that a 403 confirms the spec
   exists. A public board answers an unknown spec with `200` and an empty list. Keeping that on a
   private board would have made "someone else's spec" distinguishable from "no such spec" by
   status code alone — re-opening the exact enumeration the 404-not-403 rule closes. Both cases
   now return the same 404 with the same body, pinned by a test.

## Owner-verify

- **Confirm the runtime `authMode` with @Stephen before the challenge is announced.** The chart
  ships `authMode: disabled` (`values.yaml:41`) and `values-prod.yaml` does not override it. Under
  D2 that leaves the private board readable by nobody through the API — staff use the export
  module, but *participants would not see their own rows*. The deployed value is not verifiable
  from this repo (`OME-730`).
- **Flipping HealthBench to private is a config change, not code:** set `visibility: private` on
  its `seedBenchmarks` entry and re-run the seed job. Nothing in this PR makes any existing board
  private.
- **Baselines stay visible on a private board** — imported LMArena / Artificial Analysis numbers
  are public third-party data, not participant submissions, and a participant needs the line to
  beat. This is the one call not covered by the ticket; say if it should be hidden instead.
- `OME-909` is still the missing half of the story: a participant now reliably *sees* their own
  row, including one measured against another revision, but nothing yet tells them why it would
  not rank.
