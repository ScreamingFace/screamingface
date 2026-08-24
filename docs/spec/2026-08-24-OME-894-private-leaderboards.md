# OME-894 — Private leaderboards

**Ticket:** [OME-894](https://linear.app/openmined/issue/OME-894/support-private-leaderboards-starting-with-healthbench-worst-30)
· **Ledger:** `docs/work/2026-08-24-OME-894-private-leaderboards.md`
· **Stack:** scoreboard · **Date:** 2026-08-24

## 1. Problem

HealthBench worst-30 is the public **entry challenge**. Its submissions must not be publicly
visible — staff see everyone's, participants see only their own.

Privacy has to live in the **API**, not the page. The portal is static JavaScript calling a public
API, so suppressing rows in the page would leave `curl /v1/leaderboard/healthbench-worst30`
serving the whole board. Three of the four read paths leak today: the board itself, per-spec
history, and the frontier aggregate.

Built as a general capability — a benchmark is public or private — because the entry challenge
will not be the last board that needs it.

## 2. Established facts

Verified against `origin/main` at `0b6a970c`; none assumed.

| # | Finding | Evidence |
|---|---|---|
| F1 | The write path resolves identity and **401s** when absent; the peer network is checked **before** the header is read | `routes/scores.py:52-83` |
| F2 | Its own AIDEV-NOTE says a second authenticated route does not inherit the check, and directs the next one to extract a `Depends()` | `routes/scores.py:63-68` |
| F3 | Stored `submitted_by` keeps the **full email**; the local-part trim is a `PlainSerializer` with `when_used="json"`, so it only applies on output | `scores/schemas.py:159-224` |
| F4 | `benchmark_to_schema` is the **one** Benchmark→DTO mapper; a second hand-written copy is what took `main` red in OME-852 | `scores/store.py:36-51` |
| F5 | `_ranked_entry` splats `entry.model_dump()` into `RankedLeaderboardEntry`, and both are `extra="forbid"` — a field in one and not the other is a runtime 500, not a type error | `routes/leaderboard.py:51-55, 117-118` |
| F6 | `leaderboard()` already filters to the benchmark's registered revision (OME-775) | `scores/store.py:452-466` |
| F7 | `auth_mode` defaults to `"disabled"`; the chart sets `authMode: disabled` and `values-prod.yaml` does **not** override it | `config.py:43`, `charts/scoreboard/values.yaml:41` |
| F8 | Tests already drive the real identity path — `cloudflare_headers` + `allowed_networks` + `X-User-Email` | `tests/unit/test_scores_routes.py:67`, `test_proxy_headers_integration.py:66` |

F3 is load-bearing: server-side ownership comparison against the header email is **exact**, because
the domain survives in storage. No fuzzy matching is needed and none is acceptable.

F7 is the operational catch — see §5.

## 3. Decisions

| # | Decision | Source |
|---|---|---|
| D1 | `Benchmark.visibility`, `public` by default; existing rows backfill to `public` | ticket design |
| D2 | **Fail closed under `auth_mode: "disabled"`** — no verified identity means nothing readable on a private board. No API escape hatch. | owner, 2026-08-24 |
| D3 | `rank` becomes `int \| None`, null on a private board | owner, 2026-08-24 |
| D4 | A private benchmark **is** listed in the public catalogue, marked private | Irina, AGREED 2026-08-24 |
| D5 | Participants see **no aggregate** — nothing beyond their own submissions | Irina, AGREED 2026-08-24 |
| D6 | Staff access is a **read-only operator module**, never an admin API | owner, 2026-08-24 |
| D7 | Identity on reads is a shared `Depends()`, resolved once (F2) | this spec |
| D8 | On a private board the caller sees **all** their own rows, not only registered-revision ones | §4.3 |

D2 was chosen over a dev escape hatch because F8 shows local development and tests can already
exercise the owner path through the real identity mechanism. A hatch would buy nothing and would be
one more setting whose misconfiguration silently publishes the challenge.

## 4. Design

### 4.1 `Benchmark.visibility`

```python
visibility = fields.CharField(max_length=16, default="public")
```

Typed as a `Literal["public", "private"]` on the DTO. Added to `BenchmarkSchema` **and**
`benchmark_to_schema` in the same change (F4), and to `SeedBenchmark` so the chart can flip
HealthBench without a code change.

Default rather than nullable: a benchmark whose visibility is unknown must not be treated as
private-by-accident or public-by-accident. `public` preserves today's behaviour for every existing
row with no backfill.

### 4.2 Optional identity on reads (D7)

A dependency returning `str | None`:

1. `auth_mode == "disabled"` → `None`. There is no verified identity to be had (D2).
2. Peer outside `allowed_networks` → `None`. **Checked before the header is read**, carrying F1's
   invariant over verbatim so an untrusted peer never has its claim consulted.
3. Header absent → `None`.
4. Otherwise the verified email.

It never raises. A public board must stay anonymously readable, so a missing identity is a normal
state on reads, unlike on the write path.

### 4.3 What a private board returns

| Path | Private behaviour |
|---|---|
| `/v1/benchmarks` | listed, `visibility: "private"` (D4). Carries no scores, so nothing leaks. |
| `/v1/leaderboard/{id}` | the caller's own entries, `rank: null`, an explicit private flag, no leading marks. Anonymous → empty **with** the flag. |
| `/v1/leaderboard/{id}/{spec_id}/history` | served only if the spec belongs to the caller, otherwise **404, not 403** |
| `/v1/leaderboard/{id}/frontier` | **404** — an aggregate over everyone by definition (D5) |

**404 not 403 on history:** a 403 confirms the spec exists, and spec ids are guessable model names.
The status code is part of the privacy boundary, not an implementation detail.

**An empty list is not enough on the board path.** A bare `[]` is indistinguishable from "nobody
has submitted", so the response carries an explicit flag saying the board is private and the view
is scoped to the caller.

**Suppressed:** rank, because telling a participant they are 4th tells them three people beat them;
and the SOTA and Pareto marks, because each is a statement about the field. Omitted, not
computed-and-hidden.

**Baselines stay visible.** `LeaderboardResponse.baselines` are imported LMArena / Artificial
Analysis single-model numbers — public third-party data, not participant submissions — and a
participant needs the line to beat. This is the one call not covered by the ticket; flagged for
owner confirmation rather than assumed silently.

### 4.4 Revision interaction (D8)

F6 means `leaderboard()` drops rows whose revision differs from the registered one. On a private
board that would hide a participant's own submission with no explanation — a second
invisible-submission mode, which is precisely the failure that stranded a real DRACO submission on
2026-08-19 and which `OME-909` exists to fix.

Because rank is suppressed on a private board (D3), **the filter's purpose does not apply**: it
exists to stop incomparable numbers being ranked against each other, and nothing is being ranked.
So a private board lists all of the caller's rows.

Explaining *why* a row would not rank remains `OME-909`. D8's job is to keep this ticket from
creating that problem in a second place.

### 4.5 Staff access (D6)

A read-only operator module, following the `seed.py` / `import_baselines.py` precedent:

```sh
python -m scoreboard.export_private_submissions --benchmark healthbench-worst30
```

It reads the database and prints every submission. No HTTP surface, so there is nothing to secure,
guess, or accidentally expose — the property the ticket asked for. It also works regardless of
`auth_mode`, which matters given F7.

### 4.6 Migration

One Tortoise migration `0008_*` (built-in migrations, never Aerich) adding one column with a
default. No backfill needed — the default supplies `public` for every existing row.

## 5. Operational catch

Per F7 the deployed `authMode` is very likely `disabled`, and under D2 that makes the private board
readable by **nobody** through the API. Staff still have §4.5. Enabling `cloudflare_headers` is an
infra action tracked by `OME-895` (Backlog, `human`).

The actual deployed value cannot be verified from this repo — the platform team keeps its own values
file (`OME-730`). **Confirm the runtime `authMode` before the challenge is announced**, or
participants will be unable to see their own submissions.

## 6. Out of scope

Explaining why a row will not rank (`OME-909`) · opening Cloudflare auth (`OME-895`) ·
verified-vs-self-reported signal (`OME-821`) · portal rendering · an admin API (D6) · any change to
the submission path.

## 7. Acceptance

- An anonymous caller reading a private benchmark gets no other participant's data on **any** of
  the four paths.
- An authenticated caller sees their own rows and no one else's.
- `history` for another participant's spec returns 404.
- `frontier` is unavailable for a private benchmark.
- A private board shows no rank and no leading marks.
- A caller's own rows appear even when measured against a non-registered revision (D8).
- **Public boards are byte-identical to today for an anonymous caller** — the main regression risk.
- Full gates green.
