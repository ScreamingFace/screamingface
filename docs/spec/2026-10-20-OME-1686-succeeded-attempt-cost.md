# OME-1686 — Report the cost of the successful attempt in request economics

Ticket: `OME-1686` (parent epic `OME-1287`). Landing: `aigateway`. Consumer: `OME-1687`
(`screamingface-engine`), which is blocked by this issue. Ledger:
`docs/work/2026-10-20-OME-1686-succeeded-attempt-cost.md`. Plan:
`docs/plan/2026-10-20-OME-1686-succeeded-attempt-cost.md`.

## 1. Problem

The leaderboard shows the **cost of intelligence** of a model. It does not show the money that one
run spent. The cost of intelligence assumes a perfect world: each model answers on the first
attempt. A retry is an infrastructure event, so a retry must not change the price of a call.

Today the gateway folds all attempts of one request into one status
(`apps/aigateway/src/aigateway/plugins/taxonomy/render.py:73-95`, `_direct_cost_status`):

- A failed attempt that the gateway retried (HTTP 429, 503 or 529, `core/retry.py:23`) has
  `direct_cost.status = "unavailable"`.
- One uncovered attempt makes `direct_cost_status = "partial"` (`render.py:82-95`), and
  `known_direct_cost_subtotals` holds only the reported amounts.
- The Engine prices a call only when `direct_cost_status == "complete"`
  (`apps/screamingface-engine/src/screamingface_engine/world/accounting.py:206-208`). The call
  becomes unpriced, and one unpriced call makes the full run unpriced.

Example: attempt 1 is OpenRouter 503 (`unavailable`), attempt 2 is OpenRouter 200 with cost
`0.00042` (`reported`). The request is `partial`, and the Engine shows no price. The wanted price
is `0.00042`.

## 2. Goal

The gateway reports the direct cost of the **successful attempt** of each request as a separate
field in `request_economics`. The Engine (`OME-1687`) prices the call from this field. The fields
that describe the actual spend do not change.

## 3. Cross-ticket contract (fixed)

`OME-1687` codes against this contract. Do not change it in this unit.

- New key: `_aigw.request_economics.succeeded_attempt_direct_cost`.
- Value: the JSON of `direct_cost` of the attempt record whose `outcome == "succeeded"`. The shape
  is exactly the shape of `usage_accounting.attempts[].direct_cost`: `status`, `amount`, `unit`,
  `source` (`plugins/taxonomy/types.py:291-336`, schema `$defs.direct_cost`).
- Value is `null` when no attempt succeeded: a cache hit, a failed request, or no dispatch.
- The gateway calculates the value from **all** collector records (`records`,
  `render.py:153`). It never uses the truncated `rendered_records` (`render.py:155`).
- The value does not depend on `capture_status`, `omitted_attempts` or `may_summarize`
  (`render.py:168`).
- `direct_cost_status`, `known_direct_cost_subtotals`, `observed_new_attempts` and
  `usage_accounting.attempts[]` do not change.

**Contract extension (owner, 2026-10-20).** The Engine also counts tokens from the successful
attempt only. Thus a second additive key is part of this contract:

- New key: `_aigw.usage_accounting.succeeded_attempt_usage`.
- Value: the JSON of `usage` of the **same** record that `succeeded_attempt_direct_cost` uses.
  The shape is exactly the shape of `usage_accounting.attempts[].usage` (schema `$defs.usage`).
- The value is `null` in exactly the same cases as the cost key.
- The same rules apply: all records, never the truncated list; independent of `capture_status`;
  `_degrade_to_bound` keeps it.
- One helper selects the record for both keys, so the two keys always describe the same attempt.

## 4. Decisions

### D1 — Selection rule

The gateway selects the record with `outcome == "succeeded"`. If more than one record has
`outcome == "succeeded"`, the gateway selects the record with the **highest `sequence`** (the last
observed successful send). This case is not expected:

- A retry starts only after a failure (`core/retry.py:69-71`, `:162-164`).
- The collector downgrades a success that the gateway later rejects
  (`plugins/taxonomy/collector.py:284-304`, `mark_last_succeeded_provider_error`,
  `mark_last_succeeded_indeterminate`; `:329-341`, `mark_conversion_failed`).

The rule makes the value deterministic if a future path breaks this expectation. A unit test locks
the rule.

