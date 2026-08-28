---
ticket: OME-1026
stack: aigateway
status: done
started: 2026-08-27
finished: 2026-08-27
---

# OME-1026 — Live Anthropic model discovery for /v1/models

## Intent

`GET /v1/models` publishes 10 compiled Anthropic seed aliases frozen at release time
(`AnthropicPluginSettings.models`, OME-818). This unit makes the Anthropic ID SET live —
discovered from `GET https://api.anthropic.com/v1/models` — as the **second** implementation of
the `ModelListingProvider` port shipped by OME-972 (`cc9deb4a`), reusing the existing
`ModelCatalog` snapshot-or-fallback machinery unchanged. A newly released Claude model then
appears in the gateway listing without a gateway release, and a retired alias disappears instead
of 404-ing at dispatch. The historical SF-284 Settings consumer was removed before this baseline.

Unlike OpenRouter's public catalog, Anthropic's is **credentialed-only** (401 without
`x-api-key`), so discovery is strictly **opt-in** behind one dedicated operator secret,
`AIGW_ANTHROPIC_DISCOVERY_API_KEY`. Account API keys (`credential_blobs`) and Claude-subscription
OAuth tokens are off limits for discovery. Listing only: admission, chat dispatch, and
`anthropic:static` parameter evidence are untouched.

Approved planning pack: `.agent-team-AIGW/live-anthropic-model-discovery/` (initial task
description, implementation plan D1–D11 / U1–U8, research notes, two-round plan review;
approved-plan confidence 97%).

## Planned changes

- `src/aigateway/core/parameter_discovery.py` — NEW `HeaderCapableDiscoveryClient` protocol;
  `fetch_discovery_json(..., headers=None)`; `HttpxDiscoveryClient.get` extended signature.
  `DiscoveryHttpClient` itself stays UNTOUCHED (D1 — widening it would fail pyright on every
  existing OME-972 test double).
