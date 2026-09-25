# OME-1325 — Storing what the cache saved

Scoreboard half of `OME-1251` D5. **Phase 1 of two**; the ranking half is deferred, see §6.

## §1 The number this field carries

A cache hit costs nothing upstream. So a cached run's `run_cost_usd` is ≈0, and because it *was*
priceable it derives `complete` — a confident label on a meaningless figure. That is `OME-1143`.

`#930` records, at cache-fill time, what the original call cost, and the engine totals it per
run. The SDK reads it as of `OME-1252`. **Nobody carries it to the board.**

| field | means |
| -- | -- |
| `run_cost_usd` | what the run **spent**. Unchanged meaning, unchanged value |
| `cache_saved_cost_usd` | what this run's cache hits **would have cost** |
| reproduction cost | `run_cost_usd + cache_saved_cost_usd`, **derived at the point of use** |

**Never stored pre-summed.** D5's reasoning: separate parts let the board store real data now and
decide later. A pre-summed number would be silently low until `OME-1287` lands, with no way to
tell how low or recompute. It also destroys the submitter's actual spend, which is a real fact
about a real bill.

## §2 One field crosses, not two

`cache_saved_cost_archive_usd` stays client-side. **D3.**

`reported` money is what the provider itself priced for the call that filled the entry.
`archive_matched` is a real measured amount from a **different** call of the same model and kind —
real money, but not provably this row's. url4 keeps them as two differently-named fields
*"precisely so the two can never be summed"*, and both the engine and the SDK carry structural
tests forbidding a third accumulator. Publishing the archive figure, or summing it in, would
defeat all of that from the far end.

## §3 The wire contract

`cache_saved_cost_usd` is **optional**, `Decimal | None`, defaulting to `None`.

Bounds mirror `run_cost_usd` exactly, reusing `_validate_run_cost`: `ge=0`,
`allow_inf_nan=False`, `DECIMAL(12, 6)` — `0.000001` through `999999.999999`. Money already has a
validated domain here and this is money.

### §3.1 A ONE-WAY pairing rule — amended at review, 2026-09-24

*First written as "there is NO pairing rule". Review of PR #1055 (P2) showed that was broader
than the rollout requires.*

**Accepted: `partial` beside a null saving.** A `partial` run has a reported saved-cost sum by
definition, but `OME-1252` ships the status and NOT this field, and `OME-1326` adds it later.
Between those releases every `partial` submission legitimately lacks it. Refusing it would 422
the released SDK — the `OME-822` P1-1 deadlock exactly.

**Refused: `unavailable` beside any saving.** `unavailable` means no cost evidence, and a saving is
cost evidence. It can never come from a correct client: the SDK derives `partial` whenever the
reported sum is present, **including when it is 0** — so the rule is "any non-null saving", not
"> 0". Older clients never send this field, so nothing deployed can trip it.

### §3.2 An absent status is derived — amended at review round 2, 2026-09-24

When `run_cost_status` is absent, the board derives it from the evidence present, matching the
SDK's own derivation:

| status absent, and… | derived |
| -- | -- |
| `run_cost_usd` present | `complete` — an amount IS the claim `complete` makes |
| only `cache_saved_cost_usd` present | `partial` — unpriced, with a reported saving |
| neither | stays null — a legacy-shaped row |

The middle row was missing. Without it, a submission carrying only a saving stored a null status,
which reads as "predates cost reporting" on a row carrying a field only new clients send — and
§5.1's snapshot rule meant replay could never repair it. Rollout-safe: older clients never send
the saving, and new clients send the status explicitly.

## §4 Storage

Nullable `DecimalField(max_digits=12, decimal_places=6)` on `Score`, migration `0015`, **no
backfill**.

**NULL means "not reported", never `0`.** The same rule `run_cost_usd` carries at
`models/score.py:72`: a run that genuinely saved nothing is a legitimate `0`, and conflating the
two would let an unknown value behave like a known one — the failure `OME-770` D8 exists to
prevent and the one `OME-1143` is about.

Backfill was rejected for the reason `0014` records: it would assert a fact about every legacy row
that nobody ever established.

## §5 Replay

`content_hash` excludes cost (`OME-770` D8), so a recipe already stored gains this field only
through `_replay_updates`.

**Fill only, never replace**, gated on `existing.cache_saved_cost_usd is None`. A populated value
is retained — enrichment fills a gap, it does not arbitrate between two claims.

### §5.1 One execution, one snapshot — amended at review, 2026-09-24

*First written as "why the `OME-822` P1-2 trap does not apply here", arguing the saving could be
filled on its own null because nothing published could be overwritten. **That reasoning answered
the wrong question.** The risk was never overwriting; it was COMBINING figures from two different
runs.*

Review of PR #1055 (P1) reproduced it: an original run spent $2 and reported no saving; a later
fully cached run of the same recipe spent $0 and saved $2. `content_hash` excludes cost, so the
second dedups to the first. Filling the saving alone kept the old $2 spend beside the new $2
saving — a **$4 reproduction cost neither run produced**, and one phase 2 would rank on.

**Spend, status and saving describe ONE execution and move as one snapshot.** All three are filled
together from a single replay, and only when all three were absent. The existing heal of a
missing status label beside a stored amount is unchanged — it relabels the row's own amount and
mixes nothing.

**Accepted consequence:** a row already holding a spend never gains a saving by replay. The saving
arrives on FIRST submission, from clients that send all three fields together.

## §6 What this deliberately does NOT do

**The frontier is untouched.** `scores/pareto.py:91` still reads `entry.run_cost_usd` alone.
Ranking on the sum is phase 2 and is gated on `OME-1287` (E2): until every call is priced from a
central per-model list, the sum understates the truth, and a frontier ranked on quietly-low
numbers is the present failure at a smaller scale.

**No read path changes.** Nothing serves the new field to the portal yet, so the open question of
what the Cost column shows stays open and stays phase 2's. Storing without reading is safe
precisely because no surface can disagree with another.

**`ScoreSchema` does gain it, with `exclude_if`.** The stored value must survive the byte-exact
JSONL export whose digest authorises a private-board purge — a stored-but-unexported field would be
lost on restore. `exclude_if` is not optional: an always-present key changes every historical
digest, so a previously certified export stops authorising its own purge. That is the `OME-1181`
Q2 trap, and it has bitten once.

## §7 Out of scope

- `archive_matched` money — D3
- the client half — `OME-1326`
- the frontier, the portal, and the Cost column — phase 2
