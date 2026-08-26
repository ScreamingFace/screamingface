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

## Review round — 2026-08-25

Five P1 findings on PR #719. Each was reproduced against the code before being acted on; all five
were valid. Decisions and reasoning are in spec §8 (D9–D12).

- **D9** migration adds nullable → backfills → tightens, with a mutation-checked test that applies
  it to a populated database through the real runner.
- **D10** deployment config owns `visibility` on Engine-published rows, and an omitted value means
  "leave it alone" rather than "reset to public".
- **D11** the submitter joins the dedup hash on private boards only; public identity is untouched.
- **D12** supersedes D3 — a private board carries no ranking, so `entries` is `[]` and the caller's
  rows move to `my_submissions`. `rank` goes back to a required `int`, which removes the
  cross-cutting SDK change, the epic, and the release ordering entirely.

Verified after the fixes: the migration applies to a populated database; a hand-set private board
survives both a bare re-seed and a full deploy seed, and the chart can still flip it back;
`GET /v1/scores/{id}` returns the same 404 for anonymous and non-owner callers; two participants
submitting an identical recipe on a private board each keep their own row; and **the unmodified
SDK decodes a private-board response** rather than raising. Public boards unchanged throughout.

**No prior test was modified.** `_content_hash`'s new argument defaults to `False` specifically so
the existing `test_content_hash_keys_on_the_submitted_score` keeps passing untouched.

## Review round 2 — 2026-08-25

Three findings, all reproduced first, all valid. Reasoning in spec §9 (D13–D15).

- **D13** deployment-declared visibility is applied to an existing row even when the Engine
  catalogue is down, and the deploy log names it. Previously a transient outage left the board
  public and exited zero.
- **D14** the idempotency key is namespaced by submitter on a private board. It is consulted
  before the content hash, so D11's per-submitter hash could not cover this.
- **D15** own rows come from `list_owned_entries`, not the ranking query, so a caller's earlier
  submission to the same spec is no longer dropped.

**Simplification that fell out of D15:** `leaderboard(owner=)` and `list_all_for_benchmark(owner=)`
lost their only caller and were removed, together with D8's revision-skip branch. The
"`owner=None` means unscoped" footgun is gone rather than guarded, and the ranking query is back to
the shape `OME-775` gave it. Three tests covering the removed parameters went with them; their
intent is carried by the `list_owned_entries` tests.

All three re-verified after fixing: two same-spec submissions both appear, a shared key no longer
crosses participants, and a catalogue-down deploy makes the board private and reports it.

## Review round 3 — 2026-08-25 (@HupBaHa, PR #719)

Four blockers, all reproduced before being acted on, all valid.

- **Forged writes were a read primitive.** Under `auth_mode=disabled` the body's `submitted_by` is
  trusted, so claiming a participant's address with a matching recipe returned their stored row —
  url4, metadata and id. Reproduced. The route now refuses writes to a private benchmark whenever
  authentication is disabled, **ahead of the store**, since refusing after the dedup lookup would
  still tell a forged request whether a matching row exists. Reads already failed closed in this
  mode (D2); writes now match, so a private board is inert in both directions rather than half-open.
- **The scoped idempotency key could not exist on PostgreSQL.** It joined submitter and key with a
  literal NUL, which SQLite accepts and PostgreSQL rejects — verified against `postgres:16` with
  `invalid byte sequence for encoding "UTF8": 0x00`. Every private submission carrying an
  `Idempotency-Key` would have failed only in production. Now a `sfp-`-prefixed sha256: 68
  printable ASCII characters, well inside the VARCHAR(255) column, with the separator surviving
  only inside the digest input.
- **The concurrent-retry branch used the unscoped key.** `_resolve_existing` was called with the
  raw `idempotency_key` in the `IntegrityError` handler, re-opening the cross-participant leak for
  exactly the concurrent case that branch exists to handle. It uses `stored_key` now.
- **Identity-scoped responses were shared-cacheable.** Private board, history, frontier and
  direct-score responses now carry `Cache-Control: private, no-store` and
  `Vary: X-User-Email, Origin`, refusals included — those are identity-dependent too, and
  replaying one participant's 404 to another would deny them their own history.

**A real PostgreSQL test now exists** (`tests/unit/scores/test_idempotency_postgres.py`). It opens
its own connection rather than using `tortoise_db`, because that fixture routes through
`postgres_schema_database_url`, which calls `asyncio.run()` inside a running loop and errors before
any test body runs — the known OME-430 defect, confirmed still live. Mutation-proven: restoring the
NUL separator fails it with the PostgreSQL error above.

