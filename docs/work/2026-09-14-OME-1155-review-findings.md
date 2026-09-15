---
ticket: OME-1155
stack: aigateway + url4 + screamingface-engine
status: in_progress
started: 2026-09-14
finished:
---

# OME-1155 — PR #930 review findings: the missing spec, the silent restore, and the untested edges

## Intent

The full four-reviewer review of PR #930 found no correctness defect, but it did find that the
feature's own specification was never committed: ~30 test docstrings across three stacks cite
`docs/spec/2026-09-13-cache-entry-metadata-prd.md` and `…-erd.md` by numbered test, section and
invariant, and neither file exists on disk, in `.gitignore`, or in any branch's history. The
prior ledger on this branch records EDITING those files, which cannot have happened. That is the
blocker: a reader cannot check what "PRD test #23" requires, and the repo's spec-before-code gate
is unmet for the whole feature.

Beyond it, six Important findings: a snapshot merge that silently turns priced rows back into
unknown ones with nothing counting them; two store-level invariants that have hand-written
constants and comments but no test; Postgres concurrency tests that never pass a metadata block;
best-effort handlers that log a provider name and discard the exception; and `ModelResponse`
stating a pairing invariant it does not enforce while its accounting-side twin does.

FEATURE: standard metadata (cost, latency, tokens) on every cached response — OME-1155.

## Planned changes

**Spec (reconstructed from the implementation that cites it)**
- `docs/spec/2026-09-13-cache-entry-metadata-prd.md` — numbered tests #2–#28, sections §2.3/§2.4/
  §3.5/§3.9/§4.1/§4.4/§4.5, tasks A1–A9/B1–B5/C1–C4, invariants I1–I6/S3–S18, answered questions
  ans:Q1/Q2/Q3/Q5.
- `docs/spec/2026-09-13-cache-entry-metadata-erd.md` — §3.1/§3.2/§3.5/§4/§5.1/§5.2/§5.4/§5.5,
  invariants E6/E7/E9/M1/M2/M5/M7/M8/R2, scenarios S12/S13/S20.
- `docs/tasks/2026-09-14-OME-1155-cache-entry-metadata.md` — the missing Linear mirror.

**Code**
- `apps/aigateway/src/aigateway/core/request_cache/bulk_loader.py` — `LoadOutcome` grows
  `metadata_degraded`; a set-based count of rows whose live block is non-NULL and whose incoming
  staged block is NULL runs inside the load transaction, before the merge; a warning names the
  count. Merge mode only — replace is the acknowledged-loss path.
- `apps/aigateway/src/aigateway/core/request_cache/upload_job.py` — carry the count into the job's
  reported counts.
- `apps/aigateway/src/aigateway/plugins/taxonomy/entry_metadata.py` — `exc_info=True` on the S8
  handler; an `AIDEV-NOTE:` recording that `archive_paired` has no in-repo producer.
- `apps/aigateway/src/aigateway/plugins/taxonomy/session.py` — `exc_info=True` on both handlers.
- `apps/aigateway/src/aigateway/core/request_cache/store.py` — an `AIDEV-NOTE:` naming the
  caller-side broad catch that completes `_serialize_metadata`'s never-fails guarantee.
- `packages/url4/src/url4/observe.py` — `ModelResponse.__post_init__` enforcing the documented
  amount/provenance pairing, mirroring `AvoidedCost`.

**Tests (append-only; no prior test is edited)**
- `apps/aigateway/tests/unit/test_request_cache_metadata_store.py` — repeat hits on one corrupt
  key warn exactly once; an over-cap block written through the real store lands NULL and warns.
- `apps/aigateway/tests/unit/test_cache_entry_metadata.py` — a block whose strings carry
  U+2028/U+2029 round-trips byte-exactly.
- `apps/aigateway/tests/integration/test_cache_snapshot_entry_metadata_postgres.py` — a legacy
  merge reports how many rows it degraded.
- `apps/aigateway/tests/integration/test_global_cache_store_postgres.py` — genuinely concurrent
  fills carrying different metadata leave the winner's block intact.
- `packages/url4/tests/unit/test_saved_cost_reporting.py` — an amount without a provenance is
  refused, and vice versa.
- `apps/screamingface-engine/tests/unit/test_cache_saved_cost.py` — the three
  `SavedCostProvenance` literals declare identical members.

## Test plan

- **RED first, every one.** Each test above is written and observed failing for the right reason
  before its production change exists.
- Happy path: a merge that degrades nothing reports `metadata_degraded == 0`.
- Boundary: the warn-once set at its `_MAX_WARNED_METADATA_KEYS` cap still warns rather than
  growing; a block exactly at the byte cap stores, one byte over does not.
- Error paths: serialize raising, parse failing, an unpaired `ModelResponse`.
- Invariants protected: "unknown is not free" (NULL never 0), the two-totals separation, one
  warning per unreadable key, and the winner's block surviving a lost race.

## Acceptance

- Every PRD/ERD citation in the codebase resolves to a section that exists and says what the
  citing test asserts.
