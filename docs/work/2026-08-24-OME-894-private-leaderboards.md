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

## Review round 8 — 2026-08-26

Three owner findings, all three reproduced in code before any fix.

**[P1] A public key is honoured after its score became private** (`store.py:466-468`). The
ownership test branches on the REQUEST's `per_submitter`, not on what the mapping points AT. Flip a
board public → private while a pre-flip raw mapping is still live (24h TTL), and any caller reusing
that key on ANY public benchmark takes the `not per_submitter` short-circuit: the linked private
score is returned unchecked, and `POST /v1/scores` publishes its id, url4 expression and metadata.
The key lookup is global, not per-benchmark, so the leak crosses boards.

Fixed by testing the LINKED row instead of the request: a mapping is honoured only when the caller
may read what it points at. That subsumes round 6 — the private-board case is the same rule with
the board in question being the request's own.

**[P2] A visibility-only override creates the row it was meant to override**
(`seed.py:356-359`). `_apply_orphan_visibility` documents the invariant — *"this never creates a
benchmark… a configured id the board has never seen stays refused"* — but `_classify_configured`
runs earlier and breaks it. A NEW Engine-published private board is represented in the chart by a
visibility entry with no revision (that is the shape `_with_configured_visibility` requires). During
a catalogue outage its id is in neither `published` nor `engine_owned`, so it falls through to
`allowed` and is CREATED: revisionless, carrying the chart's placeholder text, marked private, and
accepting submissions. `seeded_before` is true on a populated board, so the deploy exits 0.

`test_an_unknown_benchmark_gets_no_visibility_row_of_its_own` asserts exactly this invariant and
misses exactly this case — its fixture passes `revision="r"`, which is refused one branch earlier.

Fixed by making that invariant total: a configured row declaring `visibility` never creates a
benchmark. It overrides a published row, or an existing one, or it is refused.

**[P2] The escaped public namespace is not reserved** (`store.py:287-291`). A public key beginning
`sfp-` is escaped to `sfu-<digest>`, but a client may send that exact digest as an ordinary raw key
and the `else` stores it verbatim. Two distinct client keys then address one mapping and the second
POST replays the first caller's score.

**Approach chosen deliberately.** The reviewer offered two: reserve the generated tokens, or hash
every public key into an unoccupiable namespace. Hashing everything is the more thorough fix, but
`test_a_public_key_is_stored_verbatim` (`test_store.py:1394`) asserts the verbatim representation —
changing it is a rule-5 edit to a prior test and needs owner sign-off. Reserving both prefixes
closes the collision completely without that: any raw key that could collide now starts with
`sfu-`, so it is itself escaped. Flagged below in case the stronger form is wanted.

### Planned changes

- `store.py` — `_resolve_owned` checks the linked row's board; `_scoped_idempotency_key` reserves
  `sfu-` alongside `sfp-`.
- `seed.py` — `_classify_configured` refuses a visibility-declaring row whose target is not
  established.
- Tests appended to `tests/unit/scores/test_store.py` and `tests/unit/test_seed_engine_catalog.py`.

No schema change, so stack rule S1 does not apply.

### Test plan

- A raw mapping made private by a board flip is not replayed to another caller on a public board.
- A public board still replays a global key across submitters — the regression guard.
- An escaped `sfu-` token supplied as a raw key creates a new row rather than replaying.
- A revisionless visibility-only row for an unseen id is refused during a catalogue outage and the
  board stays empty.
- Both prior seed paths still work: an outage still flips an EXISTING board, and a published row
  still receives configured visibility.

### Outcome — DONE

All three reproduced red first, all four changes mutation-checked after.

- **F1**: BOB's public submit returned `created=False` and ALICE's now-private score.
- **F2**: `assert [] == ['healthbench-entry']` — the row was created instead of refused.
- **F3**: the escaped digest, sent as a raw key, replayed ALICE's score.

**One change beyond the plan — and the reason for it.** Closing F1 initially traded the leak for a
`UNIQUE constraint failed` on BOB's insert: the stale mapping was correctly refused, then the write
collided with it. For an ORDINARY PUBLIC submission that is a denial for the whole 24h TTL,
triggered by nothing worse than a config change, so it is not an acceptable price. Reaching that
insert means `_resolve_owned` found nothing honourable, which means any mapping still standing was
refused on purpose — so the write now reclaims its own slot and the expiry condition on that delete
is gone. Mutation-checked in its own right (restoring the condition re-fails the test with the
IntegrityError).

Evicting a mapping is not a new capability: a caller who could reach that key could already REPLAY
the linked score through it, which is strictly more than evicting it. The original client loses only
the fast path — the content hash still dedupes their retry, so no duplicate row.

**This supersedes the round-6 residual.** That entry recorded a refusal as accepted fail-closed
behaviour; it no longer happens, and the stale comment saying so was removed rather than left to
mislead the next reader. Two other comments in `_resolve_owned` were corrected in the same pass:
the opening invariant now says *readable by this caller* rather than *private board*, and the
content-hash note distinguishes the private case (hash carries the submitter) from the public one.

**Gates:** all green. 464 passed, 3 skipped. No prior test modified — the append-only gate is the
proof.

### F3 — the reserve approach is kept, and the reason is now measured

**Asked whether hashing every public key would be better. Measured, and no.** The conservative fix
already closes the finding: probing the reachable key space gives 30 distinct stored values, 0
cross-source collisions, and 0 of the 24 generated tokens reachable by supplying it verbatim.

