# Cache-entry metadata — PRD

**Ticket:** OME-1155 · **Feature:** standard metadata (cost, latency, tokens) on every cached
response · **Stacks:** aigateway, url4, screamingface-engine

> **Provenance — read this first.** This document was **reconstructed on 2026-09-14 from the
> implementation that cites it**, during the review of PR #930. The original was written during
> the feature's design but never committed: roughly thirty docstrings across three stacks cite it
> by numbered test, section and invariant, and the file existed in no branch, no history and no
> ignore rule. Every identifier below is recovered from what the citing code and tests
> demonstrably assert — not from the lost original, and not from memory.
>
> Two consequences follow, and neither is hidden. First, a requirement the original stated but
> that no surviving test or comment cites is **not here**, because nothing records it. Second,
> this is a spec derived from its implementation, so it cannot be evidence that the
> implementation is correct — only that the implementation and its citations now agree. Where a
> cited identifier could not be pinned to a specific assertion it is listed under
> [Unrecovered identifiers](#unrecovered-identifiers) rather than being invented.

---

## 1. Problem

The global response cache stored the provider body and nothing else. A hit could therefore not
say what the call would have cost, and a deployment could not report what its cache saved. Worse,
the run that consumed a hit billed it as a fresh call at zero — so savings were not merely
unreported, they were structurally invisible: the one error nobody notices, because the number it
produces looks reasonable.

## 2. Product requirements

### §2.1 A standard block beside every cached response

Every row written to the global cache carries a metadata block describing the call that produced
it: canonical token usage, the provider's own direct cost, the provider latency, and the model
that actually answered.

### §2.2 A column, not a field in the body

The block is stored in its own column. The cached row must stay provider-compatible for every
future replay, and `response_size_bytes` measures what the store is given — embedding the block
in `response_json` could push an otherwise cacheable response over the size cap and silently cost
a cache entry.

### §2.3 Locked build order

The block is built from the `AccountingSession`, **before** `attach_success_metadata` renders
`_aigw` and before `RequestCacheWrite` is constructed. The store write therefore runs before the
response is decorated, and `response_size_bytes` measures only the provider's own response.

*Cited by `tests/unit/test_chat_cache_entry_metadata.py`.*

### §2.4 Captured from the raw response, never inferred from the cached body

`cache.reference.direct_cost` is populated at write time from the raw provider response. No value
is ever derived from the cached body on the way back out. This is what lets a stored block be
monetary evidence at all.

*Cited by `runner/accounting.py`.*

## 3. The block and its reporting

### §3.2 Shape

See the ERD §3.2 for the field-level shape. Product-level: status, observation time, response
model, usage, direct cost, latency.

### §3.5 Reference mapping

On a hit the stored block is mapped to the caller-visible `CacheReference`. A `partial` capture
never certifies a price; the usage source is rewritten to `cached_converted_response` on replay;
`provider_latency_ms` is reported verbatim or omitted.

Five saved-cost attribute keys are named here and nowhere else.

### §3.9 Coverage counts make a partial total auditable

Alongside each total the engine publishes `reported_hits`, `archive_hits` and `unpriced_hits`. A
total that covers some hits and not others is only honest if the reader can see which.

### §4.1 Accumulation semantics

Saved cost accumulates **O(1) per gateway round trip, not per turn**. A tool-calling turn is
several independently-keyed calls against one span, so a span's saved cost is the **sum** of its
hits — never last-wins. Summing the span attribute across a run's spans must reproduce the run's
own total.

### §4.4 One warning per unreadable key

A block that cannot be read is warned about **once per key**, not once per hit. A popular corrupt
row is read on every request that keys to it, and a warning per hit is spam rather than signal.

### §4.5 The block carries no sensitive material

The serialized block's key set is closed. It contains no prompt text, no credential, and no
account identity.

### §7 Metrics carry no high-cardinality identity

No metric is labelled by cache key, prompt or credential.

> *Cited as "spec §7" rather than "PRD §7" in `runner/cache_counters.py`. Recorded here as the
> most likely home; if a separate spec owns it, the citation should be re-pointed.*

## 4. Invariants

| Id | Invariant |
|---|---|
| **I1** | `NULL`, `None` and `0` are three different claims and are never conflated. A hit's **current-request** cost is exactly `Decimal("0")`; an **unknown** price is `NULL` and never defaulted. The column has no `DEFAULT`. |
| **I2** | `CacheReference` **raises** on `incurred_in_current_request=True`. A cache reference can never claim to be current spend. |
| **I3** | Cost is an output. The stored block never changes the cache key — otherwise the corpus would silently partition by price. |
| **I4** | A lost write race leaves the **winner's** metadata in place. |
| **I6** | The gateway stores the provider's cost **unit** verbatim. Unit-to-USD conversion happens engine-side, never at write time. |
| **S3/S4** | On a hit, a present block is preferred and the provider plugin mapper is not invoked. When the block is absent or unusable, the existing mapper runs unchanged. |
| **S5** | `reported` and `archive_matched` money are **never** combined into one figure. They are kept as two separately-named fields so a consumer cannot sum the labels away. Both are rendered as counterfactual. |
| **S7/M8** | The same separation holds at **both** run and span scope: two accumulators, never summed. |
| **S8** | The builder never raises. Any failure yields `None`, logs a warning, and the row is still written. |
| **S10** | The losing writer's block never overwrites the winner's. |
| **S11** | A block that fails to parse or rebuild is treated as **absent**; the caller falls back to the provider's mapper and the body still serves. |
| **S14** | Never guess a currency or an exchange rate. An unpriceable unit, or a negative amount, leaves the hit unpriced — entering no total, only the coverage counters. |
| **S18** | A placeholder cost is never `0`, which would be a lie about a genuinely unpriced hit. |
| **M2** | `archive_matched` carries the **same** mandatory fields as `reported` (amount, unit, source). |
| **M5/M7** | Money and counts are re-validated through the canonical constructors on rebuild, never trusted verbatim from storage. |
| **M9** | A block over the byte cap is dropped **whole**. There is no trimming ladder. |

## 5. Answered questions

| Id | Question | Answer |
|---|---|---|
| **ans:Q1** | Is a stored latency recomputed on replay? | No — copied verbatim into the reference. |
| **ans:Q2** | Where does saved cost live? | In its own reader and accumulators, distinct from the run's own spend, at run and span scope. |
| **ans:Q3** | What does an unpriced provider store? | `None`, never `"0"`. |
| **ans:Q5** | Can archive-paired money be treated as provider-authored? | No. It is real and measured, but its per-row attribution is unproven, so it is reported and totalled on its own. |

## 6. Acceptance tests

Numbered as the codebase cites them. A gap in the numbering is a test the original specified that
nothing surviving cites — see [Unrecovered identifiers](#unrecovered-identifiers).

| # | Requirement | Pinned by |
|---|---|---|
| **2** | An unpriced provider stores a null amount, never `"0"`. | `test_an_unpriced_provider_stores_a_null_never_zero_amount` |
| **3** | A hit reports its avoided cost while its current-request cost stays `Decimal("0")`. | `test_a_hit_reports_its_avoided_cost_without_pricing_the_current_request` |
| **4** | The `CacheReference` constructor refuses current-request spend. | `test_the_constructor_still_refuses_current_request_spend` |
| **5** | Archive money is never summed into the provider-authored total. | `test_archive_money_is_never_summed_into_the_provider_authored_total` |
| **9** | A lost write race keeps the winner's metadata. | `test_a_lost_write_race_keeps_the_winners_metadata` |
| **14** | A corrupt block is treated as absent and the body still serves. | `test_a_corrupt_metadata_block_is_treated_as_absent` |
| **15** | A serialization failure stores `NULL`, warns once, and serves the body. | `test_a_metadata_serialization_failure_stores_null_and_serves_the_body` |
| **16** | Each provenance sums into its own total; all three coverage counts are kept. | `test_each_total_sums_only_its_own_provenance_and_all_three_counts_are_kept` |
| **17** | A hit discarded by revalidation does not count its saved cost. | `test_a_discarded_hit_does_not_count_its_saved_cost` |
| **18** | A hit's saved cost never enters the run's `cost_usd`. | `test_a_hits_saved_cost_never_enters_the_runs_cost_usd` |
| **19** | An unknown currency keeps the amount and drops the unit. | `test_an_unknown_currency_keeps_the_amount_and_drops_the_unit` |
| **20** | A stored latency is reported verbatim. | `test_a_stored_latency_is_reported_verbatim` |
| **21** | The block carries no prompt, credential or account identity. | `test_the_block_carries_no_prompt_credential_or_account_identity` |
| **23** | Money validators are reused, not reimplemented; a block round-trips through JSON exactly. | `test_non_ascii_non_canonical_or_unknown_money_is_refused`, `test_a_block_round_trips_through_json_exactly` |

### Test 23 — specified `level: property`, shipped example-based

The original specifies test 23 at `level: property`. It ships as an example matrix because the
repo carries no property-testing dependency and PR #930 judged that change out of scope. The
matrix covers the known traps — scientific notation, precision boundaries, canonical `"1"` vs
`"1.0"`, sub-cent amounts, latency boundaries — and was later broadened to the line-separator
family (U+2028/U+2029/U+0085/U+FEFF), which a property test's string strategy would have found on
its own.

**This does not close the requirement at its specified level.** A property test would additionally
walk the full "which optional fields are `None`" space rather than a fixed grid, and shrink a
failure to a minimal input. Recorded as open.

## 7. Work breakdown

| Task | Scope |
|---|---|
| **A1** | The `CacheEntryMetadata` value object: codec, byte cap, rejection rules. |
| **A2** | The `metadata_json` model column (`aigw.cache-entry-metadata.v1`). |
| **A3** | Migration 0011: nullable, no default, appended last, no table rebuild on either dialect. |
| **A4/A5/A6** | Write path (`RequestCacheWrite.metadata`) and read path (`CachedEntry.metadata`). |
| **A7** | The canonical 13-column snapshot layout and its one tolerated 12-column predecessor. |
| **A9** | The Tavily retrieval lane carries no cost signal and always writes `NULL`. |
| **B1/B2** | The write-path builder `cache_entry_metadata_from_session`. |
| **B3** | The `archive_matched` status and reference latency handling. |
| **B5** | The hit path prefers the stored block over re-asking the provider plugin. |
| **C1–C4** | Chat-route wiring: built from session, read on hit, block travels to the hit path. |
| **E1/E2** | Saved-cost reporting on the observation seam (see ERD §4). |
| **E3/E5** | The avoided-cost reader and its two accumulators. |

## 7.1 Review round 2 additions (OME-1203)

> **Added in review round 2, 2026-09-14.** Unlike the rest of this document, this section is not
> recovered from a lost original — it is new specified behaviour, added closing PR #930's second
> review round, pinned by the tests named below.

**A retried round trip proves nothing was avoided.** A cache hit whose gateway round trip
followed a transport-layer retry is reported as a hit with **no saved cost**, and counts as an
**unpriced hit** (`cache.saved_cost.unpriced_hits`) — never as a priced saving. The retried
attempt may already have been processed and billed upstream before its response was lost in
transit; the retry then hits the very row that attempt wrote, and pricing that hit would report
money saved that was in fact spent. This **withdraws** a claim; it does not assert the spend was
zero — the underlying billed-then-lost-attempt gap is not closed by this rule and needs
gateway-side idempotency keys (tracked separately, not in this PR).

`CacheOutcome.retried` carries the fact from `_post_completion`, and
`avoided_usd_for_outcome(aigw, cache)` in
`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py` is the single choke
point that applies it — not the connector, which only produces the flag.

*Pinned by `test_a_hit_after_a_transport_retry_is_not_priced`,
`test_a_hit_with_no_retry_is_still_priced` and
`test_a_withdrawn_price_lands_in_the_unpriced_bucket_and_no_total` in
`apps/screamingface-engine/tests/unit/test_cache_saved_cost.py`, and
`test_read_cache_outcome_passes_the_retried_flag_through` in
`apps/screamingface-engine/tests/unit/test_cache_readback.py`.*

## 8. Unrecovered identifiers

Cited somewhere in the codebase, but not pinnable to a specific assertion from the surviving code.
Listed rather than invented, so a future reader knows the difference.

- **Test #13** — appears only in a grouped citation list in the reference suite's module
  docstring. No isolated test body or inline marker. Context suggests legacy-row behaviour
  preservation; unconfirmed.
- **M9 (as distinct from M5/S11)** — bundled with M5 and S11 in one module docstring. Its
  drop-whole/no-trimming meaning is recovered from `CACHE_ENTRY_METADATA_MAX_BYTES` and is
  recorded above; whether M9 said anything further is unknown.
- **E6 (as distinct from E7)** — appears only paired with E7 in one module docstring, with no
  assertion separating them.
- **"spec §7"** — cited with that spelling, not "PRD §7". Recorded in this document as the most
  likely home; may belong to another spec.

Numbers **#1, #6–#8, #10–#12, #22, #24–#28** are cited nowhere in the surviving code. They may
never have existed, or their tests may have been folded into others.