Implementation: `last_succeeded_record` in `plugins/taxonomy/render.py` selects the record, and
`_answer_record` adds the cache-hit rule. Both keys use the one result. The request-cache
write-time block (`plugins/taxonomy/entry_metadata.py`) used the same rule inline; it now calls
`last_succeeded_record`, so the rule is defined once.

### D2 — Value is a copy of the record's `direct_cost`

The value is `record.direct_cost.as_json()`, the same serializer that `attempts[]` uses. The
gateway does not change or summarize the value. Thus:

- `reported` carries the exact provider decimal, unit and source.
- `unavailable`, `absent` or `invalid` carries `null` amount, unit and source. This is a real
  unknown price of the successful attempt. It is not a retry effect.
- `unit_unknown` carries amount and source with `null` unit.
- No conversion and no currency logic occur in the gateway. The Engine owns conversion
  (`docs/usage-accounting.md`, "Ownership boundary").

### D3 — Cache hit, frozen-copy replay and no dispatch

- Cache hit: `attach_hit_metadata` (`plugins/taxonomy/session.py:398-478`) renders with
  `cache_status="hit"`. A hit has no new attempts (`session.py:407-409`). The value is `null`.
  The renderer sets `null` for `cache_status == "hit"` even if records exist, to match
  `_direct_cost_status` (`render.py:80-81`).
- Frozen-copy replay: `_replay_metadata` (`routes/frozen_copies.py:107-123`) renders with
  `collector=None` and `cache_status="hit"`. The value is `null`. The captured `_aigw` of the
  original call is not replayed (`frozen_copies.py:108-113`).
- Unsupported provider: the session has no collector (`session.py:144-149`), so records are empty.
  The value is `null`.
- The request cache stores the provider response **before** `_aigw` is attached
  (`session.py:364-371`, INVARIANT §6). `metadata_json` holds the write-time standard block, not
  `request_economics`. Thus no stored row carries this key, and no replay can show a stale value.

### D4 — Failure path

`accounting_error_response` (`session.py:481-510`) renders `_aigw` beside `detail` with the same
renderer. On known failure paths no record keeps `outcome == "succeeded"`: the collector downgrades
it (D1). Thus the value is `null` on an error body. The renderer stays a pure function of records
and `cache_status`; it does not know about the error path.

Owner decision (2026-10-20, Q3): the renderer does **not** force `null` on error bodies. If a
future failure path keeps a succeeded record, the error body shows that attempt's cost. This is
safe because the Engine never reads `_aigw` on a failed response: `_raise_for_status` runs before
the body is parsed (`apps/screamingface-engine/src/screamingface_engine/world/connector.py:1052`,
`:1067`), and `_report_usage` reads `_aigw` only after a successful round trip (`connector.py:238`).

### D5 — Streaming

The streaming path has no accounting session and no `_aigw` (`docs/usage-accounting.md`,
"Activation"). Nothing changes. The key is absent because `_aigw` is absent.

### D6 — Size bound and degradation

`_degrade_to_bound` (`render.py:102-122`) removes provider extensions, then attempts, then sets
`direct_cost_status = "partial"` and `known_direct_cost_subtotals = []`. It does **not** clear the
new key. The new key is calculated from `records`, so it stays correct when attempts are removed.
The key adds at most about 300 bytes (the `direct_cost` bounds are amount ≤ 64, unit ≤ 64,
source ≤ 128 ASCII bytes; schema `$defs.direct_cost`), which is far below `MAX_METADATA_BYTES`
(64 KiB, `render.py:23`). A unit test on the `bounds_overflow` shape locks this.

### D7 — JSON Schema

`$defs.request_economics` in `plugins/taxonomy/usage_accounting.schema.json` has
`additionalProperties: false` and a fixed `required` list. A strict consumer rejects an unknown
key. Changes:

- Add `succeeded_attempt_direct_cost` to `properties` as
  `{"oneOf": [{"$ref": "#/$defs/direct_cost"}, {"type": "null"}]}`.
- Add it to `required`. The gateway always emits it, and `required` makes the null/absent difference
  explicit.
- Add `succeeded_attempt_usage` to `$defs.usage_accounting` in the same way:
  `{"oneOf": [{"$ref": "#/$defs/usage"}, {"type": "null"}]}`, in `properties` and `required`.
- Owner decision (2026-10-20, Q1): **keep** the document `$id` `aigw-usage-accounting.v2.json`.
  Do not bump it. The contract is pre-beta and consumers update with it
  (`docs/usage-accounting.md`, intro).