**The rule-5 cost was four prior tests, not one.** Only
`test_a_public_key_is_stored_verbatim` is about the representation. The other three —
`test_submit_with_expired_idempotency_key_creates_new_score`,
`test_get_by_idempotency_key_respects_expiry_and_cleanup` and
`test_post_score_with_expired_idempotency_key_creates_new_row` — plant or expire `IdempotencyKey`
rows ADDRESSED BY THE RAW KEY, so changing the stored form makes their fixtures invisible and their
premise evaporate. Rewriting three unrelated expiry tests buys nothing measurable today.

**What hashing everything WOULD have bought is now machine-checked instead.** Its only real
advantage was structural: a reserve list is a denylist, and a future third namespace could be added
without updating it. `test_no_generated_storage_token_is_a_fixed_point_of_the_public_path` asserts
the property directly — no value the function generates may be storable verbatim — so that omission
goes red instead of quiet.

**The first version of that guard had the bug it was written to catch.** It selected server tokens
by `startswith(("sfp-", "sfu-"))`, so the `sfx-` mutation was filtered out of its own check and the
test passed. Caught by the mutation, not by review. It now selects any output that differs from its
input, and both mutations go red:

- reserve only `sfp-` → `'sfu-5fd830a1…' is a server-generated storage token a client can supply verbatim`
- rename the private prefix to `sfx-` → `'sfx-49256ab6…'` same

**Process note.** One mutation restore appeared to fail, showing `sfx-` in a later gate run with the
source already clean. It was stale `__pycache__`: the mutated module had been compiled and the
restored source reused its bytecode. Every mutation probe now clears `__pycache__` first, and the
restore is confirmed with `git diff HEAD` rather than by reading the file.

## Review round 9 — 2026-08-26

Three owner findings against the round-8 head. **The P1 is a regression I introduced in round 8.**

**[P1] A claimed owner name bypasses the privacy check** (`store.py:476-478`). Round 8 put the
owner-match short-circuit BEFORE `_links_to_a_private_board`, so the privacy check never runs when
the names agree — and under `auth_mode=disabled` the body's `submitted_by` is trusted. An attacker
POSTs to any PUBLIC board with a stale key and the victim's address in the body, and receives the
private row's id, url4 and metadata. Private READS fail closed in that mode (round 3); this write
path did not.

Reproduced: `same=True`, the attacker's response carried the victim's score id.

Fixed by ordering privacy first and dropping the ownership comparison for a private target
entirely: **a mapping pointing at a private-board row is never honoured.** An unverified string
cannot gate anything, and the genuine owner loses nothing — the per-submitter content hash still
finds their row. Simpler than plumbing verified-identity down into `submit()`, and it cannot be
bypassed by claiming a name.

**[P2] The reclaim deletes a mapping a concurrent winner just bound** (`store.py:579`). Two
requests with the same stored key and different recipes both clear `_resolve_owned`, the first
commits its mapping, and the second's unconditional delete removes it — both insert, both report
`created`, and the key ends up on the last writer, breaking same-key-replays-original.

**Valid by inspection, NOT reproduced.** The scenario needs both requests to finish their precheck
before either inserts; a single-threaded test completes the first submit entirely before starting
the second. Recorded as inspected rather than demonstrated, and the fixture work below is what makes
it testable.

Fixed by narrowing the delete to expired rows OR the exact row this request observed and refused, so
a concurrent rebind survives, trips the unique constraint, and replays.

**[P2] The newly reserved `sfu-` namespace is not purged** (`store.py:260`). `0009` clears only
`sfp-%`, but `main` stores client keys verbatim, so a crafted `sfu-<digest>` mapping can already
exist — and round 8 made the escape path EMIT that namespace. Reproduced: an escaped key resolved a
legacy `sfu-` row and returned an unrelated score.

`0009` now clears both prefixes. The rollout window is closed separately — see below.

### Owner decision taken

**A post-upgrade purge script** (owner, 2026-08-26). Extending `0009` cleans existing data, but the
migrate Job is a `pre-upgrade` hook, so old replicas keep writing verbatim keys after it runs. A
`post-upgrade` operator module re-runs the purge once the rollout has completed, which closes the
window rather than bounding it to the TTL. Follows the `seed.py` / `retire_benchmark.py` precedent:
`main(argv)`, no HTTP surface, run where the credentials already are.

Rejected alternative: reserving a character class clients cannot send, with `Idempotency-Key` header
validation. Structural, but it adds validation to the write path and would reject keys currently
accepted.

### Planned changes

- `store.py` — privacy before ownership; `_resolve_owned` reports the refused target; the reclaim
  narrows to it.
- `migrations/0009_*.py` — clear `sfu-%` as well.
- `purge_reserved_idempotency_keys.py` (new) + a `post-upgrade` chart Job.
- A file-backed SQLite fixture giving tests a SECOND connection — `tortoise_db` is
  `sqlite://:memory:`, which is one connection by definition, and that is why the race branch and
  the clobber above cannot be tested today.
- Tests appended; no prior test modified.

### Test plan

- A claimed owner name does not yield a private-board row.
- A private target is refused even for its genuine owner, who still replays via the content hash.
- A legacy `sfu-` mapping is not resolved by an escaped key.
- `0009` clears both reserved prefixes.
- The purge module deletes both namespaces and reports what it removed.
- A concurrent rebind survives the reclaim, and the race branch replays.

### Outcome — DONE

Two of the three reproduced; the third was fixed on inspection and is now tested. Five mutations
bind.