Two things found while fixing rather than reported:

* My first PostgreSQL test called `Tortoise._drop_databases()` in cleanup, destroying the database
  and making the test non-repeatable — it would have broken a shared CI PostgreSQL. Caught when a
  mutation check could not reconnect. Cleanup is now scoped to the rows the test creates.
* `Benchmark.exists()` is kept as the existence gate rather than folded into the visibility read,
  because it is the seam `test_post_score_store_unavailable_returns_503` patches. That prior test
  is untouched.

## Review round 4 — 2026-08-26 (@HupBaHa, PR #719)

Two P1 findings remain after round 3.

- **Idempotency namespaces are now disjoint.** The reviewer's exact exploit was reproduced first:
  a public raw key equal to Alice's derived private key returned Alice's private row and metadata.
  `sfp-` is now reserved for server-derived private tokens; a public raw key attempting to occupy
  it is deterministically escaped to `sfu-<sha256>`. Ordinary public keys remain verbatim and
  globally replayable, preserving the existing contract and every prior test. Migration `0009`
  removes only legacy `sfp-` mappings at the format boundary; ordinary public mappings and all
  score rows survive, proven through the real migration runner.
- **The PostgreSQL regression is isolated without rewriting it.** The repository's append-only
  gate correctly rejected the first narrow-row rewrite because that test was already committed.
  A directory fixture now gives that one test a UUID PostgreSQL schema, so its existing `all()`
  assertion and cleanup see only its own tables even when `SCOREBOARD_TEST_DATABASE_URL` names a
  shared database. A pure regression pins preservation of existing URL query parameters and
  per-schema separation.

**RED evidence:** four focused failures — the exact metadata leak, public/private namespace
collision, unsafe whole-table PostgreSQL access, and absent legacy cleanup migration.

**Verification:** affected suites `104 passed / 3 skipped`; full Scoreboard suite `426 passed / 3
skipped / 3 deselected`, 86.56% coverage. The complete `run_gates.py scoreboard` lane is green:
append-only check, Ruff check, Ruff format check, Pyright, full pytest coverage, and the Node portal
suite. The PostgreSQL-only runtime test remains skipped locally because
`SCOREBOARD_TEST_DATABASE_URL` is unavailable; its schema URL/isolation logic and migration path
run in the default suite.

**Commit:** `084536a2` — `fix(scoreboard): isolate private idempotency namespaces`
(`Refs: OME-894`).

## Review round 5 — 2026-08-26

Two findings, both reproduced first, both valid.

- **[P1] `0008` broke every populated SQLite board.** Tightening `visibility` to NOT NULL has no
  native SQLite equivalent, so Tortoise rebuilds the table and DROPs the old one; with a foreign
  key pointing at `benchmarks`, that DROP fails with `FOREIGN KEY constraint failed`. Reproduced
  against a database holding one benchmark and one score.

  **The tightening is gone rather than worked around.** The column stays nullable, and
  `benchmark_to_schema` coerces a legacy NULL to `public`. The constraint bought nothing: the model
  `default` supplies a value on every write, and a NULL from a pre-migration row reads as public,
  which is exactly what the backfill asserts. No rebuild, no dialect-specific SQL.

  **Why the earlier test missed it:** it inserted only a benchmark. The failure needs a CHILD row.
  Round 1 proved the migration applies to a populated table; it never asked *populated with what*.
  The test now inserts a score too, and is mutation-checked against the restored `AlterField`.

- **[P2] The visibility lookup sat outside the 503 boundary.** `get_score` catches
  `OperationalError` around the score fetch, but the OME-894 benchmark read followed the `try`, so
  a transient disconnect between the two reads escaped as an unhandled 500 on an endpoint that
  documents 503. Both reads are now in one boundary. Mutation-checked by moving the read back out.

## Review round 6 — 2026-08-26

Two findings raised by the owner against the round-5 head, both reproduced before any fix.

**[P1] The reserved private namespace is re-openable during a Helm rollout.** `0009` clears
`sfp-%`, but `job-migrate.yaml:9` is `pre-install,pre-upgrade`, so it runs BEFORE the new pods
roll. Old replicas keep serving through the window and keep storing client keys verbatim, so a
row written then survives the migration. `_resolve_existing` (`store.py:428-434`) returns the
key-linked score with no ownership test, so on a private board a participant can be handed a row
that is not theirs. The migration cannot fix this — it has already run by the time the window
opens.