- `src/aigateway/core/plugin_base/_contract.py` — `discover_live_models` docstring amendment
  only ("never an ACCOUNT credential; a provider MAY attach an operator-configured deployment
  discovery credential to its own allowlisted origin").
- NEW `src/aigateway/plugins/anthropic_provider/live_models.py` — `MODELS_LIST_URL`,
  `ALLOWED_ORIGINS`, `ANTHROPIC_MODELS_DISCOVERY_SOURCE`, `parse_catalog_page`,
  `fetch_live_model_ids`, `publishable_model_ids`, `live_listing_entries`.
- `src/aigateway/plugins/anthropic_provider/settings.py` — `discovery_api_key: SecretStr | None
  = None`, `live_models: bool = True`.
- `src/aigateway/plugins/anthropic_provider/plugin.py` — `model_discovery_source()`,
  `discover_live_models()`.
- `src/aigateway/plugins/anthropic_provider/discovery.py` — docstring only: both stale
  "Anthropic has NO live discovery" / §6.3 sentences gain the model-LIST carve-out (D4).
- `tests/conftest.py` — the autouse no-egress `_guarded` wrapper gains + forwards optional
  `headers` (signature-compatible; the `AssertionError` check stays FIRST). This is the ONLY
  planned pre-existing test-infrastructure edit; zero prior TEST CASES change.
- NEW `tests/unit/anthropic/test_live_models_parse.py`, `test_live_models_fetch.py`,
  `test_live_models_port.py`; NEW `tests/unit/core/test_models_route_live_catalog_anthropic.py`;
  APPEND to existing `tests/unit/anthropic/test_settings.py`; new U2 cases appended to the core
  parameter-discovery suite.
- `DEPLOYMENT.md` — concise operator section (opt-in var, off-switches, degrade ladder, replica
  sizing, tier log, restricted-key visibility caveat). Baseline is 424 lines against the
  450-line discipline, so the addition stays tight or splits out (CC-15).

No schema/model change ⇒ **S1 vacuously satisfied**, no migration. No Tortoise ORM work, so the
card's `tortoise-dev` companion `when` condition does not match.

## Test plan

RED-first, units U1–U8 in order (plan `implementation_plan.md`):

- **U1 settings** — `discovery_api_key` is secret and optional (repr leaks no key material,
  default None); `live_models` defaults true and honors `AIGW_ANTHROPIC_LIVE_MODELS`.
- **U2 headers envelope** — headers forwarded only when present (absent ⇒ byte-identical legacy
  call); a legacy client + headers fails closed as `DiscoveryError("internal_error")` with zero
  body executions (call-time argument-binding guard, CC-2); a capable client's INTERNAL
  `TypeError` is not misclassified as a signature mismatch (awaited outside the catch);
  `HttpxDiscoveryClient` attaches caller headers merged with `_IDENTITY_ENCODING` (identity
  encoding wins on conflict, CC-14) via injected `httpx.MockTransport`; a real-transport dial
  WITH headers still trips the no-egress guard as `AssertionError`, not `TypeError` (CC-1).
- **U3 strict page parse** — malformed matrix (non-dict payload; `data` missing/non-list; row
  non-dict; `id` missing/non-str; `has_more` missing/non-bool with `1` and `"true"` named
  explicitly; `has_more=true` with `last_id` missing/empty/non-str/injection-shaped);
  `has_more=false` WITH `last_id` present parses and terminates (CC-11); row type policy —
  absent `type` and `type="model"` are candidates, an unexpected string type is validated then
  excluded, a non-string type fails the whole page; strict-not-brittle pin (real row with
  `display_name`/`created_at`/`max_input_tokens` + unknown envelope keys parses); cursor
  `fullmatch` cases reject a trailing newline and an interior space.
- **U4 cursor walk** — multi-page stitch with the canned client asserting every dialed query is
  exactly `limit=1000` or `limit=1000&after_id=<expected>`; `last_id="x&limit=9999"` fails the
  refresh and dials nothing further (MAJOR-2); repeated cursor incl. a period-2 cycle ⇒
  `model_catalog_truncated` (CC-12); empty `data` with `has_more=true` bounded by the page cap;
  401/403/429/5xx ⇒ `bad_status` with the exact status (CC-10); oversized ⇒ `oversized`;
  aggregate deadline ⇒ `timeout`; count overflow ⇒ `model_catalog_too_large`; empty catalog ⇒
  `model_catalog_empty`; `x-api-key`/`anthropic-version` asserted on EVERY dial;
  `test_duplicate_ids_preserve_first_occurrence_and_upstream_order` pins
  `['claude-x-5','claude-x-5-20260101','claude-x-5']` ⇒ exactly
  `('claude-x-5','claude-x-5-20260101')` — unfolded, unsorted (D7).
- **U5 publish + merge** — shape rejections (`/`, `:`, `~`, overlong, trailing newline, interior
  space); `model_fields_set` distinction (explicit `models=[…]` lead and survive; compiled
  defaults dropped when absent upstream); bare-vs-prefixed dedupe via `canonical_model_id`
  keeping the operator row; publication mirror of the U4 order tuple.
- **U6 port** — source is None for every off combination (`live_models=False`, no key, both) with
  zero egress proved by a loud canned client; source present ⇒ merged entries; a `DiscoveryError`
  propagates untouched (core owns fallback).
- **U7 route acceptance** — fresh catalog listed as `anthropic/<id>`; no key ⇒ seeds
  byte-identical AND zero dials; `AIGW_DISCOVERY_ENABLED=false` ⇒ seeds with zero dials
  (MINOR-1); a malformed refresh never replaces the last good snapshot, using a discriminating
  body a lenient parser would have salvaged; cold malformed ⇒ seeds; route-level single-flight by
  server-side peak-depth measurement; `/v1/model-parameters` resolves a discovered-only id; that
  id reaches the patched `litellm.acompletion` with a valid profile credential; `tier=` logged
  once per change for provider=anthropic; Anthropic discovered rows coexist deduplicated with
  OpenRouter + admitted rows; captured logs contain no key material.
- **U8** — docs + this ledger's Outcome + the task mirror.

Canned clients raise `AssertionError` on unexpected dials (OME-972 correction-pass rule), so no
stray dial can launder into a silent seed fallback. Zero test egress.

## Acceptance

The 7 acceptance criteria of `initial_task_description.md`, each mapped to a named passing test:
(1) live IDs published as `anthropic/<id>`, a seed absent upstream disappears unless
operator-explicit; (2) opt-in only — without the key, zero egress and the exact seed listing;
(3) fail-closed all-or-nothing, never a partial catalog cached as fresh; (4) credential hygiene —
the key appears in no log, error, row, cache key, or `DiscoveryError`, and rides only
`api.anthropic.com`; (5) single-flight + tier logging inherited and pinned once at route level;
(6) every published ID resolves on `/v1/model-parameters` and reaches the credentialed dispatch
boundary; (7) all prior Anthropic provider/validation/conformance TEST CASES green and
unmodified, `anthropic:static` observations byte-identical.

Plus: OpenRouter's no-header path byte-identical and its prior suites unmodified; full AIGateway
gates green (`run_gates.py aigateway --base origin/main`).

## Deviations accepted at START (owner decision, 2026-08-27)

**The mandatory credentialed Anthropic Models probe was NOT run.**
`AIGW_ANTHROPIC_DISCOVERY_API_KEY` is absent from the execution environment and from both local
env files, and the only Anthropic credential material the repo holds is the Claude Code OAuth
token, which D2 puts explicitly off limits for discovery. Presented with supply-the-key /
proceed-without / stop, the owner chose **proceed without the probe**.

Consequence, disclosed: U3/U4 fixtures are derived from the Context7-verified official Models API
contract already recorded in `research_notes.md` (envelope `{data, has_more, first_id, last_id}`,
no `total_count`; row `{id, display_name, type: "model", created_at, max_input_tokens, …}`;
`limit` 1–1000; `after_id`/`before_id` cursors) rather than from an observed live response. Two
things therefore remain unverified against production: real page-2 envelope behavior, and the
observed alias/date-stamped-snapshot interleaving and order. Every unverified shape is designed to
fail CLOSED (stale-then-seeds), and the plan itself rated this seam 95% without the probe. **Zero
credentialed egress occurs anywhere in this unit's implementation or tests.**

## Outcome

Implementation complete through U1–U8 and gate-green. **Nothing staged, committed, pushed, or
opened as a PR** — no authorization for those operations was given.

### Actual files (17 — exactly the planned surface plus the two disclosed additions)

Modified (tracked):

- `apps/aigateway/src/aigateway/core/parameter_discovery.py` — NEW
  `HeaderCapableDiscoveryClient` protocol; `fetch_discovery_json(..., headers=None)` with the
  argument-binding guard; `HttpxDiscoveryClient.get`/`_read_bounded` extended signature and the
  identity-encoding-wins merge. `DiscoveryHttpClient` untouched. Module docstring's absolute
  "never credentials" claim narrowed (see deviation 6).
- `apps/aigateway/src/aigateway/core/plugin_base/_contract.py` — `discover_live_models`
  docstring: "never an ACCOUNT credential; a provider MAY attach an operator-configured
  DEPLOYMENT discovery credential to its OWN allowlisted origin".
- `apps/aigateway/src/aigateway/plugins/anthropic_provider/settings.py` —
  `discovery_api_key: SecretStr | None = None`, `live_models: bool = True`.
- `apps/aigateway/src/aigateway/plugins/anthropic_provider/plugin.py` —
  `model_discovery_source()` + `discover_live_models()` (320 → 363 lines, within 450).
- `apps/aigateway/src/aigateway/plugins/anthropic_provider/discovery.py` — docstring only; BOTH
  stale "no live Anthropic discovery / §6.3" sentences gained the model-LIST carve-out (D4, CC-13).
- `apps/aigateway/DEPLOYMENT.md` — concise "Live Anthropic Model Discovery (OME-1026)" section
  pointing at the dedicated doc (424 → 441 lines; 442 after the follow-up pass added one line to
  the rollback sentence — still under the 450 discipline).
- `apps/aigateway/tests/conftest.py` — the ONE disclosed shared-fixture edit: `_guarded` gains and
  forwards optional `headers`, `AssertionError` check still FIRST (+16/−3, zero test cases).
- `apps/aigateway/tests/unit/anthropic/test_settings.py` — +44 lines, **pure append** (+44/−0).

New:

- `apps/aigateway/src/aigateway/plugins/anthropic_provider/live_models.py` (320 lines) —
  `MODELS_LIST_URL`, `ALLOWED_ORIGINS`, `ANTHROPIC_MODELS_DISCOVERY_SOURCE`,
  `parse_catalog_page`, `fetch_live_model_ids`, `publishable_model_ids`, `live_listing_entries`.
- `apps/aigateway/docs/anthropic-model-discovery.md` (93 lines) — full operator guidance.
- Tests (139 collected across 5 new modules): `tests/unit/anthropic/test_live_models_parse.py`
  (52), `test_live_models_fetch.py` (22), `test_live_models_port.py` (33),
  `tests/unit/core/test_parameter_discovery_headers.py` (11),
  `tests/unit/core/test_models_route_live_catalog_anthropic.py` (21).
- `docs/tasks/2026-08-27-OME-1026-live-anthropic-model-discovery.md` (task mirror).

Total new tests: **141** (139 + 2 appended to `test_settings.py`).

### Commits

- `72eaa390` — `feat(aigateway): discover Anthropic models live`, on branch
  `OME-1026-live-anthropic-model-discovery` (baseline `cc9deb4a`). 17 files, +2844/-20. Committed on
  explicit owner authorization, which covered this commit only. Local planning artifacts under
  `.agent-team-AIGW/` were deliberately excluded and remain untracked.
- **Follow-up review-fix pass:** committed separately in the commit containing this ledger update.
  See "Follow-up pass" below for its contents and gates.

AIDEV-NOTE: an earlier revision of this section read "**None.**" and shipped *inside* `72eaa390`,
so the ledger denied the commit that contained it. When a commit lands, correct this section in the
same or the next pass — a ledger that misreports commit state is worse than one that omits it.

### Gates (actually run, initial pass)

- `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` → **ALL GATES GREEN**:
  ruff check ✓, ruff format --check ✓, pyright ✓ (0 errors), `check_no_enterprise.py` ✓,
  `pytest --cov=aigateway --cov-fail-under=80 -q` ✓.
- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` → **append-only check RED on
  `tests/conftest.py`, and on that file only.** Every other gate green. Executed output, verbatim:

  ```
  ✗ append-only test check — prior tests were modified/deleted (vs origin/main):
    M	tests/conftest.py  (removed/changed old line(s) [160, 163]; new content inserted after old line(s) [154, 159, 162] — inside an existing test/fixture)
  ```

  **The owner granted this exact one-file waiver on 2026-08-28.** The fixture change is retained because
  removing it re-breaks the feature: the autouse no-egress tripwire hardcoded the legacy
  `get(self, url, *, timeout_s, max_bytes)` signature, so without the optional `headers` passthrough
  every header-carrying dial through the real adapter raises `TypeError`, which `ModelCatalog`
  sanitizes into a quiet seeds listing — i.e. a test that genuinely reached the internet would pass
  green. Its `AssertionError` egress check still runs FIRST and zero test cases changed (see
  "Actual files" above). The append-only result remains mechanically RED, while the explicit
  one-file owner waiver resolves the policy decision for this change.
  Note that **no CI lane runs this gate** — no workflow in `.github/workflows/` references
  `run_gates.py` or the append-only check — so nothing automated will surface or block on it. It is
  a human review decision by construction.
- Full non-live suite: **4194 passed, 18 skipped, 37 deselected, 0 failed** (215 s).
- Focused `tests/unit/anthropic tests/unit/core tests/unit/openrouter`: **1821 passed**.
- Append-only evidence: in `git diff --numstat origin/main -- apps/aigateway/tests/`, the only
  PRE-EXISTING file with any deletions is `conftest.py` (+16/−3). Every other changed path is either
  a brand-new test module or a pure append (`−0`), and the whole test tree shows **3 deleted lines
  total**, all three inside that one fixture. So no prior test case was removed, rewritten, or
  weakened. (Re-measured after the follow-up pass: still 3, still only `conftest.py`.)
- Worktree hygiene: all **3869** unrelated tracked/untracked files verified byte-identical to their
  captured preflight hashes; 0 changed, 0 deleted, 0 unexpected new paths; the two `.codegraph/`
  entries exempt and unstaged; nothing staged (`git diff --cached` empty).
- Guard verification (OME-972 round-2 rule): with the parser temporarily made lenient
  (row-skipping), 5 tests FAIL — the 4 `id_*` parse cases and the route-level
  "never replaces the last good snapshot" test. The discriminating body genuinely guards the
  all-or-nothing rule rather than passing either way.
- Credential scan: every credential-shaped literal in the change set is an obviously fake fixture
  (`sk-ant-fixture-not-a-real-key`, `sk-ant-not-a-real-key-0123456789`, `sk-ant-profile-key`). No
  real key, no raw upstream response, no Enterprise import.

### Deviations

1. **The credentialed live probe was NOT run** (owner decision at start — see the section above).
   U3/U4 fixtures come from the Context7-verified documented contract. Real page-2 behavior and
   the observed alias/snapshot interleaving remain unverified against production; both fail closed.
   **Zero credentialed egress occurred at any point.**
2. **D1's narrowing device changed from `isinstance` to `cast` — forced by a verified gate
   failure.** The plan specified `isinstance(client, HeaderCapableDiscoveryClient)` for static
   narrowing. pyright rejects it: *"Class overlaps HeaderCapableDiscoveryClient unsafely and could
   produce a match at runtime"* — the static form of the very CC-2 finding that the check compares
   member names, not signatures. Resolution: `cast` to the capability protocol, `@runtime_checkable`
   dropped as now unused, and the runtime member-presence test replaced by a STATIC conformance pin
   (annotated assignments that make pyright verify the adapter satisfies BOTH protocols — a
   stronger claim). D1's invariant is preserved verbatim: the argument-binding boundary is the ONLY
   runtime guarantee. Behavior is unchanged for every reachable case.
3. **Operator docs split out** (CC-15 decision): depth lives in the new
   `apps/aigateway/docs/anthropic-model-discovery.md`, following the existing
   `docs/openrouter-routing-controls.md` convention, with a short pointer in DEPLOYMENT.md. That
   kept DEPLOYMENT.md at 441 lines instead of pushing it past 450.
4. **No production `assert`.** The walk's "parser promised more without a cursor" invariant is a
   fail-closed `raise DiscoveryError("malformed_json")` with its own test, not an `assert` (asserts
   vanish under `-O`).
5. **No separate publish cap** in `publishable_model_ids` (OpenRouter has `_MAX_PUBLISHED_MODELS`).
   `fetch_live_model_ids` already refuses a catalog over `_MAX_CATALOG_MODELS` and a filter cannot
   grow its input, so a second cap would be duplicated policy.
6. **`parameter_discovery.py`'s module docstring was amended** as well as `_contract.py`'s. The
   plan's file table named only `_contract.py` for docstring work, but the module's INVARIANT said
   "never credentials" — false once the capability exists. In-surface file, truth-preserving edit.
7. **`api_key` is typed `SecretStr` end-to-end** into `fetch_live_model_ids`, so plaintext exists
   on exactly one line (the header construction) and never in a frame a traceback would render.
8. **Test-only:** U7's two resolvability tests needed a credential-profile precondition
   (`ProfileIndexStore` upsert, as in the OME-972 resolvability suite) — `/v1/model-parameters`
   answers `profile_not_found` before it reports on a model.

### Residual risks

- Page-2 envelope behavior and the real alias/snapshot mix are unverified (deviation 1). Mitigated
  by fail-closed design; a first real deployment should check the logs for
  `model_catalog_truncated` / `malformed_json` before trusting the listing.
- A lying `has_more=false` mid-catalog is undetectable without a census — accepted residual, the
  same trust class as OpenRouter's `total_count`.
- The operator key's entitlements define what every account sees listed (D11) — documented, not
  engineered around.
- Each replica refreshes independently: N replicas ⇒ up to N credentialed fetches per 300 s TTL.

## Follow-up pass (2026-08-27, post-review) — implemented and committed separately

An adversarial review of `72eaa390` produced two behavioral defects worth fixing and a set of stale
comment/doc claims. Fixed on the same branch without changing the approved architecture; no locked
decision (D1-D7) was reopened.

### Behavior fixed

1. **A declared-but-blank discovery key no longer causes egress.** `AIGW_ANTHROPIC_DISCOVERY_API_KEY=""`
   (or whitespace-only) previously produced `SecretStr('')`, which is not `None`, so D3's
   `discovery_api_key is not None` predicate declared a discovery source and would dial Anthropic with
   an empty `x-api-key` — egress from a deployment that configured no key, contradicting the opt-in
   guarantee and the documented rollback. Fixed at the settings boundary with a
   `@field_validator(mode="after")` that normalizes blank to `None`, which keeps D3's predicate
   literally true as written in the plan instead of duplicating a blank-check at each of the two
   gates. A surviving key is returned untouched, never trimmed.
2. **The `Accept-Encoding` identity merge is now case-insensitive.** `{**headers, **_IDENTITY_ENCODING}`
   merged by exact dict key, so a caller spelling the field `Accept-Encoding` survived as a *second*
   key and httpx emitted both lines (`gzip, identity`). HTTP field names are case-insensitive, so the
   documented "identity always wins" was false for every spelling but lowercase. Replaced with a
   comprehension that drops all case-variants before applying identity. The old defect was fail-closed
   (`_bounded_body` rejects any non-identity `content-encoding` *before* byte accounting, so the byte
   cap was never bypassable) — this restores the documented contract, it does not close a byte-cap hole.

### Tests added (append-only; zero prior test cases touched)

- `tests/unit/anthropic/test_settings.py` — blank key normalizes to `None` (6 blank forms, via env
  and direct construction) + a guard that a real key survives byte-intact.
- `tests/unit/anthropic/test_live_models_port.py` — a blank key declares no source and never dials
  (3 blank forms, asserted against a client that raises on any dial).
- `tests/unit/core/test_parameter_discovery_headers.py` — identity wins for 4 caller spellings. The
  assertion reads `request.headers.multi_items()`, **not** `dict(request.headers)`: a dict view JOINS
  duplicate field lines into `'gzip, identity'` and would have passed while two lines went on the wire,
  which is exactly why the original test did not catch this.

RED confirmed before the fixes (13 failed / 1 passed — the passing one being the deliberate
over-reach guard), GREEN after.

### Documentation and ledger corrections

- `core/discovery_runtime.py` — the module INVARIANT claimed "no credential is in scope" for the whole
  shared client. Narrowed to the `observe` path (where it remains true) and stated that a provider may
  now attach a deployment credential to its own allowlisted origin, with a note that adding request
  logging or an httpx event hook to this client can now touch a credential.
- `core/parameter_discovery.py` — module docstring said providers fetch "FIXED public catalogs"
  uniformly; now distinguishes the public catalogs from Anthropic's credentialed one.
- `core/plugin_base/_contract.py` — the live-LISTING hook said "fixed public catalog"; now "fixed
  provider catalog". The two neighbouring "public" mentions on the *parameter* hooks are accurate and
  were left alone.
- `plugins/anthropic_provider/live_models.py` — the `SecretStr` rationale claimed the plaintext exists
  on "exactly one line". Corrected: `SecretStr` strictly reduces the rendered-plaintext surface and can
  never enlarge it, but the header mapping it builds is a live local in three frames, so a
  locals-capturing error reporter would still see it. Nothing in `src/` renders locals today.
- `docs/anthropic-model-discovery.md` — the SF-284 bullet asserted a current consumer "needs no
  change", but git ancestry and OME-642 establish that the consumer was removed before this
  baseline. Replaced it with historical context plus the measured facts: with
  `AIGW_ANTHROPIC_MODELS` unset the published order becomes raw upstream order, and sampling evidence
  comes from a hand-reviewed allowlist of exact ids (measured: `claude-sonnet-4-5` → supported;
  `claude-sonnet-4-5-20250929` and the unreviewed alias `claude-opus-4-1` → fail-closed), so every
  newly discovered id publishes a row without sampling parameters until reviewed. Explicitly labelled
  as pre-existing OME-583 policy that this unit did not change. There is no live dropdown consumer
  to validate in this repository or an adjacent one.
- The blank-key rule is now documented in that file's rollback sentence and off-switch table, and in
  `DEPLOYMENT.md`.
- This ledger's `### Commits` section and the task mirror both claimed the work was uncommitted while
  shipping inside `72eaa390`; both corrected.

### Deliberately NOT changed

- Snapshot-id sampling policy and F16/F17 production behavior — out of scope by owner instruction.
- `AIGW_ANTHROPIC_LIVE_MODELS=""` boot behavior — flagged only, not touched.
- `tests/conftest.py` — the fixture change is preserved under the owner-approved one-file waiver.

### Gates (follow-up pass, actually run)

- Focused `tests/unit/anthropic tests/unit/core tests/unit/openrouter` → **1835 passed** (1821 + the
  14 new cases; no prior test removed, rewritten, or weakened).
- Full non-live suite `pytest -m "not live"` → **4208 passed, 18 skipped, 37 deselected, 0 failed**
  (145 s) = the prior 4194 plus the same 14. Run beyond the requested focused scope because fix 2
  lands in the SHARED discovery transport that OpenRouter also uses; no regression there.
- `uv run ruff check .` → All checks passed. `uv run ruff format --check .` → 530 files already
  formatted. `uv run pyright` → **0 errors, 0 warnings**.
- `run_gates.py aigateway --base origin/main` → append-only still RED on `tests/conftest.py` **only**;
  the three appended test files produced no new offender. The owner approved that exact one-file
  waiver on 2026-08-28.
- Final `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` → **ALL GATES GREEN**.
  The first final run hit the pre-existing timing-sensitive auth test
  `test_unknown_user_timing_close_to_wrong_password`; it passed 3/3 in immediate isolated reruns,
  and the complete gate then passed unchanged. No auth code or prior test was modified.