- **P1 reproduced:** the attacker's response carried the victim's score id (`same=True`).
- **P2 (`sfu-`) reproduced:** an escaped key resolved a legacy row and returned an unrelated score.
- **P2 (clobber)** could not be reproduced — see below.

**The `sfu-` finding has an enforceable half and a residual, and the test now says which.** A legacy
`sfu-<digest>` row is byte-indistinguishable from one this code wrote, so the LOOKUP cannot reject it
on identity. Rejecting on content-hash mismatch was considered and refused: replaying a different
recipe under the same key IS the idempotency contract, so that check would break the feature to
patch a window. What the lookup does enforce is that such a row cannot reach a PRIVATE score, which
is what `test_a_legacy_row_in_the_reserved_namespace_cannot_leak_a_private_score` pins. Existing rows
go to `0009`; rollout-window rows go to the new post-upgrade purge. The residual is a wrong replay of
a PUBLIC score inside that window.

**The clobber fix was untested until a mutation said so.** Reverting the narrowed reclaim to an
unconditional delete changed nothing — three tests passed. The scenario is "both prechecks miss, then
the winner commits", and single-connection in-memory SQLite cannot interleave two real transactions.
Blinding only the FIRST `_resolve_existing` call reproduces exactly that ordering, and the test now
fails under the mutation (*"the loser must replay, not create a second row under the same key"*).
Recorded because a fix nobody can break is a fix nobody is holding.

**`store.py` reached 100% statement coverage**, closing the gap the reviewer named in round 3.
Reaching the race handler's success return needs a racer to commit mid-transaction, which this
fixture cannot do, so it is driven at the seam — the handler's own contract (on IntegrityError, look
again, replay what is found) rather than a simulated database race. The reorder also silently
un-covered the private-request/public-target branch; that has its own test now.

**`PLR0911` was restructured, not silenced.** The two refusal returns collapsed into one `honour`
expression, and `and` keeps the privacy read first — the ordering is the fix, so it is load-bearing.

**Gates:** all green. 483 passed, 3 skipped. `store.py` 100%, `purge_reserved_idempotency_keys.py` 97% — the one uncovered line is the `if __name__ == "__main__"` guard.

## Review round 10 — 2026-08-26 (self-review)

Adversarial pass over the round-9 changes, run because three of the previous four rounds found a
defect in code written to fix the round before. Five attack shapes probed; two findings, one of
them real.

**[P1] `get_by_idempotency_key` ignores visibility entirely.** Probed: after a board flips to
private, `store.get_by_idempotency_key(victim_key)` returns the victim's private score. The method
takes no identity, performs no ownership test, and consults no visibility — it hands back any score
whose key you hold.

It has **no production caller** today, which is the only reason this is not a live leak. That is
also exactly what makes it dangerous: a public method on the store, in the PR whose entire purpose
is making score reads owner-scoped, that silently bypasses every check the rest of this work added.
Wiring it to a route later reopens `OME-894` with no diff that looks suspicious.

Made to fail closed: a linked score on a private board returns `None`. The method has no caller
identity and therefore cannot serve private rows at all; the docstring now says so and points at
the owner-aware paths.

Deleting it as dead code was the alternative — the precedent exists in this same PR, where
`leaderboard(owner=)` and `list_all_for_benchmark(owner=)` were removed. Two prior tests exercise
this one, so removal is a rule-5 decision; failing it closed is additive and breaks neither.

**[P3, not fixed] The privacy lookup runs on every dedup hit.** `_links_to_a_private_board` is now
consulted whenever the key or hash resolves ANYTHING, including a caller replaying their own row on
a public board — measured at one extra query per dedup hit. It is a primary-key read on a tiny
table, and the obvious optimisations (trusting the request's own benchmark, or short-circuiting on
ownership) are precisely the shapes that produced the round-8 and round-9 defects. Recorded rather
than optimised: the ordering is load-bearing and worth a cheap query.

**Checked and clean:** an attacker reproducing the victim's exact recipe after a flip does NOT reach
the row (the per-submitter hash diverges); a private scoped key pointing at a public row is refused;
the purge removes legitimate live mappings as well as crafted ones, and the affected client still
replays through the content hash, which is the documented cost.

## Review rounds 11-12 — 2026-08-26 (self-review)

**Round 11 — route layer. Nothing blocking.** Probed the actual attack surface rather than the
store, where the previous rounds had concentrated. All clean, measured not assumed:

| Probe | Result |
|---|---|
| History: another participant's spec vs a nonexistent one | byte-identical, headers included |
| History: anonymous vs foreign-spec | byte-identical |
| Private leaderboard as a participant | `entries=0`, own row only, no other submitter anywhere in the body |
| Private leaderboard anonymous | 200, nothing owned, no address of any kind |
| POST the same recipe as two participants on a private board | two rows, no replay |
| Untrusted peer under `cloudflare_headers` | write 403, read yields nothing owned |

The frontier's private 404 IS distinguishable from an unknown benchmark's, and that is correct
rather than a leak: D4 publishes every private board in the catalogue, so its existence was never
secret. The same reasoning covers the differing history details.

**[P3, recorded not fixed] Every private check is `== "private"`, so an unexpected value fails
OPEN.** The column is a plain `CharField` with no constraint, and `'Private'` or any typo reads as
public at `store.py:519`, `store.py:556`, `leaderboard.py:183/257/299` and `scores.py:186/253`.
Both supported write paths are validated — `SeedBenchmark.visibility` is a Pydantic `Literal`, and
`BenchmarkSchema` rejects a bad value on the read path (loudly, with a 500) — so reaching this needs
an out-of-band `UPDATE`. Not fixed deliberately: inverting to `(visibility or "public") != "public"`
touches seven privacy comparisons and turns every legacy NULL row private if the coalesce is wrong,
which is exactly the shape of defect the last three rounds produced. Better as its own unit with its
own tests.