Fixed at the lookup instead of the migration, so the isolation holds regardless of what the table
contains: on a private board a key-resolved row must belong to the caller, or it is ignored and
the per-submitter content hash decides.

**[P2] The two 404s in `get_score` are distinguishable.** `scores.py:241` raises without headers;
`:254-258` raises the same status and detail WITH `PRIVATE_CACHE_HEADERS`. The invariant comment at
`:244` claims they are identical, so a caller could confirm a real private score id from the
response headers alone. The unknown-id 404 gets the same headers.

### Planned changes

- `apps/scoreboard/src/scoreboard/scores/store.py` — `_resolve_existing` gains `per_submitter` /
  `submitted_by`; both `submit()` call sites pass them.
- `apps/scoreboard/src/scoreboard/routes/scores.py` — the unknown-id 404 carries
  `PRIVATE_CACHE_HEADERS`.
- `apps/scoreboard/tests/unit/scores/test_store.py` — new tests, appended.
- `apps/scoreboard/tests/unit/test_scores_routes.py` — new test, appended.

No schema change, so no migration this cycle (stack rule S1 does not apply).

### Test plan

- A private board with a stale `sfp-` mapping bound to ANOTHER participant's score does not hand
  that score to the caller.
- The same lookup still replays the caller's OWN row for their own key.
- A public board still replays a global key verbatim — the regression guard.
- `GET /v1/scores/{unknown}` carries byte-identical headers to the private refusal.

### Outcome — DONE

Both reproduced red before any fix, both mutation-checked after.

- **The leak, demonstrated:** ALICE's private submit with a colliding key returned BOB's row —
  `assert 'bob@example.test' == 'alice@example.test'`. Reverting the ownership test re-fails both
  store tests; restoring it re-passes them.
- **The header discriminator, demonstrated:** `'private, no-store' == None` between the refusal
  and the unknown-id 404. Removing `headers=` again re-fails both route tests.

**Actual files** — as planned, plus nothing else. `_resolve_existing` was left untouched: a prior
test (`test_the_concurrent_retry_path_resolves_with_the_scoped_key`) monkeypatches it with a
three-argument function, so adding parameters would have edited a prior test to make new code pass
(rule 5). The rule went into a `_resolve_owned` wrapper instead, which is the better home for it
anyway — ownership belongs to the private-board caller, not to key resolution in general.

**Residual, accepted and commented in code:** when the reserved slot is corrupt AND the caller has
no row of their own for that recipe, the insert collides with the stale mapping and the submission
is REFUSED rather than served. Reclaiming the slot would be a write from a resolve path, so it is
deliberately not done. Reaching this at all needs the rollout window plus a guessed scoped key, and
the mapping expires in 24 hours.

**Gates:** all green — append-only check, ruff check, ruff format, pyright, pytest (coverage over
80), portal node tests. The append-only gate passing is the machine-checked proof that no prior
test was touched.

**No schema change**, so stack rule S1 does not apply and no migration was added.

## Review round 7 — 2026-08-26

**[P2] Round 4's fix for the destructive PostgreSQL test was silently fragile.** The isolation
fixture keys off a hardcoded test NAME (`conftest.py:39`), while the guarded test keeps its
unfiltered `IdempotencyKey.all()` assertion and `.delete()` cleanup
(`test_idempotency_postgres.py:66,73`). Two ordinary edits unguard that cleanup against the
configured database — renaming the test, so the fixture stops matching and yields, or adding a
second PostgreSQL test in the same style, never matched at all.

Both failures are SILENT: the suite stays green while wiping a shared table. That is the round-4
finding reopening itself with no signal. `test_idempotency_postgres_safety.py` did not cover it —
it only exercised `_with_schema`, the URL builder, and never asserted the guarded name resolves.

One assertion closes both: the module must define exactly the test the fixture guards. A rename
changes the name it sees; an addition changes the count.

### Outcome — DONE

A guard for a condition that already holds cannot go red on its own, so it was mutation-proved
instead of RED-first, both ways:

- Renamed the guarded test → `Fixture guards '...round_trips_on_postgres'; module defines
  ['...with_a_key_round_trips_on_postgres']`.
- Added a second unfiltered PostgreSQL test → `module defines [..., 'test_a_second_unisolated_
  postgres_test']`.

Both restored; guard green. The failure message names the fixture's expectation and what the
module actually defines, so the next author sees the fix, not just the break.

**Files:** `apps/scoreboard/tests/unit/scores/test_idempotency_postgres_safety.py` only — test
code, no production change. The prior test and the fixture are both untouched, so the append-only
contract holds.

**Gates:** all green.

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