- A legacy-archive merge reports its degradation count at the moment it happens.
- `run_gates.py` green on all three stacks: aigateway, url4, screamingface-engine.
- `AIGW_TEST_PG=1 pytest -m needs_postgres` green, including the new concurrency coverage.
- No prior test modified, weakened, or skipped.

## Outcome

- **Actual files:** as planned, with three additions. (1) `core/admin_schemas.py` — the
  degradation count is surfaced on `AdminCacheJobOut`, not only on the job record, because the
  console is where the admin who ran the restore actually reads it. (2) `core/request_cache/
  upload_job.py` also appends a `metadata_degraded:<n>` code to the existing `warnings` list, the
  channel the console already renders. (3) One extra test,
  `test_a_failing_provider_mapper_never_logs_the_cached_body` — see Deviations.
- **Commits:** see the commit that carries this ledger.
- **Gates:** `run_gates.py` **ALL GATES GREEN on all three stacks** — url4, screamingface-engine
  (incl. `check_layering.py`), aigateway (incl. `check_no_enterprise.py`). The **append-only test
  check passed on every stack**, which is the mechanical proof that no prior test was edited,
  weakened or skipped. Directly observed counts: url4 1 255 passed; aigateway's affected unit
  slice 518 passed, reference suite 77 passed; engine saved-cost suite 26 passed.
  `AIGW_TEST_PG=1 pytest -m needs_postgres`: 30 collected, **25 passed, 5 failed** — see
  Deviations.
- **Deviations:**
  - **A finding I introduced and then had to fix.** The review asked for `exc_info=True` on the
    best-effort handlers. Applied to all three, it is wrong on one: the provider-mapper handler in
    `session.py` wraps a plugin called on the cached RESPONSE BODY, so a mapper raising with the
    payload in its message would put response content into the log through the traceback —
    breaking PRD §4.5 and the key-prefix-only discipline the store already keeps. That handler now
    logs `type(exc).__name__` instead, which separates a defect from an expected mapper failure
    without carrying content. The other two read the metadata block, which carries no content, and
    keep `exc_info`. Pinned by the extra test above, which fails if `exc_info` is restored there.
  - **5 pre-existing Postgres failures, not caused by this work.** Every test in
    `test_cache_snapshot_upload_postgres.py` that shells out to `pg_dump` fails here:
    `FileNotFoundError: 'pg_dump'`. Verified by stashing this unit's changes and re-running
    against the bare branch — the same 5 fail identically. The binary is absent from this machine;
    PR #930's own run reported them passing. The 25 that do run include all 5 tests added here.
  - **Two public contracts widened, both additively.** `LoadOutcome` gains a defaulted field (every
    call site is keyword-based) and `AdminCacheJobOut` gains a defaulted field. `ModelResponse` is
    the one genuine tightening: a construction that was previously accepted — an amount with no
    provenance, or the reverse — now raises. That is the finding's whole point, and its
    accounting-side twin `AvoidedCost` has enforced the same pairing from the start.
  - **`tortoise-dev` companion not invoked — owner decision.** The card marks it
    `mandatory: true`; the plugin is not installed. Asked and answered: the `when` condition does
    not match this unit — `bulk_loader.py` deliberately bypasses the ORM (raw asyncpg COPY and
    SQL on a connection Tortoise only hands over), and no model, migration or queryset changed.
    Recorded rather than assumed.
  - **The spec documents are RECONSTRUCTED, and say so.** `docs/spec/2026-09-13-cache-entry-
    metadata-{prd,erd}.md` were rebuilt from the ~30 docstrings that cite them, because the
    originals exist in no branch, no history and no ignore rule — while the prior ledger on this
    branch records *editing* them, which cannot have happened. Both carry a provenance note
    stating plainly that a spec derived from its implementation cannot be evidence that the
    implementation is correct. Four cited identifiers (`test #13`, `M9`, `E6`, `"spec §7"`) could
    not be pinned to an assertion and are listed as unrecovered rather than invented; numbers
    `#1`, `#6–#8`, `#10–#12`, `#22`, `#24–#28` are cited nowhere and may never have existed.
  - **PRD test #23 still does not close at its specified `level: property`.** The example matrix
    was broadened here to the line-separator family (U+2028/U+2029/U+0085/U+FEFF), which a
    property test's string strategy would have found unaided. Adding `hypothesis` was out of
    scope by the owner's scoping decision. Recorded as open in the PRD.
  - **OME-1155 was attached, not filed.** The issue pre-existed and describes this work exactly
    ("Cache the response along with cost, latency, and any metadata returned by the gateway, using
    a standardized schema"). Moved Triage → In Progress, assigned, labelled `aigateway`/`agentic`,
    and mirrored to `docs/tasks/`. Its sub-issue OME-1156 (USD cost reporting for token-based
    providers) remains untouched in Triage.
  - **Still open, deliberately not done here:** runtime validation of
    `usage_accounting.schema.json` (a design decision, not a defect), and the `archive_paired` /
    `archive_matched` naming proximity (both `Literal`-constrained; a glossary line would do).