**Round 12 — migrations. One finding, fixed.**

**The round-9 `sfu-%` clause had no executing test.** `test_migration_0009_*` seeds an `sfp-` row
and a raw row; it never seeded an `sfu-` one, so the only thing holding that change was
`test_migration_0009_clears_both_reserved_namespaces`, which greps the SQL for the string. A
source-text assertion passes on a malformed clause — demonstrated: appending `AND 1=0` to the new
`OR` keeps the literal `sfu-%` in the file and the grep test stays green.

Now RUN rather than grepped, with a row in each reserved namespace plus two that must survive
(`sfx-not-reserved`, `ordinary-retry` — this clears two prefixes, not a table). Both mutations bind:
dropping the clause, and the precedence trap the grep test accepted.

The grep tests are kept alongside it: they catch a THIRD prefix being reserved without updating the
migration, which the behaviour test — hardcoding two — would not.

## Review rounds 13-14 — 2026-08-26 (self-review)

**Round 13 — chart, prod values, export module. Nothing blocking.** The chart renders under
`values-prod.yaml` with all three Jobs including the new purge. `values-prod.yaml` overrides
nothing, which is the direct confirmation of the `authMode` item under Owner-verify: prod inherits
`disabled`. The export module applies no visibility filter, which is correct — it is the staff
path, has no HTTP surface, and exists precisely to read what participants cannot.

Also checked and clean: the purge Job matches the seed Job's hook shape, weight and `backoffLimit`,
so it introduces no new failure class into a release; and the round-8 seed refusal cannot strand a
live board — every path that could un-private one is covered by an existing test.

**Round 14 — DTO projections. One latent defect, guarded.**

**`list_owned_entries` hand-builds `LeaderboardEntry` field by field**, which is a SECOND projection
of a DTO the ranking query also constructs via `LeaderboardEntry(**row)`. That is the OME-852 shape
the codebase warns about at `_get_benchmark_or_404` — *"use the store's single mapper, never a
second hand-written projection"* — and `RankedLeaderboardEntry` already carries an AIDEV-NOTE about
the same coupling.

All ten fields are projected today, so there is **no live defect**. The hazard is what happens next:
`LeaderboardEntry` is `extra="forbid"` with required fields, so a field added to the DTO and not to
this projection raises rather than degrades, and the casualty is a **500 on the private read path
this ticket exists to protect**. The ranked DTO's version of this coupling is caught by the splat in
`_ranked_entry`; this one had nothing.

Guarded generically — the test walks `LeaderboardEntry.model_fields` and asserts each value came
from the Score row, so a new unprojected field fails on its own by holding the DTO's default instead
of the row's value. No hand-listed field set to maintain. Mutation-checked.

Restructuring the projection to share one mapper is the better long-term answer and is deliberately
NOT done here: it is a refactor of the private read path during review, and the last several rounds
have shown what late restructuring costs. The guard makes the drift impossible to ship silently,
which is what matters now.

## Review rounds 15-16 — 2026-08-26 (self-review)

**Round 15 — data escape paths. Nothing blocking.** Two angles not previously touched:

- **The email trim covers every read DTO.** `SubmittedBy` carries a `when_used="json"` serializer,
  and both `LeaderboardEntry` and `ScoreSchema` use it — verified live: JSON yields `alice`, python
  mode yields the full address. `my_submissions` is therefore trimmed like everything else. The one
  `str | None` submitter is on `ScoreSubmission`, the WRITE DTO, where no trim applies or is wanted.
- **Every `model_dump()` call is safe.** `_ranked_entry` splats in python mode ON PURPOSE — the
  target field re-applies the serializer — and the frontier and field-error dumps carry no
  participant data. `export_private_submissions` keeps the full address deliberately.
- **Nothing is logged.** No log or `print` in `src/` interpolates a submitter, address, metadata or
  url4 expression; the operator modules emit benchmark ids and counts only.

**Round 16 — process artifacts. One finding, drafted not applied.**

All four SDLC artifacts exist for OME-894 — spec, plan, task mirror and this ledger.

**The PR description had gone stale in a way that matters.** It described `rank: null` on a private
board with the caller's rows in `entries` — the D3 design, superseded by D12 six review rounds ago.
The implementation returns `entries: []` with the caller's rows in `my_submissions`, and `rank` is a
required `int`. The body also predated the entire submission-path half of the work: the reserved key
namespaces, `0009`, and the post-upgrade purge were absent from it.

That is the artifact a reviewer reads before the diff, and it misdescribed the response shape.

**Rewritten but NOT posted.** Editing the PR body is outward-facing, and the commits it describes
are not pushed — publishing it now would document code that is not on the branch. The draft is
ready to apply alongside the push.

## Review round 17 — 2026-08-27 (@HupBaHa, PR #719, third review)

**[P1] The visibility check and the write raced.** `routes/scores.py:183` read visibility to decide
whether to refuse an unverified write; `store.submit()` read it AGAIN at `store.py:555` to decide
per-submitter semantics. Two reads of the same authority, and the decision that governs PERSISTENCE
used the second one while the guard used the first. Flip a board public -> private between them —
which the seed job does on every deploy — and the guard passes on stale data.

Reproduced: `status=201`, board private, and
`submitted_by='victim@example.test' metadata={'attacker': 'controlled'}` persisted under
`auth_mode=disabled`.