- The top-level `request_economics.schema` marker stays `aigw.request_economics`. The doc says
  these markers carry no numbered version (`docs/usage-accounting.md`, intro).

### D8 — Documentation

Update `apps/aigateway/docs/usage-accounting.md`:

- Add the key to the response-shape example.
- Add a section "Cost of intelligence and actual spend":
  - To price a model call (cost of intelligence), use `succeeded_attempt_direct_cost`, and for its
  tokens use `succeeded_attempt_usage`.
  - To get the actual spend of the request, use `direct_cost_status` with
    `known_direct_cost_subtotals`, and the existing completeness rule.
- State D1, D3 and D4 in short form. State that `null` means "no successful attempt", and that
  an unknown status on a non-null value means "the successful attempt has no known cost".

### D9 — What does not change

- Retry policy (`core/retry.py`).
- Proven-zero logic (`OME-1446`). It continues to affect `direct_cost_status` only.
- Engine code. `OME-1687` owns the Engine change.
- Collector, mappers and provider plugins.

## 5. Effect on prior tests (Confidence Gate)

The key is always present, so these prior exact-shape tests must change. The sdlc rules require
owner approval before a prior test changes:

1. `tests/unit/usage_accounting/test_release_fixtures.py:68-78` and `:468-477`:
   `_EXPECTED_FIXTURE_SHA256` holds a hash for each of the 18 fixtures. Every hash changes. The
   fixture builders and other assertions do not change.
2. `tests/unit/usage_accounting/test_handoff_contract.py:89-100`: an exact `economics == {...}`
   dict. It needs the new key.
3. `tests/fixtures/cache_hit_contract/openrouter_hit.json:74-79`: the generated hit fixture
   gets `"succeeded_attempt_direct_cost": null`. It is regenerated with
   `SF_REGENERATE_CONTRACT_FIXTURES=1` (`tests/unit/test_cache_hit_contract_fixture.py:15-17`).
   The Engine suite reads this file (`apps/screamingface-engine/tests/unit/test_cache_hit_contract.py:53`).
   The Engine run-events output must stay the same; the plan runs that Engine test against the
   regenerated file to prove it.
Owner decision (2026-10-20, Q2): items 1–3 are approved, and nothing else in prior tests changes.
The approval is recorded byte-exact in `.claude/test-change-approvals/OME-1686.json`. Because the
`$id` stays `v2`, `test_openrouter_proven_zero_strict_evidence.py:431` does not change.

`tests/unit/test_frozen_copy_replay.py:395-420` seeds a hand-written `_aigw` as stored input. It
is not a rendered output, so it does not change.

## 6. Acceptance

- Each successful non-cached chat response with `request_economics` carries
  `succeeded_attempt_direct_cost` with the successful attempt's `direct_cost`.
- 503 → 200 with reported `0.00042`: the key is `reported` `0.00042`, and `direct_cost_status`
  stays `partial`.
- 429 → 200: the key is the 200's cost, with or without the `OME-1446` proven-zero evidence.
- Truncated attempts (more than `MAX_RENDERED_ATTEMPTS`) and the 64 KiB degradation: the key is
  present and correct.
- Cache hit, frozen-copy replay, failed request, unsupported provider: the key is `null`.
- The packaged schema validates every rendered fixture, and it rejects a wrong shape.
- `docs/usage-accounting.md` documents the key and the two meanings.
- Full `aigateway` gates pass.

## 7. Owner decisions (2026-10-20)

The owner approved this spec and the plan on 2026-10-20.

- **Q1 — Schema `$id`:** keep `aigw-usage-accounting.v2.json`. Add the key to the current schema's
  `properties` and `required` as `direct_cost | null` (D7).
- **Q2 — Prior tests:** §5 items 1–3 are approved. Nothing else in prior tests changes.
- **Contract extension:** add `usage_accounting.succeeded_attempt_usage` (§3). The approved
  prior-test changes (§5) cover this key too. Any other prior-test change needs approval first.
- **Q3 — Error bodies:** do not force `null`. The Engine never reads `_aigw` on a failure (D4).
- **Cache row:** the request-cache write-time block already stores the cost of the last succeeded
  send (`plugins/taxonomy/entry_metadata.py:184-213`). No change is needed there. The new
  selector uses the same rule (the last record with `outcome == "succeeded"`), which is the same
  record as the highest `sequence` because records are in send order.
