# SB-registry — system names, revisions and fingerprints in the scoreboard (E14, OME-1307) — implementation plan

Epic: [OME-1307](https://linear.app/openmined/issue/OME-1307) · Component: `apps/scoreboard` ·
Wave: 2 (D2) · Stack card: `scoreboard` (skill `sdlc-python`, companion `tortoise-dev`).

Binding decisions: D1 (one branch), D2 (wave 2 with SB-meta), D3 (the fingerprint call with
`exclude_bindings=frozenset({"_sf_recipe"})`), D5 (every submitter and owner is the verified
`cloudflare_headers` identity), D7 X-18 (C11 by unit tests), D7 X-22 (the url4 cap is the
existing 32,000 chars with `422`).

Spec (the rubric): `docs/spec/2026-09-29-e14-reproducible-submission/prd/system-registry.md`
(read in full), `erd.md` §2.3, §2.4, §6.4, `contracts.md` C11, `test-plan.md` §1.
Also read the URL4-fp plan §4.1-§4.4 (the `url4.fingerprint` contract, the `exclude_bindings`
parameter and the golden vectors).

Branch / worktree (D1): build in a temporary worktree on branch `unit/SB-registry`, made from
the HEAD of `e14-reproducible-submission-spec` after the wave-1 integration:
`git worktree add .claude/worktrees/unit-SB-registry e14-reproducible-submission-spec`, then in
that worktree `git checkout -B unit/SB-registry e14-reproducible-submission-spec`. There is no
PR, no Linear issue and no CI merge gate for this unit. After wave 2, the integrator merges the
unit branches into `e14-reproducible-submission-spec` (SB-meta first, then SB-registry; see
§2.3) and runs the gates.

Plan: this file, `docs/plan/2026-09-29-e14-reproducible-submission/SB-registry.md`. Do not copy
it. Ledger: `docs/work/2026-09-29-e14-system-registry.md` (`ticket: unfiled`).

One SDLC unit, one stack (`scoreboard`). This unit adds a **service** and a CLI command. It
adds **no route**: SB-submit calls the service from `POST /v1/scores`, and SB-grants calls
`resolve_pin`.

## 1. Scope

### 1.1 In scope

From `prd/system-registry.md` §7: **SR-1, SR-6, SR-7, SR-8, SR-9, SR-10, SR-11, SR-12,
SR-13, SR-14, SR-15, SR-16, SR-17, SR-18, SR-19, SR-20**.

Plus, with plan-local ids:

| Id | Test | Why it is here |
|---|---|---|
| SR-5-SB | `test_sr5_url4_fingerprinter_matches_golden_vectors` | the scoreboard half of SR-5 (URL4-fp plan §4.4 assigns it to this unit) |
| SR-H3-SB | `test_sr_h3_sdk_recipe_rename_is_one_identity` and `test_sr8_h3_sdk_recipe_rename_returns_notice` | SR-H3 with the real adapter and SDK-shaped url4s (D3). SR-8 with the fake proves the notice; these rows prove that a recipe rename does not make a new fingerprint |
| BF-1 to BF-7 | the `backfill-systems` command (erd.md §6.4) | named in the unit map |
| C11-SB-1 to C11-SB-3 | layering guards | contracts.md C11 "Layering-check rule and a test" |

### 1.2 Out of scope

- SR-2, SR-3, SR-4 and the url4 half of SR-5: URL4-fp.
- Calling the registry from `POST /v1/scores`, writing `Score.system_revision_id` on submit,
  the `notices` response field, mapping errors to HTTP: SB-submit.
- `result:<uuid>` and `score:<uuid>` pins, head selection by benchmark and by date: SB-grants
  (RP-6 to RP-8). This unit parses only the three name forms.
- Prometheus counters `scoreboard_system_resolutions_total`, `…_name_conflicts_total`: the
  scoreboard has no metrics stack (OD-R6, decided (default)).
- The `fingerprint` NFR (64 KB in ≤ 50 ms). The cap is 32,000 chars (D7 X-22), so a 64 KB url4
  cannot reach the fingerprinter. No wall-clock test (test-plan §1 rule 7).
- The auth mode, the identity read and the `disabled` fallback. SB-submit reads the verified
  submitter; the WIRING unit sets `cloudflare_headers` in the chart (D5, D6).
- Rename, transfer, fuzzy match, namespaced names (PRD §5).
- Editing `.claude/scripts/check_layering.py`. Decided: D7 X-18 — the C11-SB guard tests
  enforce the scoreboard rules.

## 2. Depends on

- **SB-schema** (wave 1, in the e14 branch HEAD): `System`, `SystemRevision` models and tables,
  `Score.system_revision_id`, `Benchmark.visibility`.
- **URL4-fp** (wave 1, in the e14 branch HEAD):
  `url4.fingerprint.system_fingerprint(linked, binding="candidate", *, exclude_bindings=frozenset()) -> str`
  and `url4.fingerprint.canonical_system_url4(linked, binding="candidate", *, exclude_bindings=frozenset()) -> str`,
  which raise `url4.Url4Error` unchanged (URL4-fp plan §4.1-§4.2); and
  `packages/url4/tests/fixtures/fingerprint_vectors.json` with the top-level keys `binding`
  (`"candidate"`) and `exclude_bindings` (`["_sf_recipe"]`) (URL4-fp plan §4.3).
- **SB-meta** (wave 2, same wave): no code dependency. Merge order only (§2.3).
- Contracts: consumes the pure fingerprint (C11 rule 1). Implements C11 rule 2 ("the
  scoreboard may import `url4`; never `screamingface`"). Provides the registry that C4 (SB-submit)
  and C6 (SB-grants) use.

### 2.1 Assumption A5 — resolved: the scoreboard may depend on `packages/url4`

- The scoreboard has no `url4` dependency today (`apps/scoreboard/pyproject.toml:5-13`).
- `url4` needs only `httpx` at runtime (`packages/url4/pyproject.toml:20-22`); the scoreboard
  already has `httpx>=0.28.1` (`apps/scoreboard/pyproject.toml:10`). No new third-party package.
- The engine already consumes `url4` as a repo path dependency
  (`apps/screamingface-engine/pyproject.toml:104-105`) and its image mirrors the repo layout
  for it (`apps/screamingface-engine/Dockerfile:33-40, 60-66`). This unit copies that pattern.
- The local runtime already ships both `scoreboard` and `url4` inside the SDK wheel
  (`packages/screamingface/scripts/check_distribution.py:55-58`), so `import url4` works in the
  bundled scoreboard with no SDK change.
- `import url4.fingerprint` runs `url4/__init__.py`, which imports only `url4` modules and
  `httpx` (`packages/url4/src/url4/__init__.py:58-128`). Nothing heavy.

### 2.2 SR-5 parity — where it lives

The scoreboard may not import the SDK (C11), so no single test can call both. Parity comes from
one frozen oracle (URL4-fp plan §4.4): `packages/url4/tests/fixtures/fingerprint_vectors.json`.
The url4 half lives in `packages/url4/tests/unit/test_fingerprint_parity.py` (URL4-fp). The
scoreboard half lives **here**: `apps/scoreboard/tests/unit/registry/test_url4_fingerprinter.py`
reads the file by repository path and runs every vector through the scoreboard adapter. The
exemplar for a test that reads a file outside the app by path is
`tests/unit/guards/test_postgres_regressions_run_in_ci.py:20-22`. The SDK half has no owner yet
(URL4-fp spec gap G2, X-9).

The production call is fixed by D3:
`system_fingerprint(linked, binding="candidate", exclude_bindings=frozenset({"_sf_recipe"}))`.
The adapter owns the constant `SDK_METADATA_BINDINGS = frozenset({"_sf_recipe"})` (§4.8).
SR-5-SB checks that this constant equals the `exclude_bindings` list in the vectors file, so the
scoreboard and the url4 half use one call shape.

### 2.3 Integration notes (for the integrator, D2)

Same-wave shared files with **SB-meta** (wave 2). The integrator merges `unit/SB-meta` first,
then `unit/SB-registry`. Every overlap is additive:

| Shared file | SB-meta adds | SB-registry adds | Merge rule |
|---|---|---|---|
| `apps/scoreboard/src/scoreboard/main.py` | its `app.state` wiring | `app.state.system_registry = …` (§3) | keep both; SB-registry line after the SB-meta lines |
| `.github/workflows/scoreboard-tests.yml` | its test paths | `"packages/url4/**"` in both `paths` lists and the registry PostgreSQL module in the `postgres` job | keep both lists; no duplicate line |
| `apps/scoreboard/DEPLOYMENT.md` | no change (not in SB-meta §3) | "Backfill system names" | no overlap in wave 2; add the section at the end of the E14 part |

Other possible overlaps: `apps/scoreboard/pyproject.toml` and `apps/scoreboard/uv.lock` if
SB-meta adds a dependency. The rule: keep both entries in `pyproject.toml`, then run `uv lock`
again in `apps/scoreboard` (do not hand-merge the lock) and check `uv lock --check`.
After the merge, the integrator runs §7.3 and §8 on the e14 branch.

### 2.4 The submitter identity (D5)

- In production the scoreboard runs the existing auth mode `cloudflare_headers`
  (`apps/scoreboard/src/scoreboard/core/auth/cloudflare_identity.py`: the peer check against
  `SCOREBOARD_ALLOWED_NETWORKS` before the `X-User-Email` read). The `submitter` argument of
  `resolve_for_submit` is that verified identity. SB-submit reads it; this unit only receives it.
- `System.owner` and `SystemRevision.declared_by` store that raw verified identity. The owner
  check of SR-10 (`NotSystemOwner`) compares it.
- `disabled` mode is a dev/local fallback only. There SB-submit keeps today's behaviour
  (content-hash clustering) and does not call `resolve_for_submit`. So the registry never gets
  a `None` submitter; the `submitter: str` type stays (OD-R10 decided: D5).
- The backfill reads `Score.submitted_by`. Legacy heads that were stored while production ran
  `disabled` have `submitted_by = NULL`. They get the row `no_owner` and stay unlinked (§4.10
  step 5). This is correct: the registry has no verified owner for them.

## 3. Files

| Path | Change | Exemplar to imitate |
|---|---|---|
| `apps/scoreboard/src/scoreboard/core/registry/__init__.py` | create (re-exports) | `core/auth/__init__.py` |
| `apps/scoreboard/src/scoreboard/core/registry/model.py` | create: value types | `core/auth/cloudflare_identity.py` (pure, no framework) |
| `apps/scoreboard/src/scoreboard/core/registry/errors.py` | create: registry errors | `scores/store.py:545-583` (exception classes with anchors) |
| `apps/scoreboard/src/scoreboard/core/registry/names.py` | create: normalize, suggest | `core/auth/cloudflare_identity.py:31-70` |
| `apps/scoreboard/src/scoreboard/core/registry/pins.py` | create: `parse_pin` | same |
| `apps/scoreboard/src/scoreboard/core/registry/ports.py` | create: `SystemFingerprinter`, `SystemRepository`, `SystemRegistry` protocols | `core/auth/cloudflare_identity.py` ("that module is the port", `routes/dependencies.py:8-11`) |
| `apps/scoreboard/src/scoreboard/core/registry/service.py` | create: `RegistryService` | — (new rules; follow the module docstring style of `scores/store.py`) |
| `apps/scoreboard/src/scoreboard/adapters/__init__.py` | create (empty) | — |
| `apps/scoreboard/src/scoreboard/adapters/url4_fingerprinter.py` | create: `Url4Fingerprinter` | `routes/dependencies.py:1-40` (a thin adapter over a port) |
| `apps/scoreboard/src/scoreboard/scores/system_registry_store.py` | create: `TortoiseSystemRepository` | `scores/baseline_store.py:37+`, savepoint rule from `tortoise/backends/base/client.py:369-385` |
| `apps/scoreboard/src/scoreboard/backfill_systems.py` | create: the out-of-band command | `retire_benchmark.py:161-212`, `delete_scores.py` (dry run first) |
| `apps/scoreboard/src/scoreboard/main.py` | change: `app.state.system_registry = RegistryService(TortoiseSystemRepository(), Url4Fingerprinter())` | `main.py:179-181` |
| `apps/scoreboard/pyproject.toml` | change: add `"url4"` to `dependencies`; add `[tool.uv.sources] url4 = { path = "../../packages/url4", editable = true }` | `apps/screamingface-engine/pyproject.toml:104-105` |
| `apps/scoreboard/uv.lock` | change: regenerated by `uv lock` | — |
| `apps/scoreboard/Dockerfile` | change: mirror the repo layout for the path dependency | `apps/screamingface-engine/Dockerfile:33-40, 60-66` |
| `.github/workflows/scoreboard-tests.yml` | change: add `"packages/url4/**"` to both `paths` lists; add `tests/unit/registry/test_system_registry_postgres.py` to the `postgres` job | `scoreboard-tests.yml:3-11, 166-174` |
| `.github/workflows/dev-build-scoreboard.yml` | change: add `"packages/url4/**"` to `paths` | `dev-build-scoreboard.yml:9-11` |
| `apps/scoreboard/DEPLOYMENT.md` | change: a short section "Backfill system names" with the dry-run and apply commands, and one sentence: heads with no `submitted_by` (stored in `disabled` mode) are reported `no_owner` and stay unlinked | `DEPLOYMENT.md:150-180` (operator commands) |
| `apps/scoreboard/tests/unit/registry/__init__.py` | create (empty) | `tests/unit/core/__init__.py` |
| `apps/scoreboard/tests/unit/registry/conftest.py` | create: `FakeFingerprinter`, `registry` fixture | `tests/unit/scores/conftest.py` |
| `apps/scoreboard/tests/unit/registry/test_names.py` | create: SR-13 (suggestion half), SR-16, SR-17 | `tests/unit/core/auth/test_cloudflare_identity.py` |
| `apps/scoreboard/tests/unit/registry/test_pins.py` | create: SR-20 (parse half) | same |
| `apps/scoreboard/tests/unit/registry/test_service.py` | create: SR-1, SR-6 to SR-11, SR-12 (SQLite half), SR-13, SR-18, SR-19, SR-20 (resolve half), SR-H3-SB (service half) | `tests/unit/scores/test_store.py` |
| `apps/scoreboard/tests/unit/registry/test_url4_fingerprinter.py` | create: SR-5-SB, SR-H3-SB (adapter half), SR-19 (adapter half) | — |
| `apps/scoreboard/tests/unit/registry/test_system_registry_postgres.py` | create: SR-12, SR-14, SR-15 on PostgreSQL | `tests/unit/test_delete_scores_postgres.py:1-165` |
| `apps/scoreboard/tests/unit/test_backfill_systems.py` | create: BF-1 to BF-7 | `tests/unit/test_retire_benchmark_cli.py`, `tests/unit/test_delete_scores_cli.py` |
| `apps/scoreboard/tests/unit/guards/test_scoreboard_layering.py` | create: C11-SB-1 to C11-SB-3 | `tests/unit/guards/test_visibility_exit_guard.py` (AST walk) |

## 4. Signatures and data shapes

### 4.1 Hexagonal layout

```
core/registry  (pure: stdlib only)       ports: SystemRegistry (inbound), SystemRepository,
                                                SystemFingerprinter (outbound)
    ^                ^
adapters/url4_fingerprinter.py           implements SystemFingerprinter with url4.fingerprint
scores/system_registry_store.py          implements SystemRepository with Tortoise
backfill_systems.py, main.py             composition (they choose the adapters)
```

`core/registry` imports only the standard library and itself. It never imports `tortoise`,
`fastapi`, `pydantic`, `url4`, `scoreboard.scores`, `scoreboard.routes` or
`scoreboard.adapters` (C11-SB-2).

### 4.2 `core/registry/model.py`

```python
BoardVisibility = Literal["public", "private"]
ResolutionOutcome = Literal["new", "existing", "renamed_notice", "revision", "private"]

@dataclass(frozen=True)
class SystemIdentity:
    fingerprint: str          # 64 lowercase hex
    candidate_url4: str       # canonical text; sha256(candidate_url4) == fingerprint

@dataclass(frozen=True)
class SystemRef:
    id: UUID
    name: str
    owner: str

@dataclass(frozen=True)
class RevisionRef:
    id: UUID
    system: SystemRef
    revision: int
    fingerprint: str
    candidate_url4: str
    created_at: datetime

@dataclass(frozen=True)
class SystemAlreadyNamed:
    name: str
    owner: str                # RAW identity. SB-submit publishes it with the SubmittedBy rule.
    code: Literal["system_already_named"] = "system_already_named"

@dataclass(frozen=True)
class Resolution:
    # PRD §3.1 shape `Resolution(system, revision, notice | None)`, plus `outcome` and `identity`.
    outcome: ResolutionOutcome
    identity: SystemIdentity
    system: SystemRef | None          # None only when outcome == "private"
    revision: RevisionRef | None      # None only when outcome == "private"
    notice: SystemAlreadyNamed | None

@dataclass(frozen=True)
class NamePin:
    name: str

@dataclass(frozen=True)
class RevisionPin:
    name: str
    revision: int

@dataclass(frozen=True)
class DatePin:
    name: str
    at: datetime              # UTC, tz-aware

Pin = NamePin | RevisionPin | DatePin
```

SR-1 rule: no parameter of `resolve_for_submit` (or of any other service method) is a
fingerprint. The fingerprint is always recomputed from `linked_url4`.

In every `Resolution` that is not `private`, `system == revision.system`.

### 4.3 `core/registry/errors.py`

```python
class RegistryError(Exception):
    code: ClassVar[str]

class InvalidSystemName(RegistryError):      # code "invalid_system_name"   (SB-submit → 422)
    def __init__(self, rule: str, message: str) -> None: ...   # rule: empty|ascii|length|slash|pattern
class SystemNameTaken(RegistryError):        # code "system_name_taken"     (→ 409)
    def __init__(self, name: str, suggestion: str) -> None: ...
class NotSystemOwner(RegistryError):         # code "not_system_owner"      (→ 403)
    def __init__(self, name: str) -> None: ...
class SystemNotFound(RegistryError):         # code "system_not_found"      (→ 404)
    def __init__(self, name: str) -> None: ...
class InvalidUrl4(RegistryError):            # code "invalid_url4"          (→ 422)
    def __init__(self, message: str) -> None: ...
class Url4TooLarge(RegistryError):           # code "url4_too_large"        (→ 422, D7 X-22)
    def __init__(self, size: int, limit: int) -> None: ...   # size and limit in characters
class InvalidPin(RegistryError):             # code "invalid_replay_pin"    (SB-grants → 422)
    def __init__(self, pin: str, message: str) -> None: ...
class PinNotFound(RegistryError):            # code "replay_pin_not_found"  (SB-grants → 404)
    def __init__(self, pin: str) -> None: ...
class RegistryConflict(RegistryError):       # code "registry_conflict"     (→ 409, retry)
    """A write lost a race twice. The caller may retry the request."""
class RegistryWriteConflict(Exception):
    """Raised by a SystemRepository adapter when a unique constraint rejects a write.
    Not a RegistryError: the service catches it and never lets it escape."""
```

The HTTP status in the comments is the mapping SB-submit / SB-grants apply. The core holds
no HTTP knowledge.

### 4.4 `core/registry/names.py`

```python
SYSTEM_NAME_MAX = 64
_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")   # erd.md §2.3.1

def normalize_system_name(raw: str) -> str: ...
def suggest_name(name: str, fingerprint: str) -> str: ...
```

`normalize_system_name` checks, in this order, and raises `InvalidSystemName(rule, message)`:

1. `raw == ""` → `("empty", "a system name must not be empty")`.
2. `not raw.isascii()` → `("ascii", "a system name must use only ASCII letters, digits, '.', '_' and '-'")`.
   WHY before `lower()`: `"K".lower()` is the ASCII `"k"` (KELVIN SIGN). Lowercasing first
   would let a non-ASCII input become a valid ASCII name, which SR-D9 forbids.
3. `len(raw) > 64` → `("length", "a system name must be at most 64 characters")`.
4. `"/" in raw` → `("slash", "a system name must not contain '/'")`.
5. `name = raw.lower()`; `not _NAME_RE.fullmatch(name)` → `("pattern", "a system name must start and end with a letter or digit, and use only a-z, 0-9, '.', '_' and '-'")`.
6. Return `name`. Do not strip whitespace (a space fails rule 5).

`suggest_name(name, fingerprint)`: `base = name[:59].rstrip("._-")`; return
`f"{base}-{fingerprint[:4]}"` (PRD SR-13 GREEN note). The result always matches `_NAME_RE` and
is at most 64 chars. It does not check that the suggestion is free (OD-R4).

### 4.5 `core/registry/pins.py`

```python
def parse_pin(raw: str) -> Pin: ...
```

1. `name_part, sep, qualifier = raw.partition("@")`.
2. `name = normalize_system_name(name_part)`; on `InvalidSystemName` raise
   `InvalidPin(raw, exc.message)`. (So `result:<uuid>` fails here in this unit; SB-grants adds
   those forms before this step.)
3. No `@` → `NamePin(name)`. `@` with an empty qualifier → `InvalidPin(raw, "empty pin qualifier")`.
4. Qualifier matches `^r([1-9][0-9]{0,8})$` → `RevisionPin(name, int(group))`. `r0`, `r01`,
   `r-1` → not this rule → fall to 5 and fail there.
5. Qualifier matches `^\d{4}-\d{2}-\d{2}$` → `date.fromisoformat`; `at =
   datetime.combine(d, time(23, 59, 59, 999999), tzinfo=UTC)` (RP-D7: "a date-only T means the
   end of that day, UTC").
6. Else `datetime.fromisoformat(qualifier)`; `tzinfo is None` → `InvalidPin(raw, "a pin time
   needs a UTC offset")`; else `at = value.astimezone(UTC)`.
7. Any `ValueError` in 5 or 6 → `InvalidPin(raw, "not a revision (r<N>) or an ISO-8601 date")`.

### 4.6 `core/registry/ports.py`

```python
class SystemFingerprinter(Protocol):
    def identify(self, linked_url4: str) -> SystemIdentity:
        """Raise InvalidUrl4 when the text is not a url4 expression."""

# `connection` is typed `object | None` so the core stays free of Tortoise. The adapter casts
# it to `BaseDBAsyncClient`. None means "the default connection".
class SystemRepository(Protocol):
    async def find_revision_by_fingerprint(
        self, fingerprint: str, *, connection: object | None = None
    ) -> RevisionRef | None: ...
    async def find_system_by_name(
        self, name: str, *, connection: object | None = None
    ) -> SystemRef | None: ...
    async def create_system_with_first_revision(
        self, *, name: str, owner: str, identity: SystemIdentity, connection: object | None = None
    ) -> RevisionRef: ...                       # raises RegistryWriteConflict
    async def create_next_revision(
        self, *, system: SystemRef, identity: SystemIdentity, declared_by: str,
        connection: object | None = None,
    ) -> RevisionRef: ...                       # raises RegistryWriteConflict
    async def list_revisions(
        self, system_id: UUID, *, connection: object | None = None
    ) -> list[RevisionRef]: ...                 # by revision ASC

class SystemRegistry(Protocol):
    # The three operations of PRD §3.1, with the PRD parameter names and order.
    async def resolve_for_submit(
        self,
        linked_url4: str,
        requested_name: str,          # SB-submit passes the submission's spec_id
        revision_of: str | None,
        submitter: str,               # the verified cloudflare_headers identity (D5); never None
        board_visibility: BoardVisibility,
        *,
        connection: object | None = None,
    ) -> Resolution: ...
    async def resolve_pin(
        self, pin: str, *, connection: object | None = None
    ) -> RevisionRef | list[RevisionRef]: ...
    def fingerprint(self, linked_url4: str) -> str: ...   # pure: identify(...).fingerprint
```

Deviation from PRD §3.1, stated on purpose: `resolve_pin` takes no `benchmark_id`. The
registry is system-scoped; the benchmark picks a **head**, and heads belong to SB-grants
(RP-6 to RP-8). SB-grants adds the benchmark filter on top. An unknown name or revision raises
`PinNotFound` (code `replay_pin_not_found`), not `SystemNotFound`; a bad pin raises `InvalidPin`.

Transaction rule: the submit flow calls the registry inside its own
`async with in_transaction() as conn:` block and passes `connection=conn` (SB-submit plan
§"store", C4). The service passes `connection` through to every repository call unchanged.
The adapter runs every read with `.using_db(connection)` (`using_db(None)` keeps the default,
`tortoise/queryset.py:1112-1119`). For a write it opens `async with in_transaction() as sp:`.
Tortoise binds the caller's transaction to the task context
(`tortoise/backends/base/client.py:336-346`), so this nested `in_transaction()` becomes a
SAVEPOINT on that same transaction (`tortoise/transactions.py:33-44`,
`tortoise/backends/base/client.py:365-383`); the writes use `using_db=sp`.
INVARIANT (docstring of the adapter): a non-None `connection` must be the transaction that the
current task opened with `in_transaction()`. When `connection` is None, the write opens its
own top-level transaction (the backfill command and the unit tests).

### 4.7 `core/registry/service.py`

```python
MAX_URL4_CHARS = 32_000   # D7 X-22: the existing ScoreSubmission cap (scores/schemas.py:378), 422

class RegistryService:
    def __init__(self, repository: SystemRepository, fingerprinter: SystemFingerprinter) -> None: ...
    async def resolve_for_submit(
        self, linked_url4: str, requested_name: str, revision_of: str | None, submitter: str,
        board_visibility: BoardVisibility, *, connection: object | None = None,
    ) -> Resolution: ...
    async def resolve_pin(
        self, pin: str, *, connection: object | None = None
    ) -> RevisionRef | list[RevisionRef]: ...
    def identify(self, linked_url4: str) -> SystemIdentity: ...   # size check + fingerprinter
    def fingerprint(self, linked_url4: str) -> str: ...           # return self.identify(linked_url4).fingerprint
```

`fingerprint` is the PRD §3.1 pure operation. SB-submit calls it for the private-board cluster
key (erd.md §2.4). It raises `Url4TooLarge` and `InvalidUrl4` like `identify`.

`identify`: `size = len(linked_url4)` (characters, the same unit as the pydantic
`max_length=32_000` at `scores/schemas.py:378`); `size > MAX_URL4_CHARS` →
`Url4TooLarge(size, MAX_URL4_CHARS)` **before** the fingerprinter runs (SR-19). Else
`self._fingerprinter.identify(linked_url4)`.

WHY the service keeps its own check when the route already caps the field (D7 X-22): the
backfill and any later caller do not go through `ScoreSubmission`. Both caps are the same
number and the same unit, so the client sees one rule: over 32,000 chars is a `422`. Through
`POST /v1/scores` the pydantic check fires first; the service check is the guard for the other
callers.

`resolve_for_submit`, in this order:

1. `identity = self.identify(linked_url4)`.
2. `board_visibility == "private"` → return `Resolution("private", identity, None, None, None)`.
   No repository call at all (SR-11, I-N4). SB-submit stores the fingerprint in
   `Score.metadata.system_fingerprint` (erd.md §2.4).
3. `name = normalize_system_name(revision_of if revision_of is not None else requested_name)`.
   When `revision_of` is given, it names the system; `requested_name` is not read (OD-R2).
4. Loop `for attempt in (1, 2):`
   1. `existing = await repo.find_revision_by_fingerprint(identity.fingerprint)`.
      Found → return `_existing(existing, name)`:
      `existing.system.name == name` → `Resolution("existing", identity, existing.system, existing, None)`;
      else `Resolution("renamed_notice", identity, existing.system, existing, SystemAlreadyNamed(existing.system.name, existing.system.owner))`.
      A known fingerprint always wins, also with `revision_of` (I-N2; OD-R3).
   2. `try:` `revision_of` given → `return await self._declare_revision(name, identity, submitter, connection)`;
      else → `return await self._claim(name, identity, submitter, connection)`.
   3. `except RegistryWriteConflict:` on attempt 2 → `raise RegistryConflict(...)`; else
      continue (the loop re-reads by fingerprint, then by name).
5. `_claim(name, identity, submitter)`: `find_system_by_name(name)` found → raise
   `SystemNameTaken(name, suggest_name(name, identity.fingerprint))` (SR-E3; also when the owner
   is the submitter — the owner must use `revision_of`). Else
   `create_system_with_first_revision(name=name, owner=submitter, identity=identity, connection=connection)` →
   `Resolution("new", identity, rev.system, rev, None)`.
6. `_declare_revision(name, identity, submitter)`: `find_system_by_name(name)` is None →
   `SystemNotFound(name)` (SR-E4). `system.owner != submitter` → `NotSystemOwner(name)` (SR-E1),
   checked **before** any write. Else `create_next_revision(system=system, identity=identity,
   declared_by=submitter, connection=connection)` → `Resolution("revision", identity, rev.system, rev, None)`.

How the retry covers the races:

- SR-D2 (same new fingerprint, names `a` and `b`): the loser's insert of its `SystemRevision`
  hits `UNIQUE(fingerprint)`; the adapter's savepoint rolls back its `System("b")` row too;
  attempt 2 finds the winner by fingerprint → `renamed_notice`.
- SR-D3 (two fingerprints, one new name): the loser hits `UNIQUE(name)`; attempt 2 finds no
  revision for its fingerprint, finds the name → `SystemNameTaken`.
- SR-D4 (two revisions of one system): the loser hits `UNIQUE(system_id, revision)`; attempt 2
  re-reads the max and inserts N+2.

`resolve_pin(pin, *, connection=None)`: `parsed = parse_pin(pin)`; `system = await repo.find_system_by_name(parsed.name, connection=connection)`,
None → `PinNotFound(pin)`; `revisions = await repo.list_revisions(system.id, connection=connection)`;
`NamePin` → `revisions[-1]`; `RevisionPin` → the one with that number, else `PinNotFound`;
`DatePin` → `revisions` (all of them; SB-grants picks the result by date, PRD SR-H5).

Keep every function under the caps (`pyproject.toml:33-40`: complexity 8, statements 26,
branches 7, returns 3). Split `_existing`, `_claim`, `_declare_revision`, `_resolve_named_pin`.

### 4.8 `adapters/url4_fingerprinter.py`

```python
import hashlib

import url4
from url4.fingerprint import CANDIDATE_BINDING, canonical_system_url4

SDK_METADATA_BINDINGS: frozenset[str] = frozenset({"_sf_recipe"})
"""Root-level Candidate bindings that are SDK metadata, not part of the system (D3).

Mirrors `_SOURCE_NAME` in packages/screamingface/src/screamingface/_evaluation/topology.py:14.
C11 forbids the SDK import, so the value is mirrored. SR-5-SB pins it against the
`exclude_bindings` list of packages/url4/tests/fixtures/fingerprint_vectors.json.
"""

class Url4Fingerprinter:
    """SystemFingerprinter over the pure url4.fingerprint helper (C11: the one url4 import site)."""
    def identify(self, linked_url4: str) -> SystemIdentity:
        try:
            candidate = canonical_system_url4(
                linked_url4, CANDIDATE_BINDING, exclude_bindings=SDK_METADATA_BINDINGS
            )
        except url4.Url4Error as exc:
            raise InvalidUrl4(str(exc)) from exc
        return SystemIdentity(
            fingerprint=hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
            candidate_url4=candidate,
        )
```

The value is the D3 formula:
`system_fingerprint(linked, binding="candidate", exclude_bindings=frozenset({"_sf_recipe"}))`.
WHY `canonical_system_url4` plus a local sha256 and not two calls: one parse, and URL4-fp
guarantees `sha256(candidate_url4) == system_fingerprint(linked, ...)` for equal arguments
(URL4-fp plan §4.2). SR-5-SB checks both values against the vectors, and it also calls
`system_fingerprint` with the D3 arguments directly, so any drift fails.

Rules:

- Pass `exclude_bindings=SDK_METADATA_BINDINGS` on every call. Never call a url4 fingerprint
  function with the default empty set in the scoreboard: the recipe display name would then
  change the fingerprint, and SR-H3 would never fire for SDK recipes (a rename would dodge
  clustering, SR-D1 risk).
- Keep `SDK_METADATA_BINDINGS` in the adapter, not in `core/registry`. The core does not know
  the url4 shape.
- `SystemRevision.candidate_url4` stores the canonical system text **after** the exclude (no
  `_sf_recipe` source). This is the text a replay grant later names; it holds no display name.

### 4.9 `scores/system_registry_store.py`

```python
class TortoiseSystemRepository:
    # Every public method has the exact SystemRepository signature of §4.6, incl. `connection`.
    async def find_revision_by_fingerprint(self, fingerprint, *, connection=None) -> RevisionRef | None
    async def find_system_by_name(self, name, *, connection=None) -> SystemRef | None
    async def create_system_with_first_revision(self, *, name, owner, identity, connection=None) -> RevisionRef
    async def create_next_revision(self, *, system, identity, declared_by, connection=None) -> RevisionRef
    async def list_revisions(self, system_id, *, connection=None) -> list[RevisionRef]
    async def _next_revision_number(self, connection: BaseDBAsyncClient, system_id: UUID) -> int
```

- Reads (each with `.using_db(db)`, `db = cast(BaseDBAsyncClient | None, connection)`):
  `SystemRevision.filter(fingerprint=…).select_related("system").first()`,
  `System.filter(name=…).first()`, `SystemRevision.filter(system_id=…).select_related("system").order_by("revision")`.
  Map rows to the frozen `*Ref` types (never return a Tortoise object from the adapter).
- Writes: the `try` goes **outside** the savepoint, so the savepoint is rolled back before the
  error is mapped:

  ```python
  try:
      async with in_transaction() as connection:
          system = await System.create(using_db=connection, name=name, owner=owner)
          revision = await SystemRevision.create(
              using_db=connection, system=system, revision=1,
              fingerprint=identity.fingerprint, candidate_url4=identity.candidate_url4,
              declared_by=owner,
          )
  except IntegrityError as exc:
      raise RegistryWriteConflict(str(exc)) from exc
  ```

  WHY: on PostgreSQL a failed statement aborts the whole transaction until a
  `ROLLBACK TO SAVEPOINT`. The nested context does that rollback on exit
  (`tortoise/backends/base/client.py:377-383`), and the caller's outer transaction stays
  usable. Under READ COMMITTED the next read then sees the winner's committed row.
- `create_next_revision`: in the savepoint, `number = await self._next_revision_number(connection, system.id)`
  (`max(revision) + 1`, via `order_by("-revision").first()`), then create. Same
  `IntegrityError` mapping. The PostgreSQL race test wraps `_next_revision_number`.

### 4.10 `backfill_systems.py` (erd.md §6.4)

Command form: `python -m scoreboard.backfill_systems --dry-run` or `--apply` (a required,
mutually exclusive group). WHY not `scoreboard backfill-systems` (erd.md §6.4): the `scoreboard`
console script starts uvicorn only (`cli.py:8-15`); every operator command in this app is a
`python -m scoreboard.<module>` (`DEPLOYMENT.md:150, 171, 336, 355`). See OD-R7.

```python
BackfillAction = Literal[
    "claim", "link", "already_linked", "clash", "duplicate_head",
    "name_mismatch", "invalid_name", "invalid_url4", "no_owner",
]

@dataclass(frozen=True)
class BackfillRow:
    action: BackfillAction
    score_id: UUID
    benchmark_id: str
    name: str | None
    detail: str

async def backfill_systems(
    *, apply: bool, repository: SystemRepository, registry: RegistryService
) -> list[BackfillRow]: ...
def format_report(rows: Sequence[BackfillRow], *, applied: bool) -> str: ...
def main(argv: Sequence[str] | None = None) -> None: ...
```

Algorithm (one pass, heads ordered by `submitted_at`, then `id`):

1. Heads = `Score` rows with `system_revision_id IS NULL` whose benchmark is public
   (`visibility == "public"` or `visibility IS NULL`, the NULL-is-public rule at
   `store.py:88-90`). Private heads are never read (I-N4).
2. For each head, keep in memory: `planned_revisions: dict[fingerprint, RevisionRef | "planned"]`,
   `planned_names: dict[name, fingerprint]`, `linked_keys: set[(benchmark_id, benchmark_revision, fingerprint)]`.
3. `identity = registry.identify(head.url4_expression)`; `InvalidUrl4` / `Url4TooLarge` →
   row `invalid_url4`, next head.
4. `name = normalize_system_name(head.spec_id)`; `InvalidSystemName` → row `invalid_name`.
5. `head.submitted_by is None` → row `no_owner` (a `System.owner` is NOT NULL).
6. Revision for the fingerprint = planned, or `repository.find_revision_by_fingerprint`.
   - None: the name is in `planned_names` or `find_system_by_name(name)` finds it → row `clash`
     (the name belongs to another fingerprint; report, never apply). Else row `claim`; with
     `--apply`, `create_system_with_first_revision(name, owner=head.submitted_by, identity)`
     (a `RegistryWriteConflict` becomes row `clash`).
   - Found, and its system name != `name` → row `name_mismatch` (the head is not linked).
7. Link rule (only after a `claim`, or for a found revision whose name == `name`): when
   `(benchmark_id, benchmark_revision, fingerprint)` is already in `linked_keys`, or a head with
   that `system_revision_id` already exists on that board and revision → row `duplicate_head`
   (not linked). Else row `link`; with `--apply`,
   `Score.filter(id=head.id, system_revision_id=None).update(system_revision_id=rev.id)`.
8. **Never** change `spec_id`, `score`, `content_hash` or any ranked column. **Never** merge two
   heads. So `ScoreStore.leaderboard()` returns the same rows before and after (erd.md §6.4).
9. `--apply` wraps each head's writes in its own `in_transaction()`. A rerun skips linked heads
   (step 1) and reuses registered fingerprints (step 6), so it is idempotent.

`main` follows `retire_benchmark.py:161-212`: parse args, `asyncio.run(_run(...))`, where
`_run` calls `init_db(Settings().database_url)`, builds `TortoiseSystemRepository()` and
`RegistryService(repository, Url4Fingerprinter())`, calls `backfill_systems`, prints
`format_report`, and always calls `close_db()`. Print a first line `DRY RUN — nothing written`
or `APPLIED`, then one tab-separated line per row, then counts per action.

### 4.11 Dockerfile (mirror the engine layout)

Builder stage, replacing `COPY apps/scoreboard/pyproject.toml …` to the second `uv sync`:

```dockerfile
WORKDIR /app
# All path dependencies must exist before `uv sync` resolves the lockfile.
COPY packages/url4 ./packages/url4
COPY apps/scoreboard/pyproject.toml apps/scoreboard/uv.lock ./apps/scoreboard/
WORKDIR /app/apps/scoreboard
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev
COPY apps/scoreboard/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev
```

Runtime stage: replace `COPY --from=builder … /app /app` with
`COPY --from=builder --chown=scoreboard:scoreboard /app/packages/url4 /app/packages/url4` and
`COPY --from=builder --chown=scoreboard:scoreboard /app/apps/scoreboard /app/apps/scoreboard`,
set `WORKDIR /app/apps/scoreboard`, and set `PATH="/app/apps/scoreboard/.venv/bin:$PATH"`.
Keep the portal and artifact `COPY` lines and `SCOREBOARD_PORTAL_DIR` unchanged. Add an
INVARIANT comment: the build context is the repo root, and the editable install resolves
through the mirrored paths (copy the wording of `apps/screamingface-engine/Dockerfile:11-16`).
The chart's migrate Job passes `-c scoreboard.db.TORTOISE_CONFIG`
(`charts/scoreboard/templates/job-migrate.yaml:37-42`), so the new working directory does not
change it.

### 4.12 Ed25519 JWS

None in this unit.

## 5. Migrations

None. SB-schema owns every table and column this unit uses (`system`, `system_revision`,
`scores.system_revision_id`). If `uv run tortoise makemigrations` writes a file, stop and ask.

## 6. TDD order (RED first, in risk order)

Pre-step (no test): `cd apps/scoreboard && uv add --editable ../../packages/url4`, then
`uv lock`. Check `git diff uv.lock`: the only change is the new `url4` package entry (its
`httpx` requirement is already locked). If any other package version moves, stop and ask.
Then create every module of §3 with the signatures and `raise NotImplementedError` bodies, so
each RED fails on an assertion or on `NotImplementedError`, never on an import error. The
adapter stub already defines the constant `SDK_METADATA_BINDINGS = frozenset({"_sf_recipe"})`
(rows 19, 19a and 19b import it), and `MAX_URL4_CHARS = 32_000` is in the service stub.

`tests/unit/registry/conftest.py`:

```python
class FakeFingerprinter:
    """Deterministic SystemFingerprinter: text 'invalid!' raises InvalidUrl4, else sha256(text)."""
    def identify(self, linked_url4: str) -> SystemIdentity: ...

@pytest_asyncio.fixture
async def registry(tortoise_db: None) -> RegistryService:
    return RegistryService(TortoiseSystemRepository(), FakeFingerprinter())
```

Test oracles come from the PRD scenarios (test-plan §1 rule 6): names `kevins-best`,
`opus-5.5`, owners `kevin@x.org`, `ana@x.org`, `bruno@y.org`.

| # | Id | File :: test name | RED reason |
|---|---|---|---|
| 1 | C11-SB-1 | `guards/test_scoreboard_layering.py::test_c11_scoreboard_never_imports_the_sdk` | Guard: green on day one (no import exists). Write it first; it stays green. AST-walk every `src/scoreboard/**/*.py`; fail on `import screamingface` / `from screamingface…` (top-level name exactly `screamingface`). |
| 2 | C11-SB-2 | `…::test_c11_registry_core_imports_only_the_standard_library` | Guard, green when §4.1 holds. It fails when any `core/registry` module imports `tortoise`, `fastapi`, `pydantic`, `url4`, `scoreboard.scores`, `scoreboard.routes` or `scoreboard.adapters`. To prove it bites, put the checker in a helper `_forbidden_imports(source: str, banned: set[str]) -> list[str]` and also assert that it reports `import tortoise` in a literal source string. |
| 3 | C11-SB-3 | `…::test_c11_only_the_adapter_imports_url4` | Same shape: only `scoreboard/adapters/url4_fingerprinter.py` may import `url4`. |
| 4 | SR-1 | `test_service.py::test_sr1_fingerprint_ignores_client_supplied_value` | `NotImplementedError`. Seed Ana's system for fingerprint of text `U_A`. Assert `inspect.signature(RegistryService.resolve_for_submit)` has no parameter whose name contains `fingerprint`. Resolve `U_B` with name `kevins-best` → outcome `new`, a revision whose fingerprint == `sha256(U_B)`, and Ana's system untouched. |
| 5 | SR-6 | `test_sr6_new_fingerprint_new_name_creates_system_rev1` | `NotImplementedError`. Assert `System(name="kevins-best", owner="kevin@x.org")`, `SystemRevision(revision=1, fingerprint=F, declared_by="kevin@x.org", candidate_url4=…)`, outcome `new`, `notice is None`. |
| 6 | SR-7 | `test_sr7_known_fingerprint_reuses_name_no_rows` | Second resolve of F with `opus-5.5` by Bruno → outcome `existing`, same revision id, row counts unchanged. |
| 7 | SR-8 | `test_sr8_known_fingerprint_other_name_returns_notice` | F named `opus-5.5` by Ana; Bruno sends `bruno-opus` → outcome `renamed_notice`, `notice == SystemAlreadyNamed("opus-5.5", "ana@x.org")`. |
| 8 | SR-9 | `test_sr9_owner_declares_revision_two` | Kevin owns `kevins-best` rev 1 (F1); Kevin sends F2 with `revision_of="kevins-best"` → outcome `revision`, `revision == 2`. |
| 9 | SR-10 | `test_sr10_non_owner_revision_rejected_403_no_write` | Bruno sends F2 with `revision_of="kevins-best"` → `NotSystemOwner`; `SystemRevision` count unchanged. |
| 10 | SR-11 | `test_sr11_private_board_never_writes_registry` | Use a `SystemRepository` spy (every method raises `AssertionError`) → outcome `private`, `revision is None`, identity present; no spy call. |
| 11 | SR-13 | `test_service.py::test_sr13_taken_name_by_other_system_409_with_suggestion` and `test_names.py::test_sr13_suggestion_shape` | `SystemNameTaken` with `suggestion == f"opus-5.5-{F2[:4]}"`; a 64-char name gives a ≤ 64-char suggestion that passes `normalize_system_name`. |
| 12 | SR-18 | `test_sr18_revision_of_unknown_404` | `revision_of="nope"` → `SystemNotFound`. |
| 13 | SR-19 | `test_service.py::test_sr19_unparseable_url4_422_and_oversize_422` and `test_url4_fingerprinter.py::test_sr19_adapter_maps_url4_errors` | `NotImplementedError`. `"invalid!"` → `InvalidUrl4`; `"a" * 32_001` → `Url4TooLarge` with `size == 32_001`, `limit == 32_000`, and the fake records **no** call (size check first); `"a" * 32_000` is accepted; `"é" * 32_000` (64,000 UTF-8 bytes) is accepted too (the cap counts characters, like `scores/schemas.py:378`). Both error classes carry the code that SB-submit maps to `422` (D7 X-22): assert `InvalidUrl4.code == "invalid_url4"` and `Url4TooLarge.code == "url4_too_large"`. Adapter: `monkeypatch.setattr(scoreboard.adapters.url4_fingerprinter, "canonical_system_url4", <raise url4.ParseError("bad")>)` (the adapter imported the name, so patch it there, not in `url4.fingerprint`) → `InvalidUrl4`. |
| 14 | SR-16 | `test_names.py::test_sr16_name_rules_boundaries` (parametrized) | `normalize_system_name` stub returns the input. Cases: `""` → empty; `"a"` ok; 64 × `"a"` ok; 65 × `"a"` → length; `"a/b"` → slash; `"-abc"`, `"abc-"`, `"a..b."` → pattern; `"Opus-5.5"` → `"opus-5.5"`; `" opus"` → pattern. Assert the `rule` attribute. |
| 15 | SR-17 | `test_names.py::test_sr17_non_ascii_name_rejected` | Cases: `"opus-5.5é"`, `"оpus"` (Cyrillic о), `"Kevins-best"` (KELVIN SIGN) → rule `ascii`. |
| 16 | SR-20 | `test_pins.py::test_sr20_resolve_pin_forms` (parse) and `test_service.py::test_sr20_resolve_pin_forms` (resolve) | Parse: `"kevins-best"` → `NamePin`; `"kevins-best@r1"` → `RevisionPin(…, 1)`; `"kevins-best@2026-09-01"` → `DatePin(at=2026-09-01T23:59:59.999999Z)`; `"Kevins-Best@2026-09-01T10:00:00+02:00"` → name lowercased, `at=08:00Z`; `"x@r0"`, `"x@"`, `"x@2026-13-01"`, `"x@2026-09-01T10:00:00"` (no offset), `"result:0b…"` → `InvalidPin`. Resolve with revisions 1 and 2: name → rev 2; `@r1` → rev 1; `@r3` → `PinNotFound`; date → `[rev1, rev2]`; unknown name → `PinNotFound`. |
| 17 | SR-12 (SQLite) | `test_service.py::test_sr12_lost_race_on_first_submit_resolves_to_winner` | Insert the winner (`a`, F) directly. Monkeypatch the repository's `find_revision_by_fingerprint` to return `None` on its **first** call only (a stale read). Resolve F with name `b` → outcome `renamed_notice` naming `a`; `System` count 1 (the savepoint removed `b`); `SystemRevision` count 1. RED: without the retry loop the `RegistryWriteConflict` escapes. |
| 18 | SR-12 / SR-14 / SR-15 (PostgreSQL) | `registry/test_system_registry_postgres.py::test_sr12_concurrent_first_submits_one_revision`, `::test_sr14_concurrent_name_claims_one_winner`, `::test_sr15_concurrent_revisions_contiguous` | `skipif(not DATABASE_URL.startswith("postgres"))`, own `Tortoise.init(config=build_tortoise_config(DATABASE_URL))` + `generate_schemas(safe=True)`, clean up only its own rows (pattern `test_delete_scores_postgres.py:70-116`). Use per-run unique names (`f"sr12-{uuid4().hex[:8]}"`). Two tasks, each `async with in_transaction(): await service.resolve_for_submit(...)`, run with `asyncio.gather(..., return_exceptions=True)`. Each task passes its own `conn` as `connection=conn`. Force the overlap with `asyncio.Barrier(2)`: SR-12 and SR-14 wrap `find_revision_by_fingerprint`, SR-15 wraps `TortoiseSystemRepository._next_revision_number`; the wrapper first calls the real method, then awaits the barrier, on its **first** call per task only (so both tasks have read before either writes; a barrier before the read would let one task commit first and hide the race). Assert: SR-12 one `SystemRevision` for F, results `{new, renamed_notice}`; SR-14 one `System` with that name, one result is `SystemNameTaken`; SR-15 revisions `[1, 2, 3]`. Add the module to the CI `postgres` job (the guard at `tests/unit/guards/test_postgres_regressions_run_in_ci.py` requires it). |
| 19 | SR-5-SB | `test_url4_fingerprinter.py::test_sr5_url4_fingerprinter_matches_golden_vectors` | `NotImplementedError` in the adapter stub. Read `Path(__file__).resolve().parents[5] / "packages/url4/tests/fixtures/fingerprint_vectors.json"` (a module-level helper `_vectors()`; rows 19a and 19b reuse it). Assert `schema == "url4.fingerprint.vectors.v1"`, 50 vectors, `binding == "candidate"`, and `frozenset(data["exclude_bindings"]) == SDK_METADATA_BINDINGS` (D3: one call shape on both sides). For each vector (parametrize, `ids=` from `id`): `Url4Fingerprinter().identify(v["linked_url4"])` gives `fingerprint` and `candidate_url4` equal to the file, and `url4.fingerprint.system_fingerprint(v["linked_url4"], binding="candidate", exclude_bindings=frozenset({"_sf_recipe"})) == v["fingerprint"]` (the D3 formula, called directly). A second RED, after the stub: an adapter that omits `exclude_bindings` fails on the 10 vectors `c08-*` and `c09-*` (assertion: the recipe blob is in the hash). |
| 19a | SR-H3-SB (adapter) | `test_url4_fingerprinter.py::test_sr_h3_sdk_recipe_rename_is_one_identity` | `NotImplementedError` in the adapter stub. From `_vectors()`, take `c08-b1` and `c09-b1` (the SDK-shaped twin: they differ only in the `_sf_recipe` `name`/`named` keys; URL4-fp §4.3). Assert their `linked_url4` values differ, `identify` gives one `SystemIdentity` for both, and `"_sf_recipe" not in identity.candidate_url4`. Also `c08-b1` and `c09-b3` (twin on another benchmark) → the same identity. |
| 19b | SR-H3-SB (service) | `test_service.py::test_sr8_h3_sdk_recipe_rename_returns_notice` | `NotImplementedError`. A `RegistryService(TortoiseSystemRepository(), Url4Fingerprinter())` (the real adapter, not the fake; build it in the test, not in the `registry` fixture). Ana (`ana@x.org`) resolves `c08-b1` `linked_url4` with `requested_name="opus-5.5"`, public board → outcome `new`. Bruno (`bruno@y.org`) resolves `c09-b3` `linked_url4` (same system, other recipe name, other benchmark) with `requested_name="bruno-opus"` → outcome `renamed_notice`, `notice == SystemAlreadyNamed("opus-5.5", "ana@x.org")`, `revision.revision == 1`, `System` count 1, `SystemRevision` count 1 (PRD SR-H3). A second RED, after the stub: an adapter with no exclude set gives outcome `new` for Bruno (assertion). |
| 20 | BF-1 | `test_backfill_systems.py::test_bf1_dry_run_writes_nothing` | `NotImplementedError`. Seed 3 public legacy heads; dry run → rows `claim`/`link`, and `System`, `SystemRevision` counts are 0, every `system_revision_id` NULL. |
| 21 | BF-2 | `test_bf2_earliest_head_claims_its_spec_id` | Two heads, same fingerprint, boards B1 and B2, same `spec_id`, earlier on B1 → one `System(name=spec_id, owner=<earlier submitter>)`, both heads linked. |
| 22 | BF-3 | `test_bf3_name_clash_is_reported_not_applied` | Two heads, different fingerprints, same `spec_id` → first `claim`, second `clash`; only one `System`; the second head stays unlinked. |
| 23 | BF-4 | `test_bf4_legacy_heads_are_never_merged` | Two heads, same fingerprint, same board and revision → one `link`, one `duplicate_head`; `ScoreStore.leaderboard(...)` output is equal before and after `--apply`. |
| 24 | BF-5 | `test_bf5_private_heads_are_skipped` | A private-board head gets no row and stays unlinked; no `System` is written for it. |
| 25 | BF-6 | `test_bf6_rerun_is_idempotent` | `--apply` twice → the second run writes nothing new; row counts equal; the report has no `claim`. |
| 26 | BF-7 | `test_bf7_bad_heads_are_reported` | `spec_id="a/b"` → `invalid_name`; url4 `"invalid!"` → `invalid_url4`; `submitted_by=None` (a head stored in `disabled` mode, D5) → `no_owner`; each keeps its head unlinked. Also call `main(["--dry-run"])` with `init_db`/`close_db` monkeypatched (pattern `tests/unit/test_retire_benchmark_cli.py`) and assert the first output line is `DRY RUN — nothing written`, and `main([])` exits with argparse code 2. |

Then GREEN each in order.

## 7. Edge cases, what not to do, gates

### 7.1 Edge cases

- A known fingerprint with an invalid requested name: step 3 of §4.7 validates the name first,
  so the submit fails `invalid_system_name` (OD-R1).
- A known fingerprint sent with `revision_of`: returns the existing revision (plus a notice
  when the names differ). It never creates a second revision for one fingerprint (I-N2).
- The owner submits a new fingerprint under their own name without `revision_of`:
  `SystemNameTaken` with a suggestion. The owner must declare `revision_of`.
- A `DatePin` in the future: parsing accepts it; SB-grants resolves it to the newest (RP-D7).
- Exactly 32,000 chars: accepted. 32,001 chars: `Url4TooLarge` (`422`, D7 X-22). The cap counts
  characters, not bytes, the same as `ScoreSubmission.url4_expression`
  (`scores/schemas.py:378`). Through `POST /v1/scores` the pydantic `422` fires first.
- `System.owner` and `declared_by` are the raw verified `cloudflare_headers` identities (D5).
  Never publish them raw: SB-submit applies the `SubmittedBy` local-part rule
  (`scores/schemas.py:240-243`).
- Two SDK recipes that differ only in the display name (`sf.Model(..., name=...)`) are one
  system: the adapter drops `_sf_recipe` before the hash (D3). The second submitter gets the
  SR-H3 notice, not a new system.
- A Candidate that declares its own `seed` parameter: the seed stays in the fingerprint (D3), so
  `seed=7` and `seed=8` are two systems.
- A legacy head with `submitted_by = NULL` (stored in `disabled` mode): the backfill reports
  `no_owner` and does not link it (D5).

### 7.2 What not to do

- Do not accept, read or store a client fingerprint anywhere (SR-D1).
- Do not import `screamingface`. Do not import `url4` outside `scoreboard/adapters/` (C11).
- Do not call a url4 fingerprint function without `exclude_bindings=SDK_METADATA_BINDINGS` (D3).
- Do not add a 256 KiB cap or a `413` (D7 X-22).
- Do not read an identity header in this unit, and do not add an auth mode (D5: SB-submit
  passes the verified submitter).
- Do not import Tortoise, FastAPI or pydantic in `core/registry`.
- Do not catch `IntegrityError` inside the savepoint block (the rollback must run first).
- Do not retry more than once. Do not add a sleep to any test (test-plan §1 rule 7); force
  overlap with `asyncio.Barrier`.
- Do not change `spec_id`, ranked columns or `content_hash` in the backfill. Never merge heads.
- Do not add a route, and do not touch `routes/scores.py` (SB-submit owns the wiring).
- Do not add a migration.
- Do not edit an existing test body. Append or create.

### 7.3 Gates

Run from the `unit/SB-registry` worktree root:

```sh
uv run .claude/scripts/run_gates.py scoreboard --base e14-reproducible-submission-spec
```

Also run the url4 gate once, because the scoreboard now consumes it:
`uv run .claude/scripts/run_gates.py url4 --base e14-reproducible-submission-spec` (it must be
unchanged and green).

## 8. Verification and "done"

```sh
cd apps/scoreboard
uv lock --check
uv run pytest tests/unit/registry tests/unit/test_backfill_systems.py tests/unit/guards -v
SCOREBOARD_TEST_DATABASE_URL=postgres://scoreboard:scoreboard@localhost:5432/scoreboard_test \
  uv run pytest tests/unit/registry/test_system_registry_postgres.py -v
rm -f /tmp/sr.sqlite3 && SCOREBOARD_DATABASE_URL=sqlite:///tmp/sr.sqlite3 uv run tortoise migrate
SCOREBOARD_DATABASE_URL=sqlite:///tmp/sr.sqlite3 uv run python -m scoreboard.backfill_systems --dry-run
cd ../.. && docker build -f apps/scoreboard/Dockerfile -t scoreboard:e14 .
docker run --rm --entrypoint python scoreboard:e14 -c "import url4.fingerprint, scoreboard.adapters.url4_fingerprinter"
uv run .claude/scripts/run_gates.py scoreboard --base e14-reproducible-submission-spec
```

Done when: every test in §6 is green (the PostgreSQL module green locally against the
PostgreSQL URL above, and listed in the CI `postgres` job), the guards are green,
`uv lock --check` passes, the image builds and imports `url4`, the full suite and gates are
green with coverage ≥ 80%, and the ledger Outcome is filled. Commit on `unit/SB-registry`
(conventional commits, no `Co-Authored-By`, no `Refs:` line). Do not open a PR, do not file a
Linear issue, and do not merge: the integrator merges after wave 2 (D1, §2.3).

## 9. Open decisions

None open. Decided:

- **OD-R1 — decided (default).** The name check runs first, always, on a public board. A known
  system sent with an invalid `spec_id` (for example one with `/`) fails `422
  invalid_system_name`; it does not get the existing name plus a notice.
- **OD-R2 — decided (default).** `revision_of` names the system; `requested_name` is not read
  when `revision_of` is given.
- **OD-R3 — decided (default).** A known fingerprint plus `revision_of` returns the existing
  revision (I-N2), with a notice when the names differ.
- **OD-R4 — decided (default).** The `409` suggestion is not checked free.
- **OD-R5 — Decided: D7 X-18.** The C11-SB guard tests enforce the scoreboard rules. This unit
  does not edit `.claude/scripts/check_layering.py`.
- **OD-R6 — decided (default).** No metrics stack; this unit adds no counter (D7 X-15: the NFR
  counters stay in process and are not exported).
- **OD-R7 — decided (default).** The command is `python -m scoreboard.backfill_systems`.
- **OD-R8 — Decided: D7 X-22.** One cap: 32,000 chars with `422` (§4.7). No 256 KiB cap, no `413`.
- **OD-R9 — decided (default).** The backfill links a head only when its normalized `spec_id`
  equals the system name and its board and revision have no linked head yet; all others are
  reported and stay unlinked.
- **OD-R10 — Decided: D5.** Production runs `cloudflare_headers`, so the submitter is always a
  verified identity. In `disabled` mode SB-submit does not call the registry. `submitter: str`
  stays; the backfill reports `no_owner` for a NULL `submitted_by`.
- **Fingerprint formula — Decided: D3.** The adapter passes
  `exclude_bindings=frozenset({"_sf_recipe"})` (§4.8, rows 19, 19a, 19b).