**Fixed by deleting the route's read, not by adding a third.** The store now owns the whole
decision, taken at the single read that governs persistence, so there is no window to race. The
route passes whether identity was verified and maps the refusal to the same 403 it raised before.

### Owner decision — 2026-08-27

**The parameter defaults to NOT verified, and 17 prior tests were edited to say `identity_verified=True`.**
Put to the owner as the rule-5 decision it is, with both options priced:

- *Fail closed* (chosen): a forgotten wiring makes private boards REFUSE writes — loud, safe, and
  fixable. Cost: 17 prior store-level tests gain one keyword argument.
- *Fail open*: no prior test touched, but a second call site that forgets the parameter silently
  reopens this exact bug. That is the shape this reviewer has caught four times in this PR.

### Outcome — DONE (P1 only; P2 is a separate decision, see below)

Reproduced first: `status=201`, and `submitted_by='victim@example.test'`
`metadata={'attacker': 'controlled'}` persisted on a board that was private by the time it was
written.

**Fixed by removing a read, not adding one.** `routes/scores.py` no longer reads `visibility` at
all. `submit()` takes the whole decision — the identity rule AND per-submitter dedup — at its single
read, and refuses before it looks anything up, so a forged request still cannot learn whether a
matching row exists. The route passes `identity_verified` and maps `PrivateBoardRequiresIdentity` to
the same 403 it used to raise itself, so the route contract is byte-identical.

**The test edits are smaller than priced, and no pre-PR test was touched.** 33 call sites across
the private-board scopes of three files. Every one adds a keyword argument; the diff removes no
assertion. And every edited test was ADDED BY THIS PR — the only two lines that differ from
`origin/main` in `test_store.py` are import lines. The append-only gate therefore passes on its own,
with no `--skip-append-only` and no exception to document.

**The default is pinned by its own test**, because the route passes the value explicitly and nothing
else in the suite would notice it being flipped. Three mutations bind: removing the refusal (4
failures), flipping the default to `True` (1), and having the route always claim verified (3).

## Review round 18 — 2026-08-27 (P2, and a reversal of two earlier decisions)

**[P2] `same key replays the original` was broken in two independent ways.** Both reproduced; the
matrix is what settled the design.

| Case | Replays? |
| -- | -- |
| public board, ordinary key, changed payload | yes — contract holds |
| **private board, caller's OWN key, changed payload** | **NO — round 9** |
| private board, identical payload | yes, via the content hash |
| public board, reserved-prefix raw key, before the purge | yes |
| **public board, reserved-prefix raw key, after the purge** | **NO — the reviewer's finding** |
| attacker claims the victim's address, unverified | no leak — the round-9 guard holding |

**The reviewer's finding is real but narrower than stated, and the larger half is ours.** The purge
only touches reserved prefixes, so it breaks replay for public callers whose raw key happens to
start with `sfp-`/`sfu-`. His reproduction used a PRIVATE board, where replay was already broken
before the purge ran — by round 9's blanket refusal of any mapping pointing at a private row. That
is every private submission, on exactly the boards this ticket exists for.

### Why the blanket refusal could now be relaxed

Round 9 refused unconditionally because `submitted_by` is forgeable under `auth_mode=disabled`, so
an ownership comparison meant nothing. **P1 changed that**: the store now knows whether identity was
verified. The comparison is sound exactly when it is, so the rule becomes *honour a private target
only when identity is verified AND the row belongs to the caller*. The attacker case stays closed
because an unverified caller never reaches the comparison.

### Why the purge goes rather than gets a marker column

With the ownership rule restored, the purge stops being load-bearing for privacy — a stale mapping
to someone else's private row is refused at the lookup, whatever the table contains. What it still
does is delete live mappings, which is the finding.

**Migration `0009` stays, and the asymmetry is the whole point.** It is a `pre-install,pre-upgrade`
hook, so it completes before any new pod can have written a new-scheme row: it can only ever delete
legacy ones. The purge was `post-upgrade` — by the time it ran, live new mappings existed. Same SQL,
opposite safety, decided entirely by when it runs.

Rejected: adding a marker column in `0010` so the purge could tell legacy rows from new ones. It
fixes the reviewer's case and not ours, and it carries a schema change forever to serve one rollout.

### Planned changes

- `store.py` — `_resolve_owned` gates the private-target decision on `identity_verified`.
- Deleted: `purge_reserved_idempotency_keys.py`, its chart Job, its values block, its tests.
- Tests appended for each row of the matrix above.

### Outcome — DONE

Both cases fixed, **net -279 lines of production and chart code.** Three mutations bind: dropping
the verified gate (the round-9 leak returns), dropping the ownership test (any verified caller takes
any private row), and reverting to the blanket refusal.

**A mechanical edit corrupted a test, and a test caught it.** P1's patcher added
`identity_verified=True` to every submit inside a private-board scope, which included the ATTACKER's
submit in `test_claiming_the_owners_name_does_not_yield_a_private_row` — quietly promoting the
attacker to a legitimate verified ALICE and destroying the scenario. It surfaced as the only failure
after this change. The attacker's call now passes no identity argument, with a comment saying why,
because the next mechanical sweep will be tempted to add one again.

**Two round-9 tests described behaviour that has since reversed.**
`test_a_private_target_is_refused_even_for_its_genuine_owner` asserted a cost that no longer exists
— the verified owner gets the key fast path back — so it is renamed for what it actually guards, the
content-hash path. And a duplicate of the attacker test written this round was dropped rather than
kept alongside the original.

