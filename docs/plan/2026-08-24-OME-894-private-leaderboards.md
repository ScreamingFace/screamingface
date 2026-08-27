# OME-894 — Implementation plan

**Spec:** `docs/spec/2026-08-24-OME-894-private-leaderboards.md`
· **Ledger:** `docs/work/2026-08-24-OME-894-private-leaderboards.md`
· **Branch:** `OME-894-private-leaderboards` · **Stack:** scoreboard

Gates after every step:
`uv run .claude/scripts/run_gates.py scoreboard --base origin/main`
→ append-only · ruff check · ruff format --check · pyright · pytest --cov=scoreboard --cov-fail-under=80

`tortoise-dev` is a **mandatory** companion for this unit (model + migration).

## Ordering principle

The regression guard comes **first**, before any privacy behaviour exists. The main risk in this
unit is not failing to hide the private board; it is quietly breaking the public one while doing so.
A guard written first fails for the right reason later.

Then: schema → identity → store scoping → routes → operator module. Each step is RED-first and
leaves the suite green, so a regression bisects to one step.

---

### Step 0 — the regression guard

**RED-ish (characterisation):** pin the current anonymous response shape of all four paths for a
**public** benchmark — status, key sets, and ordering. These must pass unchanged at every later
step; if one breaks, the change is wrong, not the test.

Marked clearly as the OME-894 regression guard so a future reader knows why it is stricter than it
looks.

---

### Step 1 — `Benchmark.visibility` + migration

**RED:** `visibility` exists on the model, defaults to `"public"`, is exposed on `BenchmarkSchema`,
and a benchmark seeded without it reads back `public`.

**GREEN:**
- `scores/models/benchmark.py` — `visibility = fields.CharField(max_length=16, default="public")`
- `scores/schemas.py` — `Literal["public", "private"]` on `BenchmarkSchema`
- `scores/store.py` — `benchmark_to_schema` in the **same** edit (spec F4), plus
  `register_benchmark(..., visibility=...)`
- `seed.py` — `SeedBenchmark.visibility`, so the chart can flip HealthBench
- `scores/migrations/0008_*.py` — one `AddField` with the default

**Guard:** `tortoise makemigrations` reports no further drift.

---

### Step 2 — optional identity on reads

**RED:** returns `None` in `disabled` mode · `None` for an untrusted peer **even when a header is
present** (the invariant that matters) · `None` when the header is absent · the email for a trusted
peer with a header. Never raises.

**GREEN:** new `core/auth/read_identity.py`, wired as a `Depends()`. Peer check strictly before the
header read.

**Note:** this is the extraction the AIDEV-NOTE at `routes/scores.py:63-68` asks for. Leave the
write path's `_resolve_submitter` alone — it must keep raising, and merging the two would weaken it.

---

### Step 3 — store-level owner scoping

**RED:** each of `leaderboard()`, `list_for_spec()`, `list_all_for_benchmark()` returns only the
owner's rows when given an owner, and is unchanged when given `None`.

**GREEN:** optional owner parameter threaded into the **queries**, not applied as a post-filter over
rows already fetched — a post-filter would read every participant's row into memory to serve one
person, and would silently interact with `top_n`.

---

### Step 4 — the four read paths

**RED**, per path: anonymous vs private · owner vs private · non-owner vs private. Plus
specifically:
- history for another participant's spec → **404**, not 403
- frontier on a private benchmark → **404**
- private board → `rank: null`, no leading marks, explicit private flag
- private board → the caller's non-registered-revision rows **are** listed (spec D8)
- `disabled` mode → nothing readable on a private board
- Step 0's public-board guards still pass

**GREEN:** `routes/leaderboard.py`. `rank` → `int | None` on `RankedLeaderboardEntry`, kept in step
with `LeaderboardEntry` (spec F5). `LeaderboardResponse` gains the private flag. Baselines stay
visible (spec §4.3).

---

### Step 5 — staff operator module

**RED:** returns every submission for a private benchmark regardless of `auth_mode`; exits non-zero
on an unknown benchmark.

**GREEN:** `scoreboard/export_private_submissions.py`, shaped like `seed.py` /
`import_baselines.py` — `main(argv)` plus `if __name__ == "__main__"`.

---

### Step 6 — close out

Ledger Outcome filled · conventional commits, body `Refs: OME-894`, no `Co-Authored-By` · PR ·
green CI · squash-merge · close comment per the card's `close_template` · close the `docs/tasks/`
mirror.

## Risks

| Risk | Handling |
|---|---|
| Breaking the public board while securing the private one | Step 0 guards it before any behaviour changes, and every later step re-runs them |
| `rank: int \| None` drifting between the two mirrored DTOs | Spec F5 records the runtime-500 failure mode; both are edited in one change in Step 4 |
| A post-filter used instead of query scoping | Called out explicitly in Step 3 |
| The feature being inert in production | Not a code risk — spec §5, needs Stephen to confirm `authMode` |

## Out of scope

`OME-909` · `OME-895` · `OME-821` · portal rendering · admin API · submission path.
