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

### §3.1 There is NO pairing rule, deliberately

A run whose `run_cost_status` is `partial` has, by definition, a reported saved-cost sum — that is
what makes it `partial`. So `partial` beside a null saved cost looks incoherent, and a validator
refusing it looks correct.

**It would 422 the SDK released today.** `OME-1252` ships `run_cost_status` and *not* this field;
`OME-1326` adds it later. Between those two releases every `partial` submission carries a status
with no saved cost, and that is the normal, correct state of the world for weeks.

This is the `OME-822` P1-1 finding exactly: a rule that is true of the final contract, enforced
before the clients can satisfy it, deadlocks the rollout. **Expand first. The pairing rule, if it
is ever wanted, belongs beside `OME-1258`'s flip.**

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

### §5.1 Why the `OME-822` P1-2 trap does not apply here

That bug was: migration `0014` left `run_cost_status` null on **every** pre-existing row including
priced ones, so gating the fill on the status treated a migrated priced row as empty and let a
replay erase published money. The amount was the correct sentinel, not the label.

Here the field **is** the amount and no row has ever held one, so `NULL` is unambiguous: nothing
has been published that a fill could overwrite. The gate on its own null is sound.

The one conflation that remains — null means both "no cache hits" and "client did not report" — is
harmless on this path, because filling either with a null submission value is a no-op.

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