**Comments naming the deleted module were corrected, not left.** Two referenced
`purge_reserved_idempotency_keys` as the thing that cleans the rollout window; they now say what is
true — `0009` runs pre-upgrade and sees only legacy rows, and a row written during the window
survives, bounded to a wrong replay of a PUBLIC score.

## Review round 19 — 2026-08-27 (self-review of the P1/P2 fixes)

**The reviewer's own two reproductions were run verbatim and no longer reproduce.** His P1 — flip
visibility immediately before the store call — now returns `403` with nothing stored. His P2 — same
key, changed payload — replays the original.

**Two fail-open shapes in the code written for P1/P2, both closed.** Neither is reachable today;
both are one forgotten call site from being reachable, which is the class the owner just chose to
fail closed on.

- **`auth_mode != "disabled"` was a denylist.** `AuthMode` is `Literal["disabled",
  "cloudflare_headers"]`, so it reads correctly today — but a third mode added later would count as
  VERIFYING until someone remembered to exclude it, on the decision that governs whether a private
  board accepts a write. Replaced with `identity_is_verified()`, an allowlist naming the modes that
  do verify, so a new one has to be added on purpose. Tested by passing a mode outside the Literal.
- **`None == None` read as "this is mine".** `Score.submitted_by` is nullable and
  `ScoreSubmission.submitted_by` is optional, so an orphan private row and an anonymous caller
  compared equal and the row would have been handed over. Unreachable through the route — verified
  mode 401s on a missing identity — which is precisely why it should not depend on that staying
  true. Ownership now requires an actual owner.

**Full sweep: 11 mutations across every privacy control, old and new, all bind.** Private-write
refusal, the fail-closed default, the verified gate, the absent-submitter test, the auth-mode
allowlist, 404 header symmetry, the unowned lookup, the reserved prefix, the seed refusal, `0009`,
and the owned-entry projection.

## Review round 20 — 2026-08-27 (owner, PR #719)

**[P1] Reading visibility once narrowed the race; it did not close it.** Round 17 collapsed the
route's read and the store's into one. But one read still happens at a point in time and the write
happens after it, so a flip landing in between leaves the whole request running on stale rules —
stale hashing AND a stale identity decision.

Reproduced at the point the owner named, by flipping after the store's read:

- **A — an unverified write persisted on a board that was private by the time it landed.**
  `persisted=True  board_now=private  rows=1`
- **B — a confidentiality leak, and structural rather than timing.**
  `created=False  got_hers=True  metadata={'secret': 'alice@example.test-only'}` — BOB received
  ALICE's private row with her metadata.

**B is the sharper half.** `store.py:538` returned the content-hash fallback with NO privacy check
at all: the KEY path gained an ownership rule in round 18 and the fallback beside it never did. The
race is only what lets a stale public hash match a now-private row; the missing check is why that
leaks instead of being refused. It would have leaked through any other route to the same mismatch.

**Attribution, since the ledger should be right about it:** this came from the owner in review, not
from `@HupBaHa`. His third review's two findings are the round-17 and round-18 entries above, and
both of his reproductions were re-run verbatim and no longer reproduce.

### Three fixes, and what each actually buys

| | Buys |
| -- | -- |
| Privacy-gate every return from `_resolve_owned`, fallback included | closes B outright, independent of timing |
| Revalidate visibility before persisting or returning | refuses to act on stale state rather than acting wrongly |
| `select_for_update()` on the benchmark row inside the insert transaction | genuinely serialises the persist path — on PostgreSQL |

Stated plainly because the tests cannot show all of it: the lock is a no-op on SQLite, so the suite
demonstrates the revalidation and the privacy gate, and PostgreSQL is what the lock is for. Without
a lock, revalidation shrinks the window from the whole request to the commit interval; it cannot
eliminate it. Claiming otherwise would be claiming more than the suite proves.

### Outcome — DONE

Refusal surfaces as **409, not 500** — nothing is wrong with the request, and a retry gets one
consistent view. `submit()` crossed `PLR0915` and the insert was extracted to `_insert_new_score`
rather than the limit being raised.

**Mutation results, including the one that does not bind:**

| Mutation | Caught |
| -- | -- |
| fallback no longer wired to the gate | 1 failure |
| the gate itself ignores ownership | 2 |
| revalidation removed from the return path | 1 |
| revalidation removed from the persist path | 2 |
| **the row lock removed** | **NOT CAUGHT** |

The lock is invisible to the suite because Tortoise no-ops `select_for_update()` on SQLite. That is
not a gap to paper over: it is the honest shape of this fix, and the PR should say so rather than
imply the tests cover it.

**Two of my own tests proved nothing until a mutation said so.** The first wrapped its assertions in
`contextlib.suppress`, so they never ran — the same trap as round 6, made the same way. The second
looked like it exercised the return-path revalidation but fell through to the insert, where the
OTHER revalidation fired; it passed for the wrong reason. Both are now driven at the level that
reaches the code under test, with a note on each saying which detail is load-bearing.

**The fallback's wiring is tested at `_resolve_owned`, deliberately.** Through `submit()` the only
route to that state is a mid-flight flip, which the revalidation refuses first — so the wiring would
have been untested while appearing covered. Both defences are real; this is the one that survives if
the other is ever relaxed.

## Review round 21 — 2026-08-27 (owner, PR #719)

**[P1] The stale-visibility window was closed on writes and left open on reads.** Round 20 fixed
`submit()`; every read path still decided from a visibility read and then ran a query, with nothing
between them. Reproduced on all three:

| Path | Result with a flip during the query |
| -- | -- |
| `/v1/leaderboard/{id}` | `200`, **`entries=2`, `scoped_to_caller=false`** — both participants' rows on a board that is private by the time it answers |
| `/v1/leaderboard/{id}/{spec}/history` | `200`, another participant's submissions to an anonymous caller |
| `/v1/leaderboard/{id}/frontier` | `200`, the aggregate D5 says a private board must not publish |

`GET /v1/scores/{id}` runs no store query after its visibility read, so its window is read →
serialise rather than read → query. Narrower, and closed the same way for consistency.

### The fix is a re-decision, not an error

Writes answer a flip with `409`: the request cannot be completed under either view, so refusing and
letting the caller retry is right. **A read can simply answer correctly instead.** Revalidating and
then producing the PRIVATE response for that path — scoped entries, or the 404 history and frontier
already return — gives the caller the right answer rather than an error, and needs no retry.

Only the branch that would return a PUBLIC response revalidates. The other direction, private →
public mid-read, returns the scoped shape for a board that has just opened: less than the caller
could have had, never more, and not worth a query.

### Outcome — DONE

`turned_private()` lives in `routes/dependencies.py`, the module both route files already share. It
started as a private helper in `leaderboard.py` that `scores.py` reached across for, which is the
kind of import that turns two modules into one by accident.

The leaderboard's private response was extracted to `_private_leaderboard()` so the initial decision
and the re-decision return the SAME thing rather than two shapes that have to be kept in agreement —
the OME-852 failure mode this file already carries a comment about.

**Four mutations, all bind:** removing the re-decision from the ranking path, the history path, the
frontier path, and `get_score`. The `get_score` one did not bind at first because no test covered
it — the fix was written and unheld until a mutation said so, for the third time in this PR.

Cost when nothing flips, which is every real request: one indexed primary-key read on the public
branch. Guarded by a test asserting the undisturbed public response is unchanged.

## Review round 22 — 2026-08-27 (owner, PR #719)

**[P2] The re-decision suppressed the entries and shipped a stale benchmark DTO with them.**
Reproduced: `scoped_to_caller = True` beside `benchmark.visibility = 'public'`, while the database
said `private`. Two statements of the same fact, disagreeing in one body — and `visibility` is the
field D4 added specifically so a client could render a board as private, so a client acting on it
would have labelled a private board public.

Not challenged. There is an argument that `scoped_to_caller` is the authoritative signal and
`visibility` merely descriptive, but that argument dies on D4: the field was exposed for clients to
act on, so shipping it wrong is a contract bug whatever else the body says.

**Fixed inside `_private_leaderboard` rather than at the call site.** That function owns the claim
that the board is private, so it states it in the DTO too. Fixing the one caller that had the stale
value would have left the two callers free to drift; asserting it in the callee makes the
contradiction unrepresentable. On the initial-decision path it is a no-op, since that read already
returned `private`.

Mutation-checked, and the test pins BOTH paths — the flip and the ordinary private read — because
the point is that they agree.



## Review round 23 — 2026-08-27 (class sweep, not another instance)

Three rounds running had been the same defect at a different layer — writes deciding from stale
visibility, then reads, then a response body carrying a stale copy. Each time the named instance was
fixed and the class was not. So the class was swept instead of waited for.

**Method, mechanical rather than by eye**, because reading by eye had missed it three times: parse
every function in `src/scoreboard`, and for each that touches `visibility` / `per_submitter` /
`is_private`, print the ORDERED sequence of visibility reads and `await`s. A read followed by an
`await` followed by a use of that read is the shape.

**One live gap, and it is the branch this PR keeps finding under-covered.** `submit()`'s
pre-insert return revalidates; its `IntegrityError` return did not. That branch is reached BECAUSE
something changed concurrently, so it is the least safe place to trust a read taken before the
failed insert — and the persist-path check that already passed cannot speak for the time spent
failing.

Reachable only for a caller replaying THEIR OWN private row: any other submitter is refused by the
privacy gate before the revalidation is consulted. Narrow, and real. Mutation-checked.

### Cleared, with the reason

| Site | Why it is safe |
| -- | -- |
| `get_leaderboard`, `get_spec_history`, `get_frontier`, `get_score` | all revalidate before returning public data (round 21) |
| `_private_leaderboard` holding the DTO across an `await` | a flip back to public during it returns the RESTRICTIVE shape |
| private → public mid-read on any private branch | returns scoped data for a board that has just opened: less than allowed, never more |
| `get_by_idempotency_key` | its privacy check runs AFTER the await and is the authority |
| `seed_from_sources` — `existing_ids` stale across `seed_benchmarks` | only a concurrent second seed job could exploit it; Helm hooks serialise per release and `register_benchmark` is idempotent |
| `_apply_orphan_visibility`, `_with_configured_visibility` | read visibility from CONFIG, immutable within the pass |
| `identity`, `auth_mode`, `submitted_by` | the other authorisation inputs, none mutable after the request starts — `submitted_by` is never updated after creation |

Visibility is the only mutable authorisation input in this app, which is why it is the only one that
needed this.

### The test took three attempts, and the reasons are worth keeping

Flipping inside `Score.create` looks the most faithful and does not work: that runs inside the
insert transaction, so single-connection SQLite rolls the flip back with it. Flipping earlier is
caught by the persist-path check and proves nothing about this one. And the caller has to be
replaying their OWN row, or the privacy gate refuses first and the revalidation never runs. Each of
those is now a comment in the test, because the next person to touch it will hit all three.


## Review round 24 — 2026-08-27 (owner, PR #719)

