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