Two halves. The first was already closed by the round-23 sweep, which landed after the comment was
written — the replay return revalidates at `store.py:764`. The second was open, and it is mine.

**[P2] The `raise` exit of the same branch was answered `503 score store unavailable`.** Not the
unhandled 500 the comment describes, and the difference matters: `IntegrityError` **subclasses**
`OperationalError`, so re-raising it is caught by the route's store-unavailable handler. The caller
is told the database is down when the board had merely changed, and a conflict is masked as an
outage. Reproduced: `{"detail":"score store unavailable"}`.

**The privacy gate is what made it reachable, so this is a consequence of round 18.** Once the board
is private the winner's row is no longer readable, so nothing resolves in the retry branch and the
bare `raise` runs. Before the gate existed, that branch almost always found something.

**Fixed by revalidating before BOTH exits rather than only the replay.** One call above the branch
instead of one inside it — simpler than what round 23 left, and it turns the flip case into the 409
it should always have been. A genuine integrity failure with visibility unchanged still re-raises,
because that IS a server-side surprise and should not be dressed as a retryable conflict.

Two mutations bind: removing the call (2 failures), and moving it back inside the `if` (1) — the
second is the exact shape round 23 shipped, so the test now holds the difference.

**Noted, out of scope:** `except OperationalError` in the route swallows every `IntegrityError` as
`503`, for all paths and not just this one. Pre-existing, wrong, and a bigger change than this PR
should make.

**The test took three attempts** and each failure was informative, so the reasons are comments in
it: the flip cannot be landed inside `Score.create` (single-connection SQLite rolls it back with the
transaction), cannot be landed before the persist-path check (that check catches it and proves
nothing), and the caller must be replaying their OWN row for the replay exit — a different submitter
is refused by the privacy gate first.


## Review round 25 — 2026-08-27 (sweep re-run, keyed on EXITS)

Round 23's sweep asked *does this return revalidate*. It should have asked *does every path out of
this branch revalidate* — which is why it found the replay exit and missed the `raise` beside it,
and why round 24 was needed at all. Re-run properly.

**Method:** for every function that reads `visibility` or takes a decision derived from it, walk the
statement tree and, for each `return`/`raise`, determine whether a revalidation MUST have executed
first — propagating the flag through `if` / `try` / `with` rather than reading the code in order.

**Two blind spots in the first attempt, both confirmed as false negatives** rather than defects:

- a guard in an `if` TEST whose body always exits means the fall-through path IS revalidated — the
  check ran and reported no change. That covers `get_leaderboard:250`, `get_spec_history:315`,
  `get_frontier:354` and `get_score:314`.
- a revalidation inside an `async with` body dominates everything after the block, because the body
  must finish before control leaves it. That covers `submit:745`, the successful-insert return.

**No new live gaps.** All 28 remaining unguarded exits are restrictive (return the private shape or
refuse), pure, writers of visibility rather than readers, helpers whose CALLER guards every path
out, functions that read visibility fresh at call time, or config-driven seed code.

### The sweep is now a test, not an exercise

`tests/unit/guards/test_visibility_exit_guard.py` runs the analysis and asserts the unguarded set
against an allowlist that records WHY each entry is safe. A new unguarded exit fails it; so does an
entry that has since been guarded, so the list shrinks instead of quietly over-permitting.

Keyed on `(function, exit kind, count)` and never on line numbers, because a guard nobody can keep
green gets deleted.

Proven to catch regressions rather than assumed to. Four shapes, all caught: removing `submit()`'s
retry revalidation, removing the persist-path revalidation, removing the leaderboard re-decision,
and adding a brand-new unguarded early return.

The analyser itself cost four rounds with the linter — `C901`, `PLR0912`, `PLR0911`, then pyright on
the dispatch table. Every one was restructured rather than suppressed: one small method per
statement kind, a dispatch table instead of a chain of returns, and narrowing inside the handlers
rather than a `type: ignore`. A guard carrying suppressions is a guard the next person deletes.

**This is the answer to the actual problem.** Four rounds of this were the same class found at
different layers, and each fix addressed the instance. A test that fails on the shape is the only
version of that work which survives me not being here.


## Known residual — the concurrent-retry success return

`store.py:607` — the `return SubmitOutcome(..., created=False)` inside `submit()`'s
`IntegrityError` handler — is **not covered**, and round 8 rerouted that branch through
`_resolve_owned`. The reviewer named this in round 3: *"This branch is currently uncovered, and the
PostgreSQL concurrency tests are skipped without `SCOREBOARD_TEST_DATABASE_URL`."* It is still true.

**Two attempts, and why they cannot work here.** Reaching that line requires a racer to COMMIT
between this caller's resolve and its insert — nothing else gets there, because the pre-insert
resolve otherwise finds the row and returns early. The suite's `tortoise_db` fixture is
single-connection in-memory SQLite, so a row created "off the transaction" is rolled back with
everything else and the handler finds nothing, exactly as if no racer existed. Forcing it produced a
test that fails on the suite's own engine.

Left uncovered deliberately rather than papered over with an assertion that re-tests the pre-insert
path and merely touches the line. Closing it honestly needs `SCOREBOARD_TEST_DATABASE_URL` and a
real second connection, which is `OME-430`'s ground.

Everything reachable on that branch IS covered: the key it consults
(`test_the_concurrent_retry_path_resolves_with_the_scoped_key`) and the ownership rule it now
applies (`test_a_private_key_hit_owned_by_another_participant_is_not_served`). Only the final return
is unexecuted.

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
