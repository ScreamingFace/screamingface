---
ticket: OME-1026
stack: aigateway
status: done
started: 2026-08-27
finished: 2026-09-02
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

Implementation complete through U1–U8 and gate-green. **Committed as `72eaa390`, with review
remediation in `056971a4`**, both on explicit owner authorization for those commits. Not pushed and
no PR is open. See `### Commits` below, and "Profile-scoped rework" at the end of this ledger — the
dedicated-deployment-key design recorded above was subsequently REJECTED by the owner and replaced.

AIDEV-NOTE: this opener previously read "Nothing staged, committed, pushed, or opened as a PR" and
shipped inside the very commits it denied — the F24 defect, recurring here after `### Commits` alone
was corrected. When a commit lands, correct EVERY commit-state sentence in this file, not just the
subsection titled after it.

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

## Profile-scoped rework (2026-08-28) — DONE

**The design recorded above is REJECTED.** Owner brief:
`.agent-team-AIGW/live-anthropic-model-discovery/profile_scoped_rework_prompt.md` (authoritative;
overrides the original plan, prompt, review, and any conflicting test). Baseline `056971a4`.

### Intent

Anthropic model discovery becomes PRIVATE and PROFILE-SCOPED, driven by the caller's own already
stored account credential, instead of one deployment-wide catalog behind a dedicated
`AIGW_ANTHROPIC_DISCOVERY_API_KEY`. OpenRouter stays a PUBLIC GLOBAL catalog. No credential-derived
model may ever enter the global `GET /v1/models` response, and no account may observe another's
private catalog.

### Owner decisions taken as given

1. Remove the dedicated deployment discovery key entirely; no backward compatibility for it.
2. Two discovery scopes: `PUBLIC_GLOBAL` (shared, safe) and `PROFILE_CREDENTIAL` (private, per profile).
3. Reuse existing profiles + stored credentials — no re-entry, no migration.
4. Max 3 s user-facing wait; refresh continues in the background and a later request observes it.
5. Contract must generalize to future public Hugging Face and profile-scoped OpenAI/Gemini — not
   implemented here.

### Planned changes

Core (new):
- `src/aigateway/core/model_discovery_scope.py` — `DiscoveryScope`, `ProviderAuthContext`.
- `src/aigateway/core/background_refresh.py` — app-lifetime deduped, shielded, bounded task manager.
- `src/aigateway/core/profile_model_catalog.py` — private per-profile snapshot service + LRU.

Core (modified):
- `core/plugin_base/_contract.py` — scope-aware port; replace the global-only listing hook.
- `core/model_catalog.py` — public scope only; reject a profile-scoped provider outright.
- `routes/models.py` — concurrent public refresh, deterministic order, seeds for private providers.
- `routes/auth.py` — new `GET /v1/auth/{provider}/profiles/{name}/models`; invalidate private
  snapshots on api-key publication, delete, and refresh.
- `main.py` — public prewarm at startup (non-blocking), task manager wired + closed at shutdown.

Anthropic:
- `plugins/anthropic_provider/settings.py` — DELETE `discovery_api_key` and its validator.
- `plugins/anthropic_provider/plugin.py` — declare `PROFILE_CREDENTIAL`; discovery header strategy;
  refuse non-`api_key` auth with a sanitized reason and zero egress.
- `plugins/anthropic_provider/live_models.py` — fetch boundary consumes an allowlisted header
  context instead of a `SecretStr` setting.

Docs: `docs/anthropic-model-discovery.md`, `DEPLOYMENT.md`, this ledger, the task mirror.

### Test plan (RED first)

Replace, not preserve, the dedicated-key tests. New/rewritten coverage:
- stored Anthropic api-key profile discovered with no re-entry; OAuth profile → ZERO egress + reason;
- account A's private models never visible to account B; two profiles → independent snapshots;
- key replacement invalidates the old snapshot; deletion evicts and cancels in-flight refresh;
- missing / non-authenticated profile handling;
- N concurrent callers → ONE refresh; request cancellation does NOT cancel the shared refresh;
- 3 s budget returns stale-or-seeds while refresh continues; a later request sees the snapshot;
- public providers refresh CONCURRENTLY; deterministic provider/model order;
- OpenRouter remains one global snapshot across accounts; no private model in `/v1/models`;
- `AssertionError` / unexpected programming errors stay observable, never degraded silently;
- shutdown cancels and awaits unfinished tasks; strict pagination, no partial publication.

Injected clocks, events and barriers only — no wall-clock sleeps, no real provider calls.

### Acceptance

Every bullet above green; full non-live suite, ruff, format, pyright, `check_no_enterprise.py`, and
`git diff --check` clean; zero references to `AIGW_ANTHROPIC_DISCOVERY_API_KEY` outside historical
ledger prose.

### Outcome — DONE (2026-08-28)

Reworked end-to-end. The dedicated deployment discovery key is gone; Anthropic discovery is
private and profile-scoped; OpenRouter stays public and global. Not committed, not pushed, no PR
(no authorization requested or granted for this pass).

#### Architecture as built

Two scopes, declared by the provider before any fetch and enforced by two different caches:

| Scope | Cache | Identity | Audience | Hook |
|---|---|---|---|---|
| `PUBLIC_GLOBAL` | `ModelCatalog` (existing) | provider | every account, `GET /v1/models` | `discover_live_models` |
| `PROFILE_CREDENTIAL` | `ProfileModelCatalog` (new) | `(account_id, provider, profile_name, credential_revision)` | that profile's owner only | `discover_profile_models` |

Isolation is structural, not procedural:

- `ModelCatalog.entries_for` refuses any non-`PUBLIC_GLOBAL` scope **before** consulting the
  source (`core/model_catalog.py:135`), so no cache slot is even opened. Refusal is a normal
  answer (`None` → seeds), not an error.
- `AnthropicProviderPlugin` does not define `discover_live_models` at all — asserted structurally
  via `vars(type(plugin))`, so there is no public code path that could produce a credentialed row.
- The credential generation rides **inside** the private cache identity, so a rotated key cannot
  be served an old snapshot even if every invalidation call site were forgotten.

Wait and work are separated because `ObservationCache.get_or_refresh` awaits its refresh while
holding the single-flight lock: `asyncio.wait_for(..., 3)` there would cancel the winner, record
no failure, and turn one upstream attempt into N. `BackgroundRefreshManager` therefore owns task
lifetime (`asyncio.wait`, which never cancels what it waits on) and `ProfileSnapshotStore` owns
freshness policy and bounded memory.

#### Actual files vs planned

Planned as three new core modules; shipped as **four** — `profile_model_catalog.py` reached 521
lines, over the project's 450-line limit, and split by responsibility into the snapshot
store (bounded memory + freshness) and the catalog (orchestration + refusal gates).

New source (5): `core/model_discovery_scope.py` (95), `core/background_refresh.py` (214),
`core/profile_snapshot_store.py` (239), `core/profile_model_catalog.py` (367),
`routes/profile_models.py` (134).

Modified source (9): `core/model_catalog.py`, `core/plugin_base/_contract.py`, `main.py`,
`routes/models.py`, `routes/auth.py`, `plugins/anthropic_provider/{settings,plugin,live_models}.py`,
`plugins/openrouter_provider/plugin.py`.

Deviation from plan: the new endpoint lives in a new `routes/profile_models.py`, **not** in
`routes/auth.py` as the plan said — `auth.py` is already far past the file-size limit and this is
an independent responsibility. `routes/auth.py` gained only the two call sites (invalidate on
session change, post-commit trigger on api-key publication).

#### Tests

Replaced, per the owner brief, rather than preserved — the rejected dedicated-key architecture's
tests encode a contract that no longer exists.

- New: `tests/unit/core/test_model_discovery_scope.py`, `test_background_refresh.py`,
  `test_profile_model_catalog.py`, `test_profile_models_route.py`.
- Renamed via `git mv` + rewritten: `test_models_route_live_catalog_anthropic.py` →
  `test_models_route_anthropic_scope_boundary.py` (was: "the global catalog publishes discovered
  Anthropic rows"; now: "the global catalog can never publish them").
- Rewritten: `tests/unit/anthropic/test_settings.py` (the removed field's absence is now the
  assertion), `test_live_models_port.py` (header context replaces the `SecretStr` setting).
- Signature-only: `test_live_models_fetch.py`.

Dropped coverage worth naming: two cases asserted that `/v1/model-parameters` resolves an
Anthropic id that exists only in a discovered listing. A privately discovered id is deliberately
not in the global catalog, so that chain no longer exists. Parameter evidence for seeded ids is
unchanged and still `anthropic:static`.

No wall-clock sleeps, no real provider calls, no real credentials: injected clocks, events and
barriers only.

#### API contract

`GET /v1/auth/{provider}/profiles/{name}/models` — authenticated, account-scoped.

```json
{"object": "list", "provider": "anthropic", "profile": "work",
 "status": "fresh|stale|refreshing|fallback", "reason": null, "data": [ /* model_row shape */ ]}
```

`404 unknown_provider` / `404 profile_not_found` (another account asking for the same profile name
gets the latter). Everything else — a rejected key, a slow catalog, an unsupported auth type, the
kill switch — answers `200` with the compiled seeds plus a sanitized `reason`. `data` rows are built
by the same `model_row` as `GET /v1/models`, so one parser serves both.

Plugin port (`core/plugin_base/_contract.py`), all defaulted so no existing provider changes:
`model_discovery_scope()`, `profile_discovery_unsupported_reason(*, auth_type)`,
`discover_profile_models(*, client, limits, auth)`,
`discovery_credential_strategy_for(profile_name, *, credential_store)`.

Generalization the brief asked for, without implementing it: a future public Hugging Face provider
declares `PUBLIC_GLOBAL` and implements `discover_live_models` — nothing else. A future
profile-scoped OpenAI/Gemini provider declares `PROFILE_CREDENTIAL` and implements
`discover_profile_models` + `discovery_credential_strategy_for`; the route, the catalog, the
identity, the wait budget and the invalidation call sites are provider-agnostic already.

#### Gates actually run

- Full non-live suite `uv run pytest -m "not live"` → **4268 passed, 18 skipped, 37 deselected, 0 failed (189 s)**.
- `uv run ruff check .` → All checks passed. `uv run ruff format --check .` → 539 files already
  formatted. `uv run pyright` → **0 errors, 0 warnings, 0 informations**.
- `uv run python scripts/check_no_enterprise.py` → OK. `git diff --check` → clean.
- Focused: the four new core suites + all of `tests/unit/anthropic` → 358 passed.
- `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` → **ALL GATES GREEN**
  (`ruff check` · `ruff format --check` · `pyright` · `check_no_enterprise.py` ·
  `pytest --cov=aigateway --cov-fail-under=80`).

Process note worth recording: an intermediate pass ran `pyright src/aigateway/` and read "0 errors"
as the gate. The card's gate is the bare `uv run pyright`, whose configured scope includes `tests/`
— where **36 errors** were sitting (unnarrowed `Task | None` from `start_or_join`, `**overrides:
object` into pydantic settings, `object()` where a `DiscoveryHttpClient` is required, an
incomplete `CredentialBlobStore` fake). All 36 were test-side and are fixed; two fixes made the
doubles stricter rather than looser (`_NoClient` and `_FakeCredentialStore` now carry the real
protocol signatures, so the type checker confirms the catalog is called the way production calls
it, and the store fake fails loudly if discovery ever writes, deletes, or mutates a credential).
A CLI-scoped type check is not the gate.

#### Append-only status (rule 5) — measured, not assumed

This pass rewrote and renamed tests, which rule 5 normally forbids — so it was measured rather
than argued. `run_gates.py aigateway --base origin/main` reports exactly **one** offender:

```
✗ M tests/conftest.py  (removed/changed old line(s) [160, 163]; new content inserted after
                        old line(s) [154, 159, 162] — inside an existing test/fixture)
```

That is the pre-existing owner-approved one-file waiver from the previous pass, unchanged, still
altering zero test cases. Every test this pass replaced was introduced **within this same unmerged
branch** by `72eaa390` and has never existed on `origin/main`; against the merge base the whole
OME-1026 test surface is **+1778 / -0**. So the replacement the owner authorized ("rather than
preserving unmerged compatibility") did not touch a single merged test — rule 5's property holds
against main for everything except the already-waived file.

Branch position: `origin/main` is now `dd51ea81`, 34 commits ahead of this branch's base
`cc9deb4a`. **None of those 34 commits touch `apps/aigateway/src` or `apps/aigateway/tests`**
(`git diff --stat cc9deb4a..origin/main -- …` is empty), so the branch is behind main but has no
conflict surface in this unit's area.

#### Residual risks (reported, not silently accepted)

- **Per-account fairness is undecided.** Snapshots and in-flight slots share one 512-entry bound
  per replica, so a tenant with many active profiles can evict another's snapshot (degrading it to
  a re-fetch, never to another account's data) and can occupy in-flight slots (degrading others to
  `refresh_deferred`). No quota was invented; this is a product decision.
- **The wait budget is not independently tunable.** It reuses `AIGW_DISCOVERY_TIMEOUT_SECONDS`
  (3.0), which is also one dial's timeout. Lowering it to tighten dials also tightens the
  user-facing wait.
- **Multi-worker/multi-replica:** caches are process-local, so N replicas mean up to N refreshes
  per TTL per *active* profile, and an invalidation on one worker does not reach the others. The
  credential revision in the identity is what makes that safe: a stale snapshot on another worker
  is unreadable under the new credential generation, so the worst case is a redundant fetch, never
  a wrong answer.
- **A background `AssertionError` only logs.** An awaited refresh re-raises non-`DiscoveryError`
  through `_terminal_reason`, so the no-egress tripwire fails the test. A refresh nobody awaits
  (the post-commit trigger, prewarm) reports through `on_error` — visible in logs, but not
  test-failing on that path.
- **`/v1/model-parameters` no longer resolves a discovered-only Anthropic id**, by design: a
  private id is not in the global catalog. Whether that route should consult the caller's private
  catalog is an open product question.

#### Constraints honored

Zero real credentials, zero production probes — fakes and canned transports only. No credential,
credential-derived identifier, or upstream body is logged, cached in a key, or returned; the
plaintext key never appears in a cache key, log, exception, metric or response. No tenant
credential is enumerated or decrypted at startup: `auth_provider` is a deferred callable invoked
only inside a refresh that is actually about to dial. Nothing committed, staged, pushed, or
published; no unrelated worktree file touched.

## Final remediation pass (2026-08-31) — SUPERSEDED, closure WITHDRAWN

> **Every F1-F8 closure statement in this section is withdrawn.** Independent adversarial probes
> reproduced failures this pass's green suite did not cover, so its verdict of DONE was wrong and
> is not evidence of anything. The section is kept for the record of what was claimed and what was
> changed; the standing verdict for each fix is in
> *Adversarial remediation pass (2026-08-31)* below. Per-fix disposition:
>
> | Fix | Claimed here | Actually still open, reproduced by the adversarial pass |
> |---|---|---|
> | F1 | closed by a route class | 422 and unexpected 500 were rendered by the APPLICATION's handlers, outside the route class, with no policy at all; the policy also REPLACED an existing `Vary` instead of merging it |
> | F3 | "the un-atomic window stops existing" | the provider strategy still persisted the credential during the provider call, so a stale refresh could overwrite a replacement's blob and restore the previous owner's metadata at the new generation |
> | F4 | closed by a re-read fence | the fence itself held, but F3 could restore a previous owner AT the current generation, which the fence cannot see |
> | F5 | "already closed" | `aclose()` cleared task tracking while cancellation-resistant tasks were still live |
> | F6 | "lossless and loud" | the sink retained live exception objects, and its counters were mutated without synchronisation |
> | F7 | hard row bound | `settled_answer` labelled a retained entry `fresh` regardless of age, so an oversized-snapshot refusal could resurrect an expired listing |
> | F8 | compliant, with auth.py/plugin.py as an accepted pre-existing deviation | not an accepted deviation: both files are split in the adversarial pass |
>
> F2 is the one fix whose closure survives adversarial review unchanged.

Source: `.agent-team-AIGW/live-anthropic-model-discovery/profile_scoped_rework_final_fix_prompt.md`,
authoritative and overriding the previous closure report where they conflict. Verdict on the prior
pass: **NOT MERGE-READY**. Owner decisions 1-8 in that prompt are SETTLED and are not re-litigated
here; the two previously-open items (D-R1 hook scope, D-R3 row budget) are now decided by the owner
and are closed below.

### Verification of each claim against the code (before any edit)

| Fix | Claim | Verified at | Verdict |
|---|---|---|---|
| F1 | policy installed only after `CurrentAccount` resolves, so pre-handler 401/403 bypass it | `routes/profile_models.py:62-86` sets headers INSIDE the endpoint; `core/auth/middleware.py:33-112` raises `HTTPException` 401/403 during dependency resolution, before the endpoint runs | CONFIRMED |
| F2 | only a 3 s DEFAULT, not a hard maximum | `routes/models.py` uses `runtime.limits.timeout_s`; `profile_model_catalog.py:399` uses `settings.discovery_timeout_seconds`; `config.py:192-197` bounds it with `gt=0` only | CONFIRMED |
| F3 | manual OAuth refresh writes the blob before the generation bump | `routes/auth.py:1480-1481` `refresh_credentials()` writes the credential, then `_profile_refresh_lifecycle`'s success branch (`:229-234`) calls `upsert`, which bumps at `profile_index.py:95` | CONFIRMED |
| F4 | private-id validation and contract construction read the profile twice | `routes/model_parameters.py:250-252` reads generation g; `:152` `_credential_target_for_chat` re-reads (`chat_credentials.py:177`) | CONFIRMED |
| F5 | must stay closed | `background_refresh.py:168-179` (`inflight` counts every not-done live task), `:293-316` (bounded `aclose`) | ALREADY CLOSED |
| F6 | drain-only fixture; overflow can pass green | `tests/conftest.py:273-301` drains without asserting; `background_refresh.py:107-112` `assert_no_unexpected` inspects only `retained`, and `take_unexpected` resets `_dropped_unexpected` at `:95` | CONFIRMED |
| F7 | carve-out + unmeasured byte claims | `profile_snapshot_store.py:303` `len(self._records) > 1` carve-out; byte estimates at `profile_snapshot_store.py:55-60` and `config.py:186-189` | CONFIRMED |
| F8 | source files over the 450-line limit | `main.py` 496, `core/plugin_base/_contract.py` 475 | CONFIRMED (prompt said 497/476; the counts are 496/475) |

Additional inaccuracy found while verifying, not in the prompt: `core/discovery_runtime.py`'s module
docstring still describes the REJECTED design ("a provider MAY attach an operator-configured
DEPLOYMENT discovery credential as static headers ... and the live model catalog does exactly that
for Anthropic"). No such credential exists any more. Corrected as part of the documentation fix.

### Planned changes

1. **F6** — `background_refresh.py`: `take_unexpected()` returns retained AND dropped; a nonzero
   dropped count fails `assert_no_unexpected`. `tests/conftest.py`: autouse teardown ASSERTS, the
   shared env disables Anthropic private discovery via `PLUGIN.settings`, discovery suites opt in
   through a named fixture, and the TestClient fixtures drain their app's discovery tasks at
   teardown so the assertion runs after the work has landed. Evidence the lever is safe: the
   tripwire test at `tests/unit/core/test_models_route_live_catalog.py:211` is about OPENROUTER
   (default `enabled=False`), not Anthropic, so disabling Anthropic's `live_models` per test does
   not touch it - which is what makes the suite-wide assertion possible now and is why D-R1 closes.
2. **F1** — a custom `APIRoute` whose handler wraps dependency resolution, applied to the profile
   listing router and the model-parameters router. `HTTPException` raised by a dependency gets the
   policy merged into `exc.headers`; a normal response gets it on the way out.
3. **F2** — one named helper `user_wait_budget(configured) = min(configured, MAX_USER_WAIT_S=3.0)`,
   applied to the global listing wait and to the profile catalog's budget. Provider refresh keeps
   its own longer aggregate deadline; expiry never cancels the shared task.
4. **F7** — the store REFUSES a snapshot larger than `max_rows` (raising, so it cannot be ignored),
   the profile catalog records a sanitized damped failure, and `_trim` loses the `len > 1`
   carve-out. Byte estimates deleted everywhere.
5. **F3** — `credential_generation` becomes an explicit OWNERSHIP fence: `upsert` no longer bumps,
   and a new `publish_credential` bumps atomically for the writes that really replace the owner
   (api-key publication, OAuth callback, bootstrap). A routine token refresh keeps its generation,
   which removes the split-write window rather than adding a transaction to it.
6. **F4** — the generation used for private-id validation is re-checked against the durable index
   after profile resolution; a rotation in between refuses with a retryable 409 instead of a
   mixed-generation 200. Error precedence is preserved deliberately (see Deviations).
7. **F8** — extract `discovery_lifecycle.py` (app-level discovery wiring) out of `main.py`, and
   `core/plugin_base/_discovery.py` (the model-discovery hooks + `ModelDiscoverySource`) out of
   `_contract.py`, preserving the exported `ProviderPluginBase` API.

### Test plan

One focused file per fix, RED before GREEN, deterministic events/barriers/injected clocks/canned
transports only. No live probe of any kind.

### Acceptance

Every command in the prompt's Required Verification section, run and reported with its real output;
the F1-F8 closure table; the ten numbered confirmations; final line counts for every source file
near the limit; append-only checked against `origin/main` with the waiver and the two approved
re-pins attributed separately.


### Outcome — DONE (2026-08-31)

All eight fixes implemented, each driven by a focused test that was RED against the pre-fix code and
GREEN after. Full suite **4384 passed, 18 skipped, 37 deselected** (`-m "not live"`), ruff/format/
pyright clean, all gates green. Nothing committed, pushed, or staged: the only staged entry remains
the pre-existing rename.

#### F1-F8 closure table as claimed on 2026-08-31 — WITHDRAWN

Read the "Final verification" and "Remaining risk" columns below as *what this pass believed*, not
as findings. Seven of the eight are contradicted by the adversarial pass (see the disposition table
at the top of this section); the "Code changed" column remains an accurate record of the edits.

| Fix | Root cause | Code changed | Failing regression test added FIRST | Verification CLAIMED (withdrawn) | Risk as understood then |
|---|---|---|---|---|---|
| **F1** private cache policy at a boundary | The policy was set INSIDE the endpoint body. `CurrentAccount` is a FastAPI dependency, and a dependency that raises does so while the framework is *solving* dependencies — before the body runs — so every pre-handler 401/403 was emitted with no cache directives at all. | NEW `routes/private_cache.py` (`PrivateCacheRoute.get_route_handler` wraps `super().get_route_handler()`, merging the policy into `exc.headers` on `HTTPException` and onto `response.headers` otherwise; `private_cache_route(*extra_vary)` factory). `routes/profile_models.py` and `routes/model_parameters.py` use it as `route_class` and lose their in-body header code. `_IDENTITY_VARY` is imported from `core/auth/cloudflare_identity` so the `Vary` cannot drift from the header the mode actually reads. | `test_private_cache_policy_pre_handler.py` (18) — parametrized over BOTH routes: missing / malformed / expired bearer, valid-token-no-account, untrusted peer (403), missing `X-User-Email`, deactivated identity, handler-raised 400/404, kill-switch 200, plus a structural test that the policy is a route class. | 18/18 GREEN; falsified by reverting the route class (the pre-handler cases fail). | An intermediary that ignores `Cache-Control` is outside the gateway's reach. |
| **F2** hard 3 s listing budget | Category error: `AIGW_DISCOVERY_TIMEOUT_SECONDS` answers "how long may one dial take", the routes needed "how long may a human wait". They coincide at the 3.0 default, so every prior test passed. | NEW `core/discovery_budget.py` (`MAX_USER_WAIT_S = 3.0`, `user_wait_budget(configured) = min(configured, 3.0)`). Applied at `routes/models.py` (global listing) and in `build_profile_model_catalog` (`profile_model_catalog.py`). `runtime.limits` is passed through UNTOUCHED — the clamp bounds the wait, never the work. | `test_listing_wait_budget.py` (6) with `AIGW_DISCOVERY_TIMEOUT_SECONDS=10`: both routes clamp to 3.0, a sub-3 s configuration is honoured as-is, the parked refresh stays alive and publishes on a later request. | 6/6 GREEN; falsified by un-clamping both sites (exactly the 3 behavioural tests fail). | 3.0 is a constant, not a setting — deliberate (owner decision 6). |
| **F3** honest, atomic credential generation | The manual OAuth refresh path wrote the credential blob and then bumped the generation in a second durable write; a crash between them left a new secret under an old cache identity. | `core/profile_index.py`: `_bump_credential_generation` redefined as an **ownership/authentication fence**; `upsert(..., credential_owner_unchanged: bool = False)`. `routes/auth.py`: the refresh-lifecycle success branch passes `credential_owner_unchanged=True` and `retire_private_catalog=False` (new parameter on `_invalidate_profile_session`). A routine OAuth refresh no longer bumps — the un-atomic window stops existing rather than getting guarded. | `test_credential_generation_ownership_fence.py` (8): publication/callback/bootstrap DO bump; routine refresh does NOT; a cancellation *and* a crash injected around a manual OAuth refresh leave the schedule consistent; the snapshot survives a refresh; an OAuth profile still gets `unsupported_auth_type`. | 8/8 GREEN. | An api-key "refresh" only re-reads the stored key (documented no-op), so the fence is exercised for OAuth on that path. |
| **F4** private model-parameter rotation TOCTOU | `/v1/model-parameters` reads the profile index twice — once to admit a private id under generation *N*, once (`_credential_target_for_chat`) to resolve the credential context the document is built from. A replacement landing in between produced a 200 mixing generations. | `routes/model_parameters.py`: `_private_catalog_ids` now returns `(ids, generation)`; the rescue path captures it; after building the document `_refuse_mixed_generation` re-reads the durable index and raises **409 `credential_generation_changed`** when the generation changed *or is gone*. Scoped to the rescue path only — a seeded/admitted id never reads a private catalog, so it pays nothing. | `test_private_parameter_generation_fence.py` (6): a **barrier** injected at the exact seam (wrapping `_credential_target_for_chat`) — refusal, refusal carries the F1 policy, retry succeeds, no-rotation still 200, seeded id unaffected, profile *deleted* at the seam also refused. | 6/6 GREEN; the pre-existing cross-account (`:178`) and sibling-profile (`:217`) 404 tests in `test_private_parameter_contract_url.py` still pass unmodified. | A 409 is a retry, not a stall: the client must retry. Documented in the reason vocabulary. |
| **F5** in-flight accounting | Already closed by the prior pass (`inflight` counts every not-done live task; bounded `aclose`). | None. | None added; the existing capacity suite re-run. | `test_background_refresh_capacity.py` GREEN, unmodified. | — |
| **F6** suite-wide, lossless background-error assertion | The fixture drained without asserting, and `take_unexpected()` reported only *retained* errors — a full sink silently dropped the rest, so overflow could pass green. | `core/background_refresh.py`: `take_unexpected()` returns retained **and dropped**; a nonzero dropped count fails `assert_no_unexpected`. `tests/conftest.py`: autouse `_background_discovery_errors` resets on the way in and ASSERTS on the way out for every test in the suite; autouse `_anthropic_private_discovery_disabled` and `_public_catalog_prewarm_disabled` stop tests performing discovery they never asked for; named opt-ins `anthropic_live_discovery` / `public_catalog_prewarm`; the `client` fixture drains the app's discovery before the assertion reads the sink and before the lifespan cancels those tasks. | `test_background_error_overflow.py` (10): overflow is loud, the sink is lossless across the boundary, a cancelled task reports nothing, the observation point fails the *causing* test. `test_public_prewarm_lifespan.py` (3): the real prewarm still runs under a real lifespan via the opt-in. | 13/13 GREEN, and the whole 4384-test suite now runs under the autouse assertion. | Tests that opt in must drain; the shared drain barrier is bounded at 5 s so a deliberately parked refresh cannot hang the session. |
| **F7** hard total row bound | `_trim` had a `len(self._records) > 1` carve-out, so one oversized snapshot could exceed the configured maximum indefinitely; and the code/docs carried unmeasured byte estimates. | `core/profile_snapshot_store.py`: `store()` REFUSES a snapshot larger than `max_rows` (records `failed_at`/`reason`, trims, raises `DiscoveryError(CACHE_BUDGET_REASON)`, deliberately leaving the previous snapshot in place); `_trim`'s carve-out deleted — `while self._records and self.retained_rows > self._max_rows: popitem(last=False)`. New `CACHE_BUDGET_REASON = "cache_row_budget_exceeded"`, distinct from the provider-side `model_catalog_too_large`. Byte estimates removed from `profile_snapshot_store.py`, `config.py`, `DEPLOYMENT.md`, `docs/anthropic-model-discovery.md`, and this ledger. | `test_profile_catalog_row_bound.py` (4) end-to-end through the real route with a test-owned clock and `max_rows=6`: 20 rows retain **nothing** and report the reason, the refusal is damped (not re-dialled per request), a stale snapshot beats seeds when the replacement is refused, and the bound holds cumulatively across five profiles. | 4/4 GREEN, plus 11 GREEN in the re-pinned store suite; falsified by restoring the carve-out (6 tests fail). | An operator whose catalog exceeds the budget gets seeds until they raise it — by design, and the reason says so. |
| **F8** 450-line compliance | `main.py` 496 and `core/plugin_base/_contract.py` 475 were over the limit. | NEW `src/aigateway/discovery_lifecycle.py` (145) takes the app-level discovery wiring (`build_discovery_runtime`, `install_discovery`, `start_public_prewarm`, `shutdown_discovery`) out of `main.py` — an APP-layer module, so `app.state` access does not migrate into `core/`. NEW `core/plugin_base/model_discovery.py` (218) takes `ModelDiscoverySource` and the six discovery hooks out of `_contract.py` as a **mixin**; `ProviderPluginBase` now inherits `(ModelDiscoveryContract, ProviderPluginCore[TSettings])`. No compatibility wrappers. | Structural, verified by the existing plugin-contract and lifespan suites plus `wc -l`. | `main.py` **407**, `_contract.py` **307**; full suite GREEN with no import shims. | `routes/auth.py` (1509) and `plugins/openrouter_provider/plugin.py` (572) remain over the limit and were already non-compliant on `origin/main` — see deviations. |

#### 1. Exact files changed in this pass

Source (new):

* `src/aigateway/core/discovery_budget.py` (37) — F2
* `src/aigateway/routes/private_cache.py` (95) — F1
* `src/aigateway/core/plugin_base/model_discovery.py` (218) — F8
* `src/aigateway/discovery_lifecycle.py` (145) — F8 *(created earlier in this pass)*

Source (modified):

* `src/aigateway/routes/models.py` (127) — F2
* `src/aigateway/core/profile_model_catalog.py` (409) — F2, F7 (`max_rows` property)
* `src/aigateway/routes/profile_models.py` (154, was 175) — F1
* `src/aigateway/routes/model_parameters.py` (334) — F1, F4
* `src/aigateway/core/profile_index.py` (391) — F3
* `src/aigateway/routes/auth.py` (1509) — F3
* `src/aigateway/core/profile_snapshot_store.py` (354) — F7
* `src/aigateway/core/background_refresh.py` (352) — F6
* `src/aigateway/config.py` (326) — F7 (byte claim removed) and F2 (an INVARIANT anchor on
  `discovery_timeout_seconds` recording that it is the DIAL deadline and cannot lengthen the
  user's wait)
* `src/aigateway/core/plugin_base/_contract.py` (307, was 362 on `origin/main`) — F8
* `src/aigateway/core/plugin_base/__init__.py` (61) — F8
* `src/aigateway/main.py` (407, was 423 on `origin/main`) — F8
* `src/aigateway/core/discovery_runtime.py` (295) — docstring described the REJECTED deployment discovery credential

Tests (new, this pass):

* `tests/unit/core/test_private_cache_policy_pre_handler.py` — 18 tests, 296 lines (F1)
* `tests/unit/core/test_listing_wait_budget.py` — 6 tests, 283 lines (F2)
* `tests/unit/core/test_credential_generation_ownership_fence.py` — 8 tests, 396 lines (F3)
* `tests/unit/core/test_private_parameter_generation_fence.py` — 6 tests, 262 lines (F4)
* `tests/unit/core/test_background_error_overflow.py` — 10 tests, 209 lines (F6)
* `tests/unit/core/test_public_prewarm_lifespan.py` — 3 tests, 184 lines (F6)
* `tests/unit/core/test_profile_catalog_row_bound.py` — 4 tests, 227 lines (F7)

Tests (modified):

* `tests/conftest.py` — F6 (pre-existing owner waiver, granted 2026-08-28, still the only waived file)
* `tests/unit/core/test_profile_snapshot_memory_bound.py` — F7 re-pin. **This file does not exist on
  `origin/main`** (it was written earlier in this same unit), so it is not an append-only offence; the
  contract change is owner-settled decision 4 and is annotated as such in the file.
* `tests/unit/core/test_background_failure_semantics.py` — repointed 4 call sites from the removed
  `main._start_public_prewarm` to `discovery_lifecycle.start_public_prewarm` (F8 mechanical follow-on;
  same file, written earlier in this unit).
* `tests/unit/test_profile_index.py`, `tests/unit/core/test_models_route_live_catalog.py` — the two
  owner-approved re-pins (D-R2).

Docs:

* `apps/aigateway/DEPLOYMENT.md`, `apps/aigateway/docs/anthropic-model-discovery.md`
* `docs/work/2026-08-27-OME-1026-live-anthropic-model-discovery.md` (this file)
* `docs/tasks/2026-08-27-OME-1026-live-anthropic-model-discovery.md`

#### 2. Commands actually run, with output

| Command | Output |
|---|---|
| focused RED runs, per fix, before the code existed | each new file failed on the asserted invariant, not on setup (F2 falsified by un-clamping both sites → exactly 3 failures; F7 falsified by restoring the carve-out → 6 failures) |
| `uv run pytest -q -p no:randomly` over the 10 OME-1026 suites | `83 passed, 2 warnings in 6.09s` |
| `uv run pytest -q -m "not live"` | `4384 passed, 18 skipped, 37 deselected, 48 warnings in 135.80s` |
| `uv run ruff check .` | `All checks passed!` (plus the harmless `PLR1702` preview notice) |
| `uv run ruff format --check .` | `558 files already formatted` |
| `uv run pyright` | `0 errors, 0 warnings, 0 informations` |
| `uv run python scripts/check_no_enterprise.py` | `OK: no LiteLLM Enterprise imports found` (exit 0) |
| `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` | `ALL GATES GREEN` — ruff, format, pyright, enterprise check, `pytest --cov=aigateway --cov-fail-under=80` |
| `uv run pytest --cov=aigateway --cov-fail-under=80 -q` (coverage figure) | `TOTAL 12329 890 93%` → `Total coverage: 92.78%`; `4384 passed, 55 skipped in 198.29s` |
| `append_only_check(apps/aigateway, "origin/main", ["tests/**"])` | RED on exactly 3 files — see item 4 |
| `git diff --check` / `git diff --check --cached` | both exit 0, no whitespace errors |
| `git diff --name-status --cached` | one entry: `R100 …test_models_route_live_catalog_anthropic.py → …test_models_route_anthropic_scope_boundary.py` (pre-existing) |
| `tests/unit/auth/test_login.py::test_unknown_user_timing_close_to_wrong_password` | passed in the full suite **and** `1 passed in 13.35s` in isolation — no flake this pass, and the test was NOT modified |

#### 3. Final full-suite counts

`4384 passed, 18 skipped, 37 deselected` (`-m "not live"`, 135.80 s). The 37 deselected are the
`live` marker (no live provider probe was run or authorized). The coverage run (which does not apply
the marker, so those 37 are skipped rather than deselected) reports `4384 passed, 55 skipped` and
**92.78 %** total coverage against the `--cov-fail-under=80` gate.

#### 4. Append-only result and attribution

`append_only_check` against `origin/main` is RED on exactly three files, each accounted for:

1. `tests/conftest.py` — the **pre-existing owner waiver granted 2026-08-28**, unchanged in kind.
   This pass extended the same fixture file for F6 (autouse assertion + the two discovery levers +
   the drain barrier), which is precisely what owner decisions 1 and 2 direct.
2. `tests/unit/test_profile_index.py::test_profile_index_serializes_with_version` — **owner-approved
   re-pin 1** (D-R2). `credential_generations` is durable index state, so the exact-dict assertion
   gains `"credential_generations": {}`, with a comment recording the identical `oauth_generations`
   precedent and why the two maps stay separate.
3. `tests/unit/core/test_models_route_live_catalog.py::test_concurrent_callers_share_one_upstream_fetch_chain_and_all_get_200`
   — **owner-approved re-pin 2** (D-R2), re-pinned as the owner required: it proves six 200s
   (`statuses == [200] * 6`), exactly one upstream fetch (`http.dialed == [LIVE_MODELS_URL]`), six
   `start_or_join` calls for the openrouter key, all six handed the **same task object**, one
   identity, and six callers parked on it simultaneously (`waiters["peak"] == 6`).

No other prior test was modified. `tests/unit/core/test_profile_snapshot_memory_bound.py` and
`tests/unit/core/test_background_failure_semantics.py` were changed but do **not** exist on
`origin/main`, so they are additions from this unit, not prior tests.

#### 5. Final line counts for every modified source file near the 450-line limit

| File | `origin/main` | Now | Verdict |
|---|---|---|---|
| `src/aigateway/routes/auth.py` | 1424 | **1509** | over — pre-existing violation, see deviations |
| `src/aigateway/plugins/openrouter_provider/plugin.py` | 558 | **572** | over — pre-existing violation, see deviations |
| `src/aigateway/plugins/anthropic_provider/plugin.py` | 320 | **420** | under |
| `src/aigateway/core/profile_model_catalog.py` | new | **409** | under |
| `src/aigateway/main.py` | 423 | **407** | under (F8 target, was 496 mid-pass) |
| `src/aigateway/core/profile_index.py` | 326 | **391** | under |
| `src/aigateway/plugins/anthropic_provider/live_models.py` | new | **358** | under |
| `src/aigateway/core/profile_snapshot_store.py` | new | **354** | under |
| `src/aigateway/core/background_refresh.py` | new | **352** | under |
| `src/aigateway/core/parameter_discovery.py` | 243 | **336** | under |
| `src/aigateway/core/model_catalog.py` | 218 | **335** | under |
| `src/aigateway/routes/model_parameters.py` | 219 | **334** | under |
| `src/aigateway/config.py` | 309 | **326** | under |
| `src/aigateway/core/plugin_base/_contract.py` | 362 | **307** | under (F8 target, was 475 mid-pass) |
| `src/aigateway/core/discovery_runtime.py` | 281 | **295** | under |
| `src/aigateway/core/plugin_base/model_discovery.py` | new | **218** | under |
| `src/aigateway/routes/profile_models.py` | new | **154** | under |
| `src/aigateway/discovery_lifecycle.py` | new | **145** | under |
| `src/aigateway/routes/models.py` | 62 | **127** | under |
| `src/aigateway/core/model_discovery_scope.py` | new | **117** | under |
| `src/aigateway/routes/private_cache.py` | new | **95** | under |
| `src/aigateway/core/discovery_budget.py` | new | **37** | under |

#### 6-10. The ten confirmations the prompt requires

6. **Pre-handler auth failures carry the private cache policy.** Confirmed by **14** deterministic
   pre-handler cases (7 refusals x 2 routes) across both auth modes (`jwt`: missing / malformed / expired
   bearer, valid-token-no-account; `cloudflare_headers`: untrusted peer 403, missing `X-User-Email`,
   deactivated identity), each asserting `Cache-Control: private, no-store` and the mode-appropriate
   `Vary` tokens. The mechanism is a route class wrapping dependency resolution, so exits nobody has
   written yet are covered too — pinned structurally by
   `test_the_policy_is_installed_where_it_wraps_dependency_resolution`.
7. **A provider timeout above 3 s cannot raise the user-facing wait above 3 s.** `user_wait_budget`
   returns `min(configured, 3.0)`, applied at both listing sites. Tested with
   `AIGW_DISCOVERY_TIMEOUT_SECONDS=10`: both budgets are 3.0, a 1.5 s configuration stays 1.5,
   and the refresh the expiring waiter left behind stays alive and publishes on a later request
   (the budget bounds the wait, never the work).
8. **Background error overflow cannot pass green.** `take_unexpected()` reports dropped as well as
   retained errors and `assert_no_unexpected` fails on a nonzero dropped count; the autouse
   `_background_discovery_errors` fixture applies it to all 4384 tests, resetting on entry so a leak
   is attributed to the test that produced it. `test_background_error_overflow.py` drives the sink
   past capacity and asserts the failure.
9. **Retained rows never exceed the configured maximum.** `store()` refuses an oversized snapshot
   outright and `_trim` has no carve-out. Asserted at the store's own API (11 tests) and end-to-end
   through the real route (4 tests) — including `retained_rows == 0` for a 20-row catalog against a
   6-row budget, and `retained_rows <= max_rows` after each of five profiles.
10. **One request cannot mix private model generations.** The rescue path captures the generation it
    admitted the id under and re-reads the durable index after resolution; any change — or a deleted
    profile — is a 409 `credential_generation_changed`, never a 200. Proved with a barrier injected
    at the exact seam, not a sleep.

#### Deviations (this pass)

* **F3 shipped a flag, not a new method.** The prompt's preferred contract was an ownership fence;
  the plan sketched a new `publish_credential` method. What shipped is
  `upsert(..., credential_owner_unchanged=False)` plus `_invalidate_profile_session(...,
  retire_private_catalog=True)`. Both defaults are the correctness-safe side (bump; drop the
  catalog), because the two mistakes are not symmetric: a spurious bump costs one refetch, a missing
  bump could serve one owner's catalog under another's credential. This touches one call site instead
  of every publication path — trimming, not new policy.
* **`routes/auth.py` (1509) and `plugins/openrouter_provider/plugin.py` (572) remain over the
  450-line guideline.** Both were **already non-compliant on `origin/main`** (1424 and 558). The
  guideline forbids growing an oversized file with a new *independent responsibility*; the F3 change
  to `auth.py` is two parameters on an existing private helper and its one caller, not a new
  responsibility. Splitting `auth.py` is a separate unit with its own blast radius (it owns every
  OAuth and api-key route) and is not in scope for a remediation pass that must not broaden.
* **No chat-transport no-egress guard was added (D-R4 stays open as a proposal).** The prompt
  explicitly says to propose it separately and not to broaden OME-1026 into a chat-transport
  refactor. The discovery tripwire remains the only egress guard; the one accidental request from the
  earlier pass is recorded at D-R4.
* **No live provider probe was run** (owner decision 8). The 37 `live`-marked tests stay deselected.
* **Nothing was committed, pushed, or staged.** The only staged entry is the pre-existing rename.


## Adversarial remediation pass (2026-08-31) — DONE

Source: `.agent-team-AIGW/live-anthropic-model-discovery/profile_scoped_rework_adversarial_fix_prompt.md`,
authoritative and superseding the closure report above where they conflict. The previous pass is
**not accepted as merge-ready**: its suite is green, but independent adversarial probes reproduced
schedules that its tests do not cover. Owner decisions 1-9 in that prompt are SETTLED. The verified
baseline it preserves: F2 closed, the F6 fixture shape and app-task drain correct, F7's ordinary
hard-row enforcement and damping correct, `main.py`/`_contract.py` under 450.

### The six reproduced defects and the planned fix

| # | Reproduced defect | Planned fix |
|---|---|---|
| B1 (F1) | `PrivateCacheRoute` catches only `HTTPException`, so a `RequestValidationError` 422 and an unexpected 500 are headerless; and `headers.update()` REPLACES an existing `Vary` (probes lost `Vary: Cookie` / `Accept-Encoding`) | mark the request scope from the route class, honour that marker in the app's EXISTING `RequestValidationError` handler and in a new generic-500 handler (Starlette renders 500 outside user middleware, so the app's error boundary is the only layer that observes it); merge `Vary` tokens case-insensitively instead of overwriting |
| B2 (F3/F4) | removing the routine-refresh bump did not remove the two-write race: provider refresh persists credential bytes BEFORE the profile-index publication, so a stale refresh A overwrites replacement B's blob and restores A's owner metadata while the durable generation stays B's | prepare-then-publish enforced at the STORAGE CAS: (a) re-read the durable generation before the refresh, (b) run the provider refresh against an ownership-guarded credential store whose write is a CAS against the exact bytes read before the network call, (c) publish the profile with `expected_credential_generation`, checked inside the index CAS. Cross-worker safe; no in-process lock |
| B3 (F6) | the sink retains original `BaseException` objects (a probe found an `x-api-key` in a retained frame local) and its globals are unsynchronized across the app loop and test threads (33 retained against a cap of 32; two drops counted once) | retain only a frozen sanitized record (safe key string, exception type name, identity token); one `threading.Lock` around every read-modify-write; `mark_observed` keeps its semantics without retaining the exception |
| B4 (F5) | `aclose()` clears `_tasks`/`_superseded` unconditionally, so a cancellation-resistant task is still running while `inflight == 0` and the tracked set is empty | drop only finished tasks; keep every still-alive task strongly referenced and counted until its done-callback runs |
| B5 (F7) | `settled_answer()` treats any retained entries as written by the completed attempt, so after an oversized refusal an EXPIRED snapshot is served as `fresh` with no reason | classify by the authoritative TTL arithmetic the ordinary read uses: accepted store -> fresh, refused within the stale window -> `stale` + reason, beyond it -> seeds + reason |
| B6 (F8) | `routes/auth.py` (1509) and `plugins/openrouter_provider/plugin.py` (572) were declared deviations instead of being split; auth.py now also owns independent model-discovery orchestration | extract the OME-1026 profile-discovery lifecycle out of `auth.py`, then split `auth.py` and the OpenRouter plugin along existing cohesive responsibilities until every hand-maintained file is <= 450 lines. No compatibility shims for unmerged internals |

### Test plan (RED first, in this order)

B3+B4 (the sink is suite-wide, so it moves first), B5, B1, B2, B6. Deterministic barriers, injected
clocks, canned transports, and the REAL production stores for B2. No live probe, no sleep-based
synchronisation. Each RED failure is recorded verbatim in the Outcome below before the fix lands.

### Acceptance

Every command in the prompt's Required Verification section; append-only RED on no more than the
three approved files; the F1-F8 table with root cause / source change / observed RED / GREEN result /
residual risk / status; and direct evidence for all ten adversarial schedules.

### Observed RED, per blocker (recorded before each fix landed)

**B3 — the sink retained live exceptions and raced.** `tests/unit/core/test_background_sink_hardening.py`:

* `assert not True` — the retained object *was* the original `BaseException`.
* the reachability probe found `sk-ant-frame-local-must-not-be-retained` through
  `record[1].__traceback__.tb_frame.f_locals`, plus the upstream text in the assertion message.
* `assert 35 <= 32` — cap breached, via a `list` subclass whose `__len__` parks on a
  `threading.Barrier` (volume alone does NOT reproduce it: 3 200 unsynchronized appends stayed
  green, because the GIL happens to serialize the check-then-append often enough).
* `assert 1 == 4` — one recorded increment for four dropped errors, via an `int` subclass whose
  `__add__` parks on a barrier; all four threads LOAD the same base before blocking.
* `(169, 1, 200)` on the first run of the drain seam — 30 of 200 errors lost between the two
  reads of a non-atomic drain.

**B4 — bounded close pretended the work died.** `test_shutdown_is_bounded_even_against_cancellation_resistant_work`:
`assert 0 == 1` for `mgr.inflight` while the cancellation-resistant task was demonstrably not
`done()`, with the tracked set empty.

**B1 — the error boundary was blind to 422 and 500.**
`tests/unit/core/test_private_cache_policy_error_boundary.py`:

* `assert None == 'private, no-store'` on a missing-required-parameter **422** for
  `/v1/model-parameters` in both identity modes — the 422 is rendered by the APPLICATION's
  `RequestValidationError` handler, after the route class has already unwound, so it carried no
  directive at all.
* the injected **500** (monkeypatching `app.state.profile_index.get_with_credential_generation` to
  raise) came out of a second `TestClient` with `raise_server_exceptions=False` as a bare
  `500` with no `Cache-Control` and no `Vary`: Starlette renders it in `ServerErrorMiddleware`,
  outside every user middleware, writing with the ORIGINAL `send`.
* `assert 'Cookie' in ...` failed on a 2xx that had declared `Vary: Cookie` — the policy assigned
  the header, so a response that DID vary on Cookie came out declaring that it does not. Same for
  `Vary: Accept-Encoding` + `Retry-After` on an `HTTPException`.

**B2 — a stale refresh could win in the credential store.**
`tests/unit/test_profile_refresh_ownership_fence.py`, all six steps of the reported schedule
reproduced with the REAL `ORMStore`/`ProfileIndexStore` and a `threading.Event` barrier inside an
`httpx.MockTransport` token handler (no sleep, no fake index):

* `assert 200 == 409` — refresh A, parked in the provider call under generation *N*, published
  successfully after replacement B committed at *N+1*.
* `assert 'oauth-A-refreshed-must-not-persist' not in ...` — A's token had overwritten B's
  credential blob.
* `assert 'api_key' == 'oauth'` — A's presence-only `upsert` restored the previous owner's auth
  type and metadata while the durable generation still read *N+1*.

**B5 — an expired snapshot came back `fresh`.** `tests/unit/core/test_profile_snapshot_settled_classification.py`:

* through the REAL route, after the snapshot aged past `ttl + stale_ttl` and the oversized
  replacement was refused —
  `AssertionError: {'object': 'list', ..., 'status': 'fresh', ...}` / `assert 'fresh' == 'fallback'`.
  This is the independent probe's exact schedule.
* the six classifier cases: `TypeError: ProfileSnapshotStore.settled_answer() got an unexpected
  keyword argument 'source'` — the function had no way to date the rows it was labelling.

### GREEN, per blocker

| Blocker | Command | Result |
|---|---|---|
| B3 + B4 | `uv run pytest -q tests/unit/core/test_background_sink_hardening.py` | 12 passed |
| B3 + B4 | `uv run pytest -q test_background_refresh_capacity.py test_background_refresh.py test_background_error_overflow.py test_background_sink_hardening.py` | 48 passed |
| B3 | `uv run pytest -q test_background_failure_semantics.py test_models_route_public_budget.py test_public_prewarm_lifespan.py` | 23 passed |
| B5 | `uv run pytest -q tests/unit/core/test_profile_snapshot_settled_classification.py` | 8 passed |
| B5 | the eight profile/private core suites (`test_profile_catalog_row_bound`, `test_profile_model_catalog`, `test_profile_snapshot_memory_bound`, `test_profile_models_route`, `test_profile_models_private_cache_policy`, `test_private_cache_policy_pre_handler`, `test_private_parameter_generation_fence`, `test_private_parameter_contract_url`) | 95 passed |

### Source changes so far

| File | Change |
|---|---|
| `src/aigateway/core/background_error_sink.py` (new, 228) | the sink, extracted from `background_refresh.py` (which had reached 463 lines). Retains a frozen `UnexpectedRecord(key, type_name, token)` — never the exception, its traceback, its frames, or `str(exc)`. One module-level `threading.Lock` guards every read-modify-write; `drain_unexpected()` resets records and the dropped count atomically; `mark_observed(exc)` still removes the matching record by `id(exc)` without retaining `exc`. |
| `src/aigateway/core/background_refresh.py` (463 -> 259) | sink removed; `pending_tasks()` made public (the honest "what am I still responsible for"); `aclose()` now calls `_release_finished()`, which drops only `done()` tasks and keeps every live one strongly referenced and counted. |
| `src/aigateway/core/profile_snapshot_store.py` | `settled_answer(key, *, source, reason)` classifies by the same TTL arithmetic `offline_answer` uses. Class docstring: the rejected one-oversized-snapshot carve-out text is gone, replaced by the hard-bound invariant plus the B5 invariant. |
| `src/aigateway/core/profile_model_catalog.py` | passes `source=source` into `settled_answer`. |
| 5 prior test files + `tests/conftest.py` | re-pointed at `background_error_sink` and at the sanitized-record contract (`record.type_name` instead of `isinstance`), under the owner-approved sink contract change. |
| `src/aigateway/routes/private_cache.py` (95 -> 213) | B1. `merge_vary` (order-preserving, case-insensitive union), `apply_private_cache_policy` (owns `Cache-Control`, MERGES `Vary`, collapses case variants), `PRIVATE_CACHE_SCOPE_KEY` + `stamp_private_cache_policy`. The route class marks the scope BEFORE dependency solving. |
| `src/aigateway/main.py` (438 -> 445) | B1. `app.add_exception_handler(Exception, _sanitized_server_error)` brings 500 rendering into application code, and all five error handlers stamp the policy when the scope was marked. |
| `src/aigateway/core/credential_ownership_fence.py` (new, 148) | B2. `ExpectedOwnership`, `CredentialOwnerChanged`, and `BufferedRefreshCredentialStore` — buffer the provider's write, publish it under a bytes-unchanged CAS inside the caller's transaction. |
| `src/aigateway/core/profile_index.py` (438 -> 445) | B2. `CredentialOwnershipConflict` + `expected_credential_generation` / `expected_auth_type` checked INSIDE the index mutator, beside the presence check. |
| `src/aigateway/routes/auth.py` (1509 -> 444) | B2 + B6. The refresh path captures ownership before the provider call and publishes both CASes in one transaction; the module is split by responsibility (below) down to the three coordinators the merged suite instruments. |
| `routes/auth_context.py` (47), `profile_credential_lifecycle.py` (237), `profile_routes.py` (228), `oauth_callbacks.py` (122), `oauth_loopback.py` (370), `oauth_profile_completion.py` (156), `oauth_connection_completion.py` (256) | B6. The seven modules `auth.py` split into, by responsibility. All 14 route declarations preserved byte-identically; `main.py` registers the two new routers adjacent to `auth.router`. |
| `plugins/openrouter_provider/plugin.py` (572 -> 427) | B6. `chat_completion` -> new `dispatch.py` (79); the parameter-observation composition and pair validation -> `parameters.py` (400); the discovery-identity predicate, source declaration and snapshot fetch -> `discovery.py` (381). `prepare_chat_body` deliberately STAYS (a merged test patches `build_provider_policy` in this module's namespace). |
| `src/aigateway/routes/admin.py` | B6. One import line: `delete_profile_for_account` now comes from `profile_routes`. |
| `apps/aigateway/docs/anthropic-model-discovery.md`, `apps/aigateway/DEPLOYMENT.md` | reason vocabulary synchronized: `fresh` is decided by age and never by retention; credential-generation change vs routine refresh; the `409 credential_owner_changed` refresh conflict and what it does NOT write. |

### Outcome — DONE (2026-08-31, adversarial pass)

All six blockers closed, each driven by tests that were RED against the pre-fix code (verbatim
failures above) and GREEN after. **`uv run pytest -q -m "not live"` -> 4480 passed, 18 skipped,
37 deselected** (was 4384 passed before this pass: +96 tests, no test removed).
**Coverage 92.88 %** (`--cov-fail-under=80`, 12 590 statements, 896 missed). `uv run ruff check .`,
`uv run ruff format --check .` (574 files), `uv run pyright` (0 errors),
`scripts/check_no_enterprise.py`, and `run_gates.py aigateway --skip-append-only` — **ALL GATES
GREEN**. `git diff --check` and `git diff --check --cached` clean.

**Closure status per blocker**

| Blocker | Status | Residual risk |
|---|---|---|
| B1 (F1) error-boundary policy + `Vary` merge | CLOSED | An intermediary that ignores `Cache-Control` is outside the gateway's reach. A future error handler added to `main.py` must stamp; the structural test pins that the `Exception` handler exists, not that a new handler stamps. |
| B2 (F3) two-write ownership race | CLOSED for the profile-refresh route | **The chat-dispatch token refresh is NOT fenced.** `get_authorization_header` on a cached strategy uses the plain store, so a token refresh raised by a dispatch can still overwrite a replacement's credential bytes. It publishes no profile metadata and cannot rewind the generation, so it cannot restore a previous OWNER — but the bytes are unprotected. Out of this pass's scope; needs its own work item. |
| B2 (F4) private-identity ownership change | CONFIRMED ALREADY HELD | The six confirmation tests passed on their FIRST run: the identity fence was never broken. F4 was blocked only because F3 could restore a previous owner AT the current generation, which B2 removes. Reported as a confirmation, not as a RED-first fix. |
| B3 (F6) sink retention + races | CLOSED | The barrier-parked subclasses prove the lock covers the read-modify-writes that exist today; a new counter added outside the lock would not be caught by these tests. |
| B4 (F5) close vs live tasks | CLOSED | A task that never finishes stays tracked forever by design — the manager reports it rather than forgetting it. Shutdown remains bounded. |
| B5 (F7) `settled_answer` freshness | CLOSED | Age is measured with the store's own clock; a caller passing a different `source` than the one the rows were fetched under would date them against the wrong TTL. Only one call site exists and it passes the resolved source. |
| B6 (F8) 450-line compliance | CLOSED | Two documented function-level imports break real cycles (`oauth_loopback` -> `auth`, `oauth_connection_completion` -> `auth`); both also preserve patchability. `routes/chat.py` (522), `routes/oauth_connections.py` (521), `plugins/taxonomy/types.py` (533) and `plugins/antigravity_provider/chat_handler.py` (610) remain over the limit and are NOT touched by this pass — `oauth_connections.py` was deliberately reverted to its `origin/main` content so that no file this pass modifies exceeds 450 lines. |

**Direct evidence for the ten adversarial schedules**

| # | Schedule | Evidence |
|---|---|---|
| 1 | 422 and unexpected 500 carry the private cache policy | `test_a_missing_required_query_parameter_is_422_with_the_policy`, `test_the_422_policy_holds_in_cloudflare_header_identity_mode`, `test_a_dependency_raised_validation_failure_carries_the_policy`, `test_an_unexpected_exception_is_a_sanitized_500_that_carries_the_policy`, `test_the_500_policy_holds_in_cloudflare_header_identity_mode`; a PUBLIC route's 500 must NOT gain it (`test_an_unexpected_exception_on_a_PUBLIC_route_gains_no_private_policy`) |
| 2 | existing `Vary` tokens survive | `test_an_existing_vary_token_survives_on_a_success`, `test_an_existing_vary_token_survives_on_an_httpexception`, `test_a_token_the_policy_also_names_is_not_listed_twice`, `test_a_422_on_a_route_whose_vary_is_extended_keeps_both`, `test_merge_vary_is_an_order_preserving_case_insensitive_union` (6 cases) |
| 3 | stale refresh A cannot overwrite replacement B's blob, profile, auth type, snapshot or generation | `test_a_stale_refresh_is_refused_deterministically`, `..._cannot_overwrite_the_replacement_credential`, `..._cannot_restore_the_previous_owner_metadata`, `..._cannot_rewind_the_ownership_generation`, `..._does_not_retire_the_replacement_private_listing`, `test_an_oauth_reauthentication_wins_against_a_stale_refresh`, `test_a_delete_wins_against_a_stale_refresh` |
| 4 | same-owner uncontended refresh succeeds without a generation bump | `test_an_uncontended_same_owner_refresh_still_succeeds`, `test_an_uncontended_refresh_does_not_bump_the_ownership_generation`, `test_an_uncontended_refresh_keeps_the_private_listing_warm` |
| 5 | F4 cannot accept an owner/auth change at the same generation | `tests/unit/core/test_private_identity_ownership_changes.py` (6): key replacement, OAuth re-authentication, api_key->oauth switch, delete/recreate, `profile_credential_revision` distinguishing `api_key@gen2` from `oauth@gen2`, and a store-level proof that a snapshot under one auth type is unreadable under the other |
| 6 | retained diagnostics carry no exception, traceback or credential | `test_a_retained_record_holds_no_exception_traceback_or_credential`, `test_a_retained_record_still_names_the_bug_class`, `test_the_failure_message_names_type_and_key_but_no_exception_text` |
| 7 | concurrent producers preserve the exact cap and the dropped count | `test_the_retention_cap_is_exact_under_concurrent_producers`, `test_the_dropped_count_is_lossless_under_concurrent_producers`, `test_the_observation_point_cannot_lose_an_error_to_a_concurrent_producer` |
| 8 | cancellation-resistant tasks stay tracked after a bounded close | `test_a_cancellation_resistant_task_stays_tracked_after_a_bounded_close`, `test_a_closed_manager_still_refuses_new_work`, `test_a_finished_task_is_dropped_promptly_by_a_bounded_close` |
| 9 | an expired snapshot cannot become fresh after an oversized refusal | `test_the_route_never_serves_expired_rows_as_fresh`, `test_a_refused_replacement_past_the_stale_window_is_never_served`, `test_a_refused_replacement_settles_as_stale_inside_the_stale_window`, `test_the_route_does_not_redial_while_the_refusal_is_damped` |
| 10 | every new/modified source file is at most 450 lines | `tests/unit/test_module_decomposition_contract.py` (42 tests) — a parametrized size assertion over all 21 source files this pass created or changed, plus route-set preservation, the auth-surface imports, and the two monkeypatch seams asserted through `__code__.co_names` (falsified: the delegating `chat_completion` reports `False` for a name only `prepare_chat_body` reads) |

**Append-only attribution** (`append_only_check(apps/aigateway, origin/main, ["tests/**"])`): RED on
exactly three files, all approved, no fourth —

* `tests/conftest.py` — the pre-existing owner waiver (granted 2026-08-28).
* `tests/unit/test_profile_index.py` — `test_profile_index_serializes_with_version`, approved re-pin.
* `tests/unit/core/test_models_route_live_catalog.py` —
  `test_concurrent_callers_share_one_upstream_fetch_chain_and_all_get_200`, approved re-pin. Per the
  owner's explicit instruction the peak-concurrency assertion was NOT replaced with an
  `inflight == 1` check: the test now proves all six callers were handed the SAME task object
  (`len({id}) == 1`), all six returned 200, exactly one upstream fetch occurred
  (`http.dialed == [LIVE_MODELS_URL]`), and `waiters["peak"] == 6`.

Every other changed test file is untracked — created earlier on this branch, absent from
`origin/main`, so not an append-only offence. Two of them were corrected in this pass to match the
owner-approved contract and are named here rather than buried: the five sink-contract call sites +
the B4 capacity re-pin (sanitized `record.type_name`), and
`tests/unit/core/test_credential_generation_ownership_fence.py`'s cancellation test, whose assertion
still expected the pre-fence split write (`== "rotated-tok-1"`, "the write landed") and now asserts
what the fence guarantees: the buffered token never became durable.

**Staging** — unchanged and reported separately: the index still contains exactly one entry, the
pre-existing `R100` rename
`tests/unit/core/test_models_route_live_catalog_anthropic.py -> tests/unit/core/test_models_route_anthropic_scope_boundary.py`.
This pass adds **no new staging**; nothing was committed, pushed, or published, and no PR was
created.

**No egress.** No live Anthropic/OpenRouter/OpenAI/Gemini call. Every new test uses
`httpx.MockTransport` or a canned catalog object, against the real `ORMStore`, `ProfileIndexStore`
and `ProfileSnapshotStore` on the suite's SQLite file.

## Independent-review remediation (2026-08-28) — DONE

Source: `.agent-team-AIGW/live-anthropic-model-discovery/profile_scoped_rework_review_findings.md`.
Verdict was **NOT MERGE-READY**: findings 1–6 pre-merge blockers, 7–8 fix-or-document. Baseline is
the uncommitted profile-scoped rework above. Every finding was re-verified against the code before
planning; **all eight reproduce**. TDD: a failing deterministic test first, then the root-cause fix.

### Verification of each finding against the code (done before any edit)

| # | Claim | Verified at | Verdict |
|---|---|---|---|
| 1 | private endpoint has no `Cache-Control`/`Vary` | `routes/profile_models.py` has neither; precedent `routes/model_parameters.py:73-76,209,218` | CONFIRMED |
| 2 | cold `/v1/models` can wait ~10 s | `routes/models.py:37,79-85` → `ObservationCache.get_or_refresh` awaits `refresh()` **holding the lock** (`parameter_discovery_cache.py:213`); OpenRouter `_AGGREGATE_TIMEOUT_S = 10.0` | CONFIRMED |
| 3 | timestamp is not a unique generation | `profile_snapshot_store.py:69-70` uses `last_refreshed_at`; `routes/auth.py:1353` assigns `datetime.now(UTC)`; `idx.upsert` bumps no generation | CONFIRMED |
| 4 | private rows advertise a 404 URL | `model_capabilities.py:78` always emits `parameter_contract_url`; `model_parameters.py:194-198` consults the PUBLIC catalog only | CONFIRMED |
| 5 | superseded tasks bypass capacity | `background_refresh.py:89` counts `_tasks` only; `:113` gates on `_tasks` only; `_superseded` unbounded; `aclose` gathers with no deadline (`:212`) | CONFIRMED |
| 6 | prewarm swallows bugs; post-commit 5xx | `main.py:177-184` `return_exceptions=True` + tuple count; `_terminal_reason` re-raises into `snapshot_for` even at `wait_budget_s=0.0` | CONFIRMED |
| 7 | identity bound is not a memory bound | `ProfileSnapshotStore._trim` counts identities; a snapshot may hold up to Anthropic's 2 000 rows | CONFIRMED |
| 8 | docs name a nonexistent reason | `invalid_payload` exists nowhere in `src/`; real reasons include `malformed_json`, `bad_content_type`, `oversized`, `model_catalog_too_large`, `origin_not_allowed`, `unsupported_encoding`, `insecure_scheme`; the normal stale path passes `reason=None` | CONFIRMED |

### Planned fixes

1. **F1** — `_PRIVATE_CACHE_HEADERS` on the profile endpoint, applied to the normal return *and*
   merged into `HTTPException.headers` (the only channel that reaches an error response). `Vary`
   must name the identity input of **every** auth mode: bearer uses `Authorization`,
   `cloudflare_headers` uses `X-User-Email` (`core/auth/cloudflare_identity.py:29`) — so the
   existing precedent's `Authorization, X-Profile` is itself incomplete and gains `X-User-Email`.
2. **F2** — route public catalog refreshes through an app-lifetime `BackgroundRefreshManager` keyed
   by provider, waited with the same 3 s budget; on expiry the route answers seeds and the refresh
   keeps running. Startup prewarm uses the **same per-provider keys**, so a request arriving during
   prewarm JOINS that task and waits its own budget instead of the provider's 10 s deadline.
3. **F3** — new `ProfileIndex.credential_generations` sibling map (like `oauth_generations`: never
   surfaced through `Profile.model_dump`), bumped **inside the atomic index CAS** on every
   credential publication, so it is durable, strictly monotonic per profile, and collision-free
   across workers. Private revision becomes `auth_type@gen<N>`; one combined read
   (`get_with_credential_generation`) keeps the credential decryption count unchanged.
4. **F4** — `/v1/model-parameters` consults the caller's own private snapshot for its own
   selected profile. **Changed during implementation** from the planned read-only
   `cached_ids_for` to the same `snapshot_for` the listing route uses: a cached-only lookup
   would make the advertised URL work on the replica that served the listing and 404 on its
   siblings, because a private snapshot is deliberately process-local. Reusing `snapshot_for`
   adds no capability (same caller, same stored credential, same refusal gates, same
   single-flight and capacity bounds) and keeps one implementation of all of them.
5. **F5** — capacity and `inflight` count **every live task** including superseded ones; bounded
   `aclose`.
6. **F6** — a module-level unexpected-error sink retains background bugs until an explicit
   observation point; `wait_budget_s=0` becomes *start-only* so publication can never return a
   timing-dependent 5xx after commit. **Changed during implementation**: prewarm does not
   re-raise, because it no longer awaits at all — it starts one manager-owned task per provider
   and returns, which is what makes "startup never waits on an upstream catalog" structural and
   what lets a request during prewarm JOIN the task (F2). The manager's own `_reap` is the
   retention point, which is strictly louder than a re-raise into a task nobody awaits. The
   teardown assertion is an **explicit hook**, not autouse — see Deviations below.
7. **F7** — row-aware total bound on the snapshot store.
8. **F8** — correct the reason vocabulary and stale semantics; add the four missing tests.

### Acceptance

Focused regression test per finding; all profile-model, model-catalog, auth-lifecycle,
model-parameter and background-refresh suites; `run_gates.py aigateway --skip-append-only`;
`pytest -m "not live"`; `git diff --check`; append-only checked against `origin/main` with the
pre-existing `tests/conftest.py` waiver reported separately.

### Outcome — remediation

All eight findings closed. Every fix was driven by a failing deterministic test written first, and
no prior assertion was weakened. Two deviations from the plan are recorded above (F4, F6) and two
open owner decisions are listed at the end of this section.

| # | Root cause | Code changed | Failing test written first | Result |
|---|---|---|---|---|
| 1 | the private listing route set no HTTP cache policy at all, and in `cloudflare_headers` mode two accounts issue byte-identical request lines for one URL | `routes/profile_models.py` (`_PRIVATE_CACHE_HEADERS`, handler split into a policy boundary + `_listing`); `routes/model_parameters.py` `Vary` gains `X-User-Email` | `test_profile_models_private_cache_policy.py` (5) | CLOSED |
| 2 | the route awaited each public provider's refresh with no budget of its own, so OpenRouter's 10 s aggregate deadline became the route's latency | `core/model_catalog.py` (`start_public_refresh`, `entries_within`, `PublicRefreshKey`); `routes/models.py`; `main.py` (`_start_public_prewarm`, `app.state.public_refreshes`) | `test_models_route_public_budget.py` (9) | CLOSED |
| 3 | the cache identity embedded `last_refreshed_at`, a wall clock assigned at publication — two replacements inside one tick produced EQUAL identities | `core/profile_models.py` (`ProfileIndex.credential_generations`); `core/profile_index.py` (`_bump_credential_generation` inside both mutators, `get_with_credential_generation`); `core/profile_snapshot_store.py`; `core/profile_model_catalog.py`; `routes/profile_models.py`; `routes/auth.py` | `test_credential_generation_identity.py` (8) | CLOSED |
| 4 | `model_row` always advertises `parameter_contract_url`, but `/v1/model-parameters` resolved seeds + admitted + PUBLIC catalog only — and the public catalog refuses Anthropic's private scope by design | `routes/model_parameters.py` (`_private_catalog_ids`); `core/model_capabilities.py` (`canonical_ids`); `core/model_discovery_scope.py` (`discovery_scope_of`, moved from `model_catalog`) | `test_private_parameter_contract_url.py` (6) | CLOSED |
| 5 | `inflight` and the capacity gate counted `_tasks` only, so a cancellation-resistant superseded task stopped being counted while still running; `aclose` gathered with no deadline | `core/background_refresh.py` (`inflight` counts every not-done live task; `shutdown_timeout_s`; bounded `aclose`) | `test_background_refresh_capacity.py` (8) | CLOSED |
| 6 | prewarm's `gather(return_exceptions=True)` + tuple count laundered every unexpected exception; `wait_budget_s=0.0` still gave the task its first step, so a fast programming failure was re-raised after the credential had committed | `core/background_refresh.py` (`mark_observed`, `take_unexpected`, `assert_no_unexpected`, retention sink); `core/profile_model_catalog.py` (start-only zero budget); `main.py` (start-only prewarm); `tests/conftest.py` (per-test drain + shared `drain_private_catalog` barrier) | `test_background_failure_semantics.py` (11) | CLOSED |
| 7 | the store bounded identities while an identity's contents are unbounded from core's view: 512 identities x Anthropic's 2 000-model cap is over a million retained rows per worker | `core/profile_snapshot_store.py` (`max_rows`, `retained_rows`, row-aware `_trim`); `core/profile_model_catalog.py`; `config.py` (`AIGW_DISCOVERY_PROFILE_CACHE_MAX_ROWS`) | `test_profile_snapshot_memory_bound.py` (9) | CLOSED |
| 8 | docs named a reason that exists nowhere in `src/` and claimed stale always carries a reason; three acceptance claims were asserted indirectly | `docs/anthropic-model-discovery.md` (full reason table, stale semantics); `DEPLOYMENT.md` (F2 budget, F7 row bound) | `test_discovery_acceptance_gaps.py` (4) | CLOSED |

### Final API and cache contract

* `GET /v1/models` — unchanged body. Each PUBLIC provider is now waited for at most
  `AIGW_DISCOVERY_TIMEOUT_SECONDS` (default 3.0, read off `runtime.limits.timeout_s` — the same
  object the discovery client uses, so there is one knob). On expiry that provider contributes its
  compiled seeds and its refresh continues. Providers still refresh concurrently; row order is
  positional over `registry.all()`. Public refresh identity is the tuple
  `(provider, source.key, source.revision)` in the app-lifetime `app.state.public_refreshes`,
  capacity = the provider count.
* `GET /v1/auth/{provider}/profiles/{name}/models` — unchanged body; every response (200, 404,
  kill-switch fallback) now carries `Cache-Control: private, no-store` and
  `Vary: Authorization, X-User-Email`.
* `GET /v1/model-parameters` — unchanged body; `Vary` gains `X-User-Email`. A model id that exists
  only in the caller's own private snapshot for the `X-Profile` it names now resolves (200) instead
  of 404. Cross-account and sibling-profile requests for the same id still return
  `model_not_found`.
* Private cache identity — `(account_id, provider, profile_name, "{auth_type}@gen{N}")` where `N`
  is `ProfileIndex.credential_generations[profile_id]`, bumped inside the atomic index CAS on every
  credential publication. Durable, strictly advancing, never cleared on delete, never surfaced by
  `Profile.model_dump`.
* Private cache bounds — `AIGW_DISCOVERY_CACHE_MAX_ENTRIES` identities (512) **and**
  `AIGW_DISCOVERY_PROFILE_CACHE_MAX_ROWS` total rows (16 384), whichever binds first.
  **SUPERSEDED 2026-08-31 (owner decisions 4 and 5):** the carve-out described here — a single
  snapshot larger than the whole row budget is still cached and reclaimed as LRU on the next
  store — is GONE. Retained rows never exceed the maximum; an oversized snapshot is refused with
  `reason=cache_row_budget_exceeded`. The byte-memory figure this bullet used to carry was an
  unmeasured estimate and is removed: the bound is a row count, not a byte bound. See F7 in the
  final remediation pass.

### Commands actually run

* `uv run pytest` per finding while iterating (each new file RED first, then GREEN).
* `uv run pytest -q -m "not live" -p no:randomly` — full suite.
* `uv run ruff check .` / `uv run ruff format --check .` / `uv run pyright` — all clean.
* `uv run .claude/scripts/run_gates.py aigateway --skip-append-only`.
* `git diff --check` — clean.
* Append-only check against `origin/main`.

### Explicit confirmations requested by the review

1. **Private HTTP responses cannot be shared across accounts.** Every exit of the private listing
   route carries `private, no-store` plus a `Vary` naming both identity inputs
   (`Authorization` for bearer mode, `X-User-Email` for `cloudflare_headers`), applied on the
   normal return AND merged into `HTTPException.headers`, which is the only channel that reaches an
   error response. Proven by `test_profile_models_private_cache_policy.py`, including the
   two-accounts-one-URL header-mode case.
2. **An old credential generation cannot serve a snapshot after replacement, including across
   workers.** The generation is part of the cache key and is bumped inside the index CAS, so worker
   A recomputes a NEW key from the committed index without needing worker B's invalidation.
   `test_another_worker_cannot_serve_the_previous_generation` asserts exactly that with a second
   catalog instance and no cross-worker invalidation;
   `test_replacement_within_one_clock_tick_retires_the_old_snapshot` pins the frozen-clock case;
   `test_a_deleted_profile_does_not_reset_its_generation` pins that recreating a name cannot rewind
   into a cached identity.
3. **Global `/v1/models` returns within the approved budget while the public refresh continues.**
   `test_a_slow_public_provider_yields_seeds_within_the_budget` returns seeds against a refresh
   parked on an event and asserts the task is still alive and joinable;
   `test_a_later_request_sees_the_completed_public_snapshot` and
   `test_the_route_answers_seeds_fast_then_the_live_catalog` (end to end, real route, real
   OpenRouter parser) assert the completed snapshot becomes visible with ONE upstream fetch.

### Final verification (2026-08-28)

Exact commands, from the repo root unless noted, with the results actually observed.

| Command | Result |
|---|---|
| `uv run ruff check` (in `apps/aigateway`) | `All checks passed!` |
| `uv run ruff format --check` | `547 files already formatted` |
| `uv run pyright` | `0 errors, 0 warnings, 0 informations` |
| `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` | ruff/format/pyright green; coverage **92.74 %** (`--cov-fail-under=80` reached); pytest **1 failed, 4326 passed, 55 skipped** — the one failure is the pre-existing timing test below |
| `uv run pytest -q -m "not live"` (in `apps/aigateway`) | **4327 passed, 18 skipped, 37 deselected**, 0 failed, 273 s |
| `git diff --check` and `git diff --check --cached` | clean |
| `append_only_check(root, "origin/main", test_globs)` | 3 offenders — see below |

Counts reconcile: the gate run selects the 37 `live`-marked tests (which then skip: 18 + 37 = 55)
while `-m "not live"` deselects them; 4326 passed + 1 failed = 4327.

**Append-only check against `origin/main` (`7e29bc67`).** `origin/main` is the base the review
specifies and the correct one — sdlc rule 5 protects the contract being merged *into*, and against
`HEAD` the check also flags four files this branch itself introduced two commits earlier. Three
offenders vs `origin/main`:

| File | Attribution |
|---|---|
| `tests/conftest.py` | **pre-existing waiver, not this pass.** `git diff origin/main HEAD` = +16/−3; `git diff HEAD` = **+49/−0**. All three removed lines belong to commit `056971a4`; the `drain_private_catalog` helper and `_drain_background_discovery_errors` fixture are purely additive. |
| `tests/unit/core/test_models_route_live_catalog.py` | owner-approved re-pin, D-R2 |
| `tests/unit/test_profile_index.py` | owner-approved re-pin, D-R2 |

The staged rename does **not** appear against `origin/main`:
`test_models_route_live_catalog_anthropic.py -> test_models_route_anthropic_scope_boundary.py` is a
rename of a branch-added file, so it reads as an addition rather than a prior-test deletion. It was
left exactly as found, per the review's instruction.

### Deviations and open owner decisions

* **D-R1 — CLOSED 2026-08-31 by owner decision 1 (the assertion is now suite-wide autouse).**
  Recorded as it stood when it was open, because the measurement below is the evidence that
  made the owner's chosen resolution necessary: an autouse teardown `assert_no_unexpected` was implemented, run, and measured: it
  fails **236 pre-existing tests**. Cause, verified: publishing an api key starts a post-commit
  private refresh, the Anthropic plugin's `live_models` default is `True`, and those tests install
  no discovery transport — so the suite's no-egress tripwire fires in the background. Nothing
  reaches the network (the tripwire raises before the socket opens). Both ways to make it
  suite-wide break a prior test: making the default wiring inert breaks
  `test_the_no_egress_tripwire_stays_loud_through_the_whole_stack`, and defaulting
  `AIGW_ANTHROPIC_LIVE_MODELS=false` breaks the profile-discovery tests that rely on the `True`
  default (itself pinned by `tests/unit/anthropic/test_settings.py`). Shipped instead: a per-test
  **drain** in `conftest.py` (isolation, no assertion) plus the explicit hook, asserted by the
  discovery suites — including a new end-to-end test that publishes a credential and proves the
  tripwire IS reported on that exact post-commit path. Making it suite-wide is a Confidence-Gate
  decision about those prior tests.
  **Resolution (F6, final pass):** the owner decided the assertion must be suite-wide and that
  tests which do not exercise Anthropic profile discovery must DISABLE it, with discovery tests
  opting in explicitly. Shipped exactly that — `_background_discovery_errors` (autouse, resets on
  the way in and asserts on the way out), `_anthropic_private_discovery_disabled` and
  `_public_catalog_prewarm_disabled` (autouse levers on this process's plugin instance and on
  `main.start_public_prewarm`, so no production default and no prior settings test changes), and
  the named opt-ins `anthropic_live_discovery` / `public_catalog_prewarm`. The 236 failures are
  gone because those tests no longer perform discovery they never asked for, not because the
  assertion was weakened. Overflow is loud: `take_unexpected()` reports dropped as well as
  retained errors, so a full sink cannot pass green.
* **D-R2 — two prior tests re-pinned to the new contract (owner-approved, 2026-08-28).** The
  owner explicitly approved re-pinning both, and required the concurrency test to prove joining
  rather than merely read a gauge.
  * `test_models_route_live_catalog.py::test_concurrent_callers_share_one_upstream_fetch_chain_and_all_get_200`
    monkeypatched `ModelCatalog.entries_for` and asserted `depth["peak"] == 6` — six callers
    simultaneously inside that method. After F2 exactly one caller enters `entries_for` and the
    other five join its task, so the probe moved to `BackgroundRefreshManager`. It now asserts:
    six 200s; exactly one upstream fetch; six `start_or_join` calls for the openrouter key; all
    six handed the **same task object** (`len({id(task)}) == 1`); one identity; and six callers
    parked on it at once (`waiters["peak"] == 6`). Strictly stronger than the old probe.
  * `test_profile_index.py::test_profile_index_serializes_with_version` pinned
    `model_dump()` to an exact dict. F3's `credential_generations` is durable index state by
    design, so the expected dict gains `"credential_generations": {}` — the identical precedent
    the test's own comment records for `oauth_generations`, with a comment explaining why the two
    maps stay separate.
* **D-R3 — CLOSED 2026-08-31 by owner decision 3: `AIGW_DISCOVERY_PROFILE_CACHE_MAX_ROWS = 16 384`
  is APPROVED for the MVP as a hard TOTAL row limit.** Justification, restated without any byte
  claim: 16 384 rows still holds eight maximum-size provider catalogs (Anthropic caps its own walk
  at 2 000) or several hundred ordinary ones, and it replaces an effective worst case of over a
  million retained rows per worker. This is a **row count**. The earlier per-row byte-memory
  derivation was never measured; every restatement of it has been removed from this ledger,
  `DEPLOYMENT.md`, `docs/anthropic-model-discovery.md`, and the code comments (owner decision 5),
  including the historical wording that quoted the figure while retracting it.
* **D-R4 — a real outbound request was made once, by accident, and is reported.** While writing the
  F8 dispatch test an unstubbed `POST /v1/chat/completions` for a discovered-only Anthropic id
  reached `api.anthropic.com` and was rejected `401` in 629 ms with a fabricated key. No real
  credential was used and nothing was stored. Cause: the suite's no-egress tripwire guards the
  DISCOVERY client only; the chat transport has no equivalent. The test now patches
  `litellm.acompletion` (the established seam) and the gap is recorded here as a suite-hardening
  candidate.
* **D-R5 — RESOLVED 2026-08-31 by F8: `main.py` is now 407 lines.** Recorded as it stood:
  `main.py` was 496 physical lines, over the 450-line guideline (423 at merge base; the
  rework crossed the line and this pass added ~+16). The natural extraction is
  `_start_public_prewarm`, but it reads `app.state` and belongs beside the lifespan that calls it;
  moving it into `core/` would put app-state access inside core, a worse trade than the line count.
  The core primitive it delegates to (`ModelCatalog.start_public_refresh`) already lives in core.
  **Resolution:** the extraction target was wrong, not impossible. The whole app-level discovery
  wiring — build, install, prewarm, shutdown — moved to `src/aigateway/discovery_lifecycle.py`
  (145 lines), which is an APP-layer module, not `core/`, so `app.state` access stays where it
  belongs. `main.py` 496 → **407**.
* **D-R6 — the gate run's single red test is a pre-existing wall-clock flake, not a regression.**
  `tests/unit/auth/test_login.py::test_unknown_user_timing_close_to_wrong_password` asserts
  `abs(missing - wrong) / wrong < 0.10` over two sequential medians of 20 real bcrypt(12) logins.
  Evidence it is unrelated to this change: it is not in the diff (`git diff HEAD --name-only`
  does not list it), it touches no discovery code, and it passed in the full no-coverage run
  (4327 passed). Isolated today it passed **4/4 with discovery enabled and 4/4 with
  `AIGW_DISCOVERY_ENABLED=0`** — the discovery code is not the discriminator. The observed failure
  ratio was `0.0282 / 0.2635 = 0.107`, i.e. 7 % past a 10 % tolerance. Coverage is not the
  discriminator either (it failed 3/3 *without* `--cov` and passed 2/3 *with* it). What is: the
  machine was at load average 63–80 from an unrelated workload (a VM plus several Node workers in
  another repo). A deliberate uniform 8-way CPU load actually made it **pass** 3/3 while slowing
  each run from ~15 s to ~26 s, because uniform load inflates both medians and so raises the
  denominator; the failure mode is *asymmetric* load arriving during one of the two batches, which
  the test cannot resist because it measures the two batches sequentially and never interleaves
  them. That is a real weakness in a prior test — reported, not fixed: changing it is an
  append-only decision for the owner, and it is outside this remediation's scope.
* **Not addressed (unchanged from the rework):** per-account fairness in the shared private cache —
  one busy tenant can still evict another's snapshot and occupy in-flight slots. Reported, not
  invented; it is a product decision (per-account quotas).

## Last-mile remediation pass (2026-08-31) — IN_PROGRESS

Source: `.agent-team-AIGW/live-anthropic-model-discovery/profile_scoped_rework_last_mile_prompt.md`,
authoritative and superseding every closure claim above where they conflict. Independent review
**confirmed** F1, F2, F5, F7, F8 and the manual `/refresh` ownership fence — those are preserved,
not reopened. Two implementation defects remain reproduced, and the independent full gates are red.

### Intent

Close the last two adversarial schedules and make the gates green on THIS worktree:

1. **Blocker 1 (F3 open / F4 blocked by it).** The manual `/refresh` route is fenced, but the
   **automatic** refresh is not: chat dispatch resolves a *cached* `BaseOAuthStrategy` whose
   provider hook writes refreshed credential bytes with a last-writer-wins `ORMStore.write`.
   Evicting `CredentialStrategyCache` after a reauthentication removes the map entry only — it
   cannot stop a strategy instance that is already mid-refresh. Reproduced schedule: owner A at
   generation 1, owner B reauthenticates and commits generation 2 with blob `owner-B-new`, the
   cached A strategy resumes and publishes `owner-A-refreshed`. The durable generation still says
   B, so **F4's generation check cannot detect it** — the metadata belongs to B and the bytes to A.
2. **Blocker 2 (F6 open).** `record_unexpected` reads the observed marker OUTSIDE the sink lock
   (`background_error_sink.py:215`) and appends INSIDE it (`:222`), while `mark_observed` sets the
   marker OUTSIDE the lock (`:104`). The marker and the record list encode ONE fact — "is this
   error still owed an observer?" — and only half of it is serialized, so
   `producer checks marker == False | observer sets marker, scans an empty list | producer appends`
   leaves a record behind after `mark_observed()` returned, failing teardown for an error the
   caller already observed.

### Planned changes

* `src/aigateway/core/background_error_sink.py` — move the marker check and the marker SET inside
  the existing `_sink_lock`, so the marker transition and the list mutation have one linearization
  point. The `logger.error` call stays outside the lock (nothing awaits or blocks while held).
  Retention shape, the exact 32 cap, the dropped counter, the atomic drain/reset and the
  cancelled-task behaviour are unchanged.
* `src/aigateway/core/credential_ownership_fence.py` — NEW `OwnershipFencedCredentialStore`: a
  credential-store decorator that binds the expected ownership on its first `read()` and turns
  every subsequent `write`/`delete` into a conditional publication (index-row ownership assertion
  first, then a byte-exact credential CAS). Reuses this module's existing CAS protocol; does not
  duplicate it.
* `src/aigateway/core/profile_index.py` — NEW `assert_ownership(...)`, the index-row half of that
  conditional publication, built from the existing `_require_expected_ownership` helper and the
  existing index-row CAS so the OME-307 index-before-credential order is preserved.
* `src/aigateway/routes/chat_credentials.py` — wrap the credential store with the fence in the
  **profile** branch of `_strategy_for_credential_target`, and map the refusal to a retryable
  `409 credential_owner_changed` that evicts the cached strategy and does NOT mark the profile
  errored. **WHY a distinct exception and not `AuthError`:** the existing `AuthError` arm calls
  `_mark_profile_error_fresh`, so reusing it would let a stale strategy mutate the NEW owner's
  profile metadata — exactly what the invariant forbids.
* `tests/unit/core/test_background_sink_observation_race.py` — NEW; the 5 required sink cases.
* `tests/unit/core/test_automatic_refresh_ownership_fence.py` — NEW; the 11 required fence cases
  against the real `ORMStore`/`ProfileIndexStore`/Tortoise transactions with `MockTransport`.
* `tests/unit/test_module_decomposition_contract.py` (new THIS pass, so not append-only-bound) —
  make the size claim precise: derive the touched set from `git diff --name-only` against
  `origin/main` instead of a hand-listed subset.
* Docs: drop the "last-refresh stamp" derivation claim for `credential_revision`
  (`apps/aigateway/docs/anthropic-model-discovery.md:138`); document the automatic cached refresh as
  ownership-fenced once it is; replace the superseded F5-F8 closure text in
  `docs/tasks/2026-08-27-OME-1026-live-anthropic-model-discovery.md` with the final disposition.

### Test plan (RED first)

Blocker 2 first (the sink assertion is suite-wide, so its false failures pollute every other run),
then Blocker 1, then the two red gates. Deterministic barriers only — no sleeps, no provider
network, production store implementations for the fence cases.

### Acceptance

Every command in the prompt's Required Verification section run on THIS worktree; append-only red on
at most the three approved files; the 10-item final report with exact RED and GREEN evidence; the
prompt's closure-state table. Merge readiness is not claimed until both remaining schedules are
green here.

### Outcome — PARTIALLY SUPERSEDED MID-PASS

Status: **DONE for the in-scope half; the out-of-scope half was reverted by owner ruling.**

**Scope correction (owner, 2026-08-31 19:23-19:26).** While this pass was in its verification
stage the owner marked the driving prompt **SUPERSEDED — DO NOT EXECUTE** and rewrote
`initial_task_description.md` + `implementation_plan.md` to state that the prompt "incorrectly
broadened OME-1026 into shared OAuth refresh behavior for Anthropic, Gemini, Codex, and
Antigravity". Chat dispatch and automatic OAuth token refresh are now listed under **Excluded
Scope**, and plan U10 says they are "explicitly outside OME-1026 and must be tracked separately".

Blocker 1's fix was therefore withdrawn from the worktree by the owner, not by this pass:
`OwnershipFencedCredentialStore`, `ProfileIndexStore.assert_ownership`, the
`chat_credentials.py` fence wiring and both of its new test modules are gone. Verified clean —
no dangling import, no orphaned `except` arm, no caller-less helper:

* `OwnershipFencedCredentialStore` — zero references in `src/` and `tests/`;
* `CredentialOwnerChanged` — exactly one consumer left, the **in-scope** manual path at
  `routes/profile_credential_lifecycle.py:207`;
* `assert_ownership` — no definition and no callers anywhere;
* `core/profile_index_ownership.py` (91 lines) — still justified: both members are called by
  `profile_index.py` itself, which is what keeps that file under the size limit.

The finding itself is preserved as a hand-off (with its reproduced schedule and the single-point
fix location) in the task ledger's "Hand-off: automatic OAuth refresh publication is unfenced"
section. **It needs its own Linear work item; this pass did not file one.**

**Delivered in scope:**

* `core/background_error_sink.py` (254) — B3/F6's last race closed. The observed marker is now
  read and written inside the same `_sink_lock` section that appends or removes the sanitized
  record, giving one linearization point instead of two. `logger.error` stays outside the lock, so
  nothing awaits or blocks while it is held. Cap 32, exact dropped count, atomic drain/reset,
  cancelled-task behaviour and the suite-wide fixture unchanged.
  RED: reproduced 3/3 in fresh processes pre-fix (the retained record survived a returned
  `mark_observed()`). GREEN: 10/10 post-fix; 64 passed across every sink/background suite.
* `tests/unit/core/test_background_sink_observation_race.py` — the 5 required cases. Its
  `_SeamLock` parks one designated thread at its first `__enter__` *before* acquiring the real
  lock (parking while holding it would deadlock rather than interleave — documented in the file).
* `core/auth/passwords.py` (84) — real production timing asymmetry removed: the unknown-user path
  made two threadpool hops against the known-user path's one (~1 ms median, ~14 ms p95 on this
  machine — up to half the login test's 10 % budget, always in the direction that reveals which
  usernames exist). One hop on both paths now.
* `tests/unit/core/test_models_route_live_catalog.py` (owner-approved re-pin) — the six-caller
  concurrency test is now deterministic: `await asyncio.sleep(0.2)` became
  `await asyncio.wait_for(all_joined.wait(), 10)`, released once all six callers have executed
  `start_or_join`. All four contract assertions untouched: six 200s, one shared manager task, one
  upstream fetch chain, peak six waiters.
* `tests/unit/test_module_decomposition_contract.py` — the size claim is now precise: it rglobs
  the whole `src/aigateway` tree instead of a hand-listed subset, with the four pre-existing
  oversized files pinned so they may shrink but never grow.
* `core/profile_snapshot_store.py` (380) + `docs/anthropic-model-discovery.md` — dropped the false
  claim that `credential_revision` derives from a last-refresh timestamp; it is the durable
  ownership generation the profile index bumps inside its publication CAS.
* `routes/chat_profile_defaults.py` (211) / `routes/chat_credentials.py` (368) — the
  `_apply_defaults` cluster moved to the module that already owns profile-default policy;
  `chat_credentials` re-exports the name for `routes.chat` and the one pinned test.

**Gates on this worktree:** `ruff check`, `ruff format --check`, `pyright` (0 errors),
`check_no_enterprise.py`, `git diff --check` (both) all clean; `pytest -q -m "not live"` →
**4694 passed / 18 skipped / 37 deselected / 0 failed**; coverage **92.89%** (run 1 failed only on
the login timing test, run 2 passed); `run_gates.py aigateway --skip-append-only` → **ALL GATES
GREEN**; append-only red on exactly the three approved files. Focused suites: 64 sink/background,
59 fence/generation, 545 four-provider OAuth, 410 chat, 148 private cache/catalog, 239 auth,
1035 OpenRouter, 251 size contract.

**Deviations:** `test_unknown_user_timing_close_to_wrong_password` is a load-sensitive flake, not a
regression — 14 isolated runs after the fix gave 9 passed / 5 failed, the failures all on a loaded
machine; 1 of 2 full coverage runs failed on it. The production asymmetry behind it was real and is
fixed (see above); the residual variance is the test's own methodology, below this machine's noise
floor. No commit, push, staging or PR. No live provider probe. The out-of-scope automatic-refresh
fence finding needs its own Linear work item, which this pass did not file.

### BLOCKED: the session instruction and the authoritative contract now contradict each other

Recorded for the owner; needs a decision that cannot be made from inside the session.

The standing session instruction is "Continue OME-1026 using this authoritative last-mile prompt:
`.agent-team-AIGW/live-anthropic-model-discovery/profile_scoped_rework_last_mile_prompt.md` … Fix
the two remaining reproduced defects … exactly as specified."

That file's first line is now `# SUPERSEDED — DO NOT EXECUTE` (stamped 2026-08-31 19:23), and the
files it hands authority to (`initial_task_description.md`, `implementation_plan.md`, both rewritten
19:26) place the subject of its Blocker 1 — chat dispatch and automatic OAuth token refresh — under
**Excluded Scope**, with plan U10 adding that it "must be tracked separately". The Blocker 1 code
was removed from the worktree by the owner.

So the instruction is unsatisfiable as written: obeying it means re-adding code the owner deleted
and re-violating the contract that replaced it. Everything else it asked for is done and green
(Blocker 2 closed; both red gates resolved; all gates green — see the section above and the task
ledger's gate table). **Nothing is waiting on engineering work.** Resolving it needs one of:

1. lift or restate the session instruction to match the current contract (the state this pass
   leaves the worktree in), or
2. restore automatic OAuth refresh to OME-1026's scope, which contradicts the 19:26 rewrite, or
3. file the separate work item the contract calls for and let it carry the fence design — the
   reproduction schedule and the single-point fix location are preserved in the task ledger's
   "Hand-off: automatic OAuth refresh publication is unfenced" section.

Option 3 is the recommendation. No Linear issue was filed: creating one is an outward-facing action
and no human authorization for it was received in this session.

## Post-commit naming correction (2026-09-01)

### Intent

Apply the owner's explicit naming decision: the model-discovery contract module must be
`core/plugin_base/model_discovery.py`, without a leading underscore and without a compatibility
wrapper at the old path.

### Planned changes

- Rename `_model_discovery.py` to `model_discovery.py` and update the package facade and contract
  import.
- Append a module-layout contract proving the new import works and the old file does not exist.
- Do not change runtime behavior, OpenRouter, persistence, schema, or migrations.

### Test plan and acceptance

- RED: the layout contract fails while only `_model_discovery.py` exists.
- GREEN: the new module imports, the old path is absent, focused plugin/decomposition tests pass.
- Gates: Ruff, format, Pyright, enterprise guard, and the AIGateway gate runner.
- Acceptance: no compatibility shim, no behavior change, and no unrelated dirty file staged.

### Outcome

- Renamed `core/plugin_base/_model_discovery.py` to `core/plugin_base/model_discovery.py`.
- Updated only the package facade and `_contract.py` import/doc references; no compatibility shim.
- Appended one layout/import contract; RED failed on the missing public path, GREEN passed after
  the rename.
- Focused decomposition suite: **252 passed**. Ruff, format, Pyright, enterprise guard, and full
  coverage gate: **ALL GATES GREEN**.
- No OpenRouter, persistence, schema, or migration change in this naming cycle. Included in the
  final naming commit; no push.

Status: **DONE**.

## Auth-context naming correction (2026-09-01)

### Intent

Apply the owner's explicit naming decision: the shared auth-route context module must be
`routes/auth_context.py`, without a leading underscore and without a compatibility wrapper.

### Planned changes

- Rename `_auth_context.py` to `auth_context.py` and update its six route import sites.
- Append a layout/import contract proving the public filename exists and the old file does not.
- Update the OME-1026 decomposition ledger reference.
- Do not change runtime behavior, persistence, schema, migrations, or provider logic.

### Test plan and acceptance

- RED: the new layout contract fails while only `_auth_context.py` exists.
- GREEN: the new module imports, the old path is absent, and the full decomposition suite passes.
- Gates: Ruff, format, Pyright, enterprise guard, and the AIGateway gate runner.
- Acceptance: no compatibility shim and no unrelated dirty file staged.

### Outcome

- Renamed `routes/_auth_context.py` to `routes/auth_context.py` without a compatibility shim.
- Updated exactly six route import sites and the decomposition ledger reference; function bodies
  and route behavior are unchanged.
- Appended one layout/import contract; RED failed on the missing public path, GREEN passed after
  the rename.
- Focused auth/decomposition suites: **362 passed**. Ruff, format, Pyright, enterprise guard, and
  full coverage gate: **ALL GATES GREEN**.
- No provider, persistence, schema, or migration change. Included in the final naming commit;
  no push.

Status: **DONE**.

## Final-review credential-ownership remediation (2026-09-01)

### Intent

Resolve the two retained findings from the scoped multi-agent review without widening OME-1026:
preserve a replacement owner's private catalog when a stale manual refresh fails after losing its
ownership race, and align discovery docstrings with the shipped profile-credential security model.

### Planned changes

- Append a deterministic regression test for the failing-refresh ownership-race branch.
- In that branch only, keep the replacement owner's private catalog after
  `ProfileTransitionConflict`, while preserving retirement when the failing refresh still owns the
  profile.
- Replace the rejected deployment-key wording in the two identified Python docstrings.
- Do not address the three sub-threshold open questions, change provider behavior, alter schema, or
  add a migration.

### Test plan and acceptance

- RED: the appended race test proves that the stale failing refresh causes an avoidable second
  private-catalog dial on the replacement owner at `83b1a44f`.
- GREEN: the replacement listing remains fresh with no second dial; existing success/error paths pass.
- Verify no stale deployment-key assertion remains in the two reviewed modules.
- Run focused ownership/auth tests and the complete AIGateway gate runner.
- Acceptance: no isolation or API behavior change beyond preventing the losing refresh from retiring
  another owner's private catalog; no unrelated dirty file touched.

### Outcome

- Appended a deterministic error-branch race regression in its own focused test module rather than
  growing the existing 473-line ownership-fence test file.
- RED reproduced the reviewed defect exactly: the replacement owner warmed once, then the first
  listing performed a second dial because the losing refresh had retired that catalog.
- GREEN keeps the replacement owner's private catalog only when `mark_authenticated_error` raises
  `ProfileTransitionConflict`; an error still owned by the current profile retains the prior
  retirement behavior.
- Replaced the rejected deployment-key claims in `core/parameter_discovery.py` and Anthropic's
  parameter-discovery docstring with the shipped profile-credential allowlisted-origin contract.
- Focused ownership/auth tests: **121 passed**. Ruff, format, Pyright, enterprise guard, and full
  coverage gate: **ALL GATES GREEN**.
- The three sub-threshold review questions remain unchanged for owner adjudication. No schema,
  migration, dependency, provider protocol, commit, or push.

Status: **DONE**.

## Implicit default provider credential (2026-09-02)

### Intent

Deliver the owner-confirmed product contract recorded in
`.agent-team-AIGW/live-anthropic-model-discovery/implicit_default_credential_implementation_prompt.md`:
`GET /v1/models` resolves each provider's ONE effective credential automatically
(hosted `default` Profile, or the sole active local Connection), contributes that
caller's credential-scoped live rows to their own response, and retains static seeds
on missing/unsupported/ambiguous/failed discovery. `/v1/model-parameters` and chat
resolve the SAME effective credential. The Engine's declared-world projection and all
prior discovery safety properties are preserved. Supersedes the earlier rule that
`/v1/models` may never contain credential-derived Anthropic rows; the invariant is now:
private rows may appear only in the authenticated caller's own response, never in a
deployment-global cache or another account's response.

### Planned changes

- U1 `core/effective_credential.py` (new): `EffectiveCredential` value object +
  `AmbiguousCredential`/`UnknownConnectionLabel` refusals + `resolve_effective_credential`
  (Profile named `default` first; else sole active provider Connection; never an
  arbitrary pick). `routes/chat_credentials._credential_target_for_chat` becomes a thin
  mapping onto its existing HTTP contract.
- U2 `core/oauth/models/oauth_connection.py`: durable non-secret
  `credential_generation` IntField (default 0) + migration `0011`; atomic `F()+1`
  bumps in `store.reactivate`/`complete_pending`/`complete_active`; `create_api_key`
  publishes at generation 1. Connection cache revision `{auth_type}@conn:{id}@gen{N}`.
  Post-commit private-catalog invalidation on replace/delete in
  `routes/oauth_connections.py`.
- U3 `core/profile_model_catalog.py`: target-shaped `snapshot_for_target` (existing
  `snapshot_for` delegates); `routes/models.py` composes PUBLIC_GLOBAL (unchanged
  `ModelCatalog`) and PROFILE_CREDENTIAL (resolver + private catalog) concurrently
  under the same 3s wait ceiling; router gains `private_cache_route()`.
- U4 `routes/model_parameters.py`: `_private_catalog_ids` resolves through the shared
  resolver; the mixed-generation fence becomes a credential-revision fence covering the
  local Connection identity.
- U5: update OME-1026 docs/planning artifacts that still state the superseded
  exclusion rule; pin Engine/Python-Client boundary only if a gap is proven.

### Test plan

RED-first per unit: resolver unit tests (hosted/local/none/ambiguous/pending/error/
credential-free + listing–chat agreement); connection revision & lifecycle-fence tests
(replace, delete/recreate, stale in-flight publish, deactivation) with injected clocks
and barriers, no sleeps; migration test for 0011; `/v1/models` route tests (hosted +
local live rows without `X-Profile`, byte-identical seeds + zero egress on
none/unsupported/ambiguous, account A/B isolation, OpenRouter stays global, ordering,
3s ceiling, private cache policy + Vary on every response class);
`/v1/model-parameters` discovered-only ID resolution without `X-Profile` for both
backings + cross-account/ambiguity/superseded-generation refusals; chat dispatch parity.
Prior tests are append-only except assertions that directly encode the superseded
exclusion contract in `tests/unit/core/test_models_route_anthropic_scope_boundary.py`
(each replacement recorded below).

### Acceptance

Completion criteria 1–10 of the implementation prompt demonstrated; all AIGateway
gates green (`run_gates.py aigateway`, append-only gate `--base origin/main` with only
pre-approved exceptions plus the recorded superseded-contract replacements); no
commit/push/PR/live egress without authorization; worktree's unrelated files untouched.

### Outcome

Status: DONE. This initial implementation state was uncommitted when verified and later
landed, together with its bounded correction pass, in `f0e23f05`. Push and PR updates
remained unauthorized at that point.

Delivered as planned, U1–U5, TDD (RED observed before every production change):

- **U1** `src/aigateway/core/effective_credential.py` (new): `EffectiveCredential`,
  `AmbiguousCredential`, `UnknownConnectionLabel`, `resolve_effective_credential`,
  `connection_credential_revision`. `routes/chat_credentials.py` now maps the shared
  resolver onto its unchanged HTTP contract (`_active_oauth_connection_for_profile`
  removed; unused `_DEFAULT_PROFILE_NAME` removed). Tests:
  `tests/unit/core/test_effective_credential_resolution.py` (13).
- **U2** durable Connection revision: `credential_generation` IntField on
  `BaseOAuthConnection` + migration
  `src/aigateway/migrations/0011_connection_credential_generation.py` (S1 satisfied;
  migration test `tests/unit/test_migration_0011_connection_credential_generation.py`
  proves populated-DB apply, idempotence, backfill 0, NOT NULL + SQL default).
  Atomic `F()+1` inside the conditional UPDATEs (`reactivate`, `complete_pending`,
  `complete_active`), generation 1 on `create_api_key`, in-memory bump in full-save
  `complete`. Post-commit retirement of the logical `default` private identity on
  connection key replace/delete via `retire_connection_credential` in
  `routes/profile_credential_lifecycle.py` (called from `routes/oauth_connections.py`).
  Tests: `tests/unit/core/test_connection_credential_revision.py` (9), incl. proof a
  replaced credential cannot read the previous snapshot and a stale in-flight refresh
  publishes only under its own identity.
- **U3** `GET /v1/models` composes per caller: `routes/models.py` gained
  `_all_listings`/`_private_listing` (one gather: PUBLIC_GLOBAL via unchanged
  `_live_listings` — signature preserved for
  `tests/unit/core/test_models_route_public_budget.py` — plus PROFILE_CREDENTIAL via
  resolver + `ProfileModelCatalog.snapshot_for_target` under the same
  `user_wait_budget` ceiling) and `route_class=private_cache_route()`.
  `routes/profile_models.py` generalized the deferred credential reader as
  `deferred_auth_provider(credential_name, auth_type)`; `auth_provider_for` delegates.
  `core/profile_model_catalog.py`: `snapshot_for_target` accepts any
  `DiscoveryCredentialTarget` (Protocol moved to `core/effective_credential.py` with a
  `profile_discovery_target` adapter during REFACTOR to hold the 450-line bound).
  Tests: `tests/unit/core/test_models_route_effective_credential.py` (12) and
  `tests/unit/core/test_models_route_private_budget_and_cache.py` (4: gated
  bounded-wait-not-work, rendezvous concurrency proof, cache policy on 200 and 401).
- **U4** `routes/model_parameters.py`: `_private_catalog_ids` resolves through the
  shared resolver (returns ids + durable credential REVISION string);
  `_refuse_mixed_generation` replaced by `_refuse_changed_credential` (re-resolves and
  refuses 409 `credential_generation_changed` unless an `EffectiveCredential` with the
  identical revision), extending the F4 fence to Connection replacement/delete. Tests:
  `tests/unit/core/test_model_parameters_effective_credential.py` (6);
  `tests/unit/core/test_private_parameter_generation_fence.py` unchanged and green.
- **U5** superseded-rule documentation updated: `core/model_discovery_scope.py`,
  `core/model_catalog.py`, `core/profile_model_catalog.py` docstrings; docs/tasks
  mirror (new dated section); `.agent-team-AIGW/live-anthropic-model-discovery/
  initial_task_description.md` + `implementation_plan.md`. Engine/Python-Client: no
  gap proven — the Engine only forwards an optional caller `X-Profile` and its
  declared-world filtering is independent of listing composition; no change.

**Append-only exceptions (superseded contract), all in
`tests/unit/core/test_models_route_anthropic_scope_boundary.py`:**

1. `test_a_stored_api_key_profile_does_not_make_v1_models_live` →
   `test_an_authenticated_profile_without_a_stored_key_fails_closed_to_seeds`. The old
   name/docstring encoded the rejected exclusion rule; the harness (an AUTHENTICATED
   index row with NO stored key blob) actually proves the fail-closed decrypt path, so
   the replacement pins that surviving claim; the inversion (owner's response goes
   live) is pinned in `test_models_route_effective_credential.py`.
2. Module docstring + `_UPSTREAM_ONLY` comment reworded from "never live on
   `/v1/models`" to "never deployment-global / never another account".

No other pre-existing test was modified. Prior-suite regression fixed during U2
REFACTOR: `routes/oauth_connections.py` (pinned pre-existing oversize, 521) and
`core/profile_model_catalog.py` (450 limit) had grown past their bounds; resolved by
moving the retirement helper into `routes/profile_credential_lifecycle.py` and the
target Protocol/adapter into `core/effective_credential.py` (now 520/449 lines).
Pyright surfaced (and the move fixed) a latent defect: the target Protocol declared
writable members a frozen dataclass cannot satisfy — now read-only properties.

Checks actually run (all green, 2026-09-02):
- focused RED/GREEN runs per unit (13 + 9 + 1 migration + 12 + 4 + 6 tests);
- full unit suite `uv run pytest tests/unit -q -m "not live"`: **4736 passed** (post-U3;
  final full run via gates below);
- `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` and
  `uv run .claude/scripts/run_gates.py aigateway --base origin/main` from the repo
  root (append-only report: only the recorded boundary-file replacement);
- direct: `ruff check .`, `ruff format --check .`, `pyright` (0 errors project-wide,
  tests included), `python scripts/check_no_enterprise.py`, `git diff --check` — all
  clean. Final `run_gates.py aigateway --skip-append-only`: **ALL GATES GREEN**
  (ruff check, ruff format, pyright, no-enterprise, full pytest with
  `--cov-fail-under=80`).

Deviations: U3 route tests split into two files (effective-credential behavior vs
budget/concurrency/cache-policy) to stay within the 450-line bound; the fence helper
was renamed (`_refuse_mixed_generation` → `_refuse_changed_credential`) — private,
no external references. No commit was made (not authorized); the branch's staged
state is untouched.

## Implicit-default correction pass (2026-09-02)

Independent review rejected the preceding closure as not merge-ready. This bounded
pass keeps the accepted implicit-credential design and fixes only defects inside that
contract.

### Intent

- Make local implicit resolution fail closed whenever more than one active Connection
  exists, including the previously missed `default` + another-label case.
- Propagate programming errors from private discovery while preserving expected,
  sanitized discovery fallback.
- Restrict durable Connection generation changes to API-key publication and
  replacement. Automatic OAuth refresh publication fencing remains a separate issue.
- Restore the touched-source 450-line limit through a cohesive API-key route split and
  remove contradictory current-contract documentation.

### Planned changes

- Add RED resolver/listing/parameters/chat regressions for the `default` + another
  active Connection ambiguity, including zero discovery egress.
- Add RED awaited/background regressions for unexpected private-refresh errors.
- Remove generation increments from generic/OAuth `complete`, `complete_pending`, and
  `complete_active`; retain API-key create/reactivate revision behavior and migration
  `0011`.
- Extract only API-key Connection routing/publication responsibility from
  `routes/oauth_connections.py`; preserve every public HTTP path and OAuth flow.
- Correct the planning pack, task mirror, source comments, and this ledger. No Client,
  Engine, provider parser, OpenRouter, explicit-profile-endpoint, schema, or automatic
  OAuth refresh changes.

### Test plan and acceptance

- Observe each new regression RED for its intended reason before production edits.
- Run focused effective-credential, listing, parameters, chat, Connection revision,
  API-key route, profile-catalog error, background sink, migration, cache-policy,
  Anthropic, and OpenRouter suites.
- Run both AIGateway gate modes plus direct Ruff, format, Pyright, no-enterprise,
  `git diff --check`, and final worktree status.
- Acceptance: ambiguous implicit state funds no egress; programming defects remain
  loud; API-key generation remains durable and atomic; OAuth refresh is unchanged;
  every touched source file is at most 450 lines; documentation states the accepted
  private-per-owner/global-isolation contract consistently.

### Correction outcome

Status: **DONE**. Commit authorized by the owner on 2026-09-02; push and PR
updates remain unauthorized.

- `resolve_effective_credential` now handles implicit `default` before label
  matching: exactly one active Connection resolves regardless of label; more than
  one returns `AmbiguousCredential`. Explicit non-default labels still resolve.
- `ProfileModelCatalog._refresh` still sanitizes and damps expected discovery/auth
  failures, but logs only the type and re-raises unexpected programming errors.
  Awaited callers observe the original error; unawaited work reaches the bounded
  sanitized background-error sink.
- Connection generation now covers only API-key ownership publication: creation
  starts at one and `reactivate` atomically applies `F() + 1`. Generic `complete`,
  OAuth callback `complete_pending`, and refresh metadata `complete_active` preserve
  the generation. The separate automatic OAuth refresh publication race was not
  changed.
- API-key create/replace routes moved without behavior changes to
  `routes/api_key_connections.py`; `routes/oauth_connections.py` includes that
  subrouter. Final source sizes: `oauth_connections.py` 341,
  `api_key_connections.py` 216, `effective_credential.py` 232,
  `profile_model_catalog.py` 447, and `core/oauth/store.py` 413 lines. Every
  source file touched by the implicit-default implementation is at most 450 lines.
- Current planning, task, deployment, and operator documentation now permits the
  authenticated caller's private rows in their own `/v1/models` response while
  retaining the deployment-global and cross-account exclusion.

RED evidence observed before production fixes:

- five ambiguity/programming-error regressions failed: resolver selected the
  `default`-labelled Connection, `/v1/models` funded a forbidden dial,
  `/v1/model-parameters` returned a private contract, and awaited/background
  `RuntimeError` cases became `internal_error` fallback;
- three generation-scope regressions failed because `complete`,
  `complete_pending`, and `complete_active` advanced `0→1`, `0→1`, and `7→8`.

Checks actually run after correction (2026-09-02):

- focused correction: **5 passed**, generation/lifecycle: **49 passed**,
  route/contract set: **74 passed**, expanded provider/cache/background/migration
  set: **378 passed**;
- direct full non-live suite: **4752 passed, 18 skipped, 37 deselected**;
- direct Ruff check, Ruff format check, Pyright (0 errors), no-enterprise, and
  `git diff --check`: green;
- `run_gates.py aigateway --skip-append-only`: **ALL GATES GREEN** including full
  coverage ≥80;
- `run_gates.py aigateway --base origin/main`: stopped only at the append-only
  precheck. Its branch-wide list contains previously recorded multi-cycle changes;
  this correction adds the necessary `test_chat_request_cache.py` adjustment so
  its cache characterization uses two explicit labels instead of relying on an
  implicit request to choose among two active Connections.

Prior-test corrections directly encoding superseded behavior:

- `test_profile_model_catalog.py`: unexpected `ZeroDivisionError` now propagates
  instead of asserting `internal_error` fallback;
- `test_chat_request_cache.py`: the two-profile cache test now uses explicit
  `work` and `personal` labels; its global-cache assertion is unchanged.

No Client/Engine production code, provider parser, OpenRouter behavior, automatic
OAuth refresh flow, explicit profile endpoint, schema beyond existing migration
`0011`, unrelated worktree file, push, rebase, merge, PR, or live provider state
was changed by this correction pass. Staging is limited to the OME-1026 source,
tests, migration, and four owner-approved tracked documentation paths. Authorized
commit message: `feat(aigateway): resolve implicit discovery credentials` with
`Refs: OME-1026`; `.agent-team-AIGW/**` remains local and untracked.

## Final P3 review corrections (2026-09-02)

### Intent

Close the five non-blocking findings in
`.agent-team-AIGW/live-anthropic-model-discovery/implicit_default_credential_review_report.md`
without changing effective-credential selection, discovery behavior, cache identity,
migration SQL, or the settled hosted/local product contract.

### Planned changes

- Make ambiguity and unknown-label response bodies advertise only explicit Connection
  labels that can actually be selected; the reserved literal `default` continues to
  invoke implicit sole-Connection resolution.
- Route unexpected-error and capacity-refusal identity logging through one bounded,
  control-safe renderer. Credential-selection and error propagation remain unchanged.
- Correct the model and migration comments to state the API-key-only generation policy.
- Remove the obsolete 521-line `oauth_connections.py` exemption and make the inventory
  guard verify that every exemption is still oversized on disk.
- Correct the historical implicit-default Outcome to distinguish the earlier uncommitted
  state from its landing in `f0e23f05`.

### Test plan and acceptance

- Observe RED HTTP coverage for `X-Profile: default` with `default + other` active
  Connections and RED caplog coverage for oversized/control-bearing background keys.
- Run the new focused tests, all directly affected prior suites, then the AIGateway gate
  runner with coverage.
- Acceptance: all five P3 findings are closed; no credential is selected differently; no
  discovery egress, schema, migration operation, endpoint, or Engine/Client behavior
  changes; source remains within the 450-line discipline.

### Outcome

Status: **DONE**.

- Ambiguous and unknown-label chat refusals now expose only actionable non-default
  labels. `default` remains reserved for the unchanged implicit sole-Connection path;
  no credential-selection branch changed.
- `safe_background_key` now bounds identity text to the existing 200-character cap and
  replaces control characters before both operator logging and retention. The unexpected
  error and capacity-refusal paths share it.
- The model/migration comments now match the tested API-key-only generation policy; the
  migration operations and SQL are unchanged.
- The obsolete `oauth_connections.py` 521-line exemption is gone, and the inventory
  hygiene test now requires every remaining exemption to still exceed 450 lines on disk.
- The earlier Outcome records its historical uncommitted state and the later landing in
  `f0e23f05` without contradiction.

RED evidence: the three new checks failed for the reported reasons — missing actionable
labels in the 409, a control character retained/logged by the unexpected-error sink, and
an unbounded control-bearing capacity-refusal log key.

Checks after GREEN:

- new P3 checks plus decomposition hygiene: **4 passed**;
- affected chat/background/decomposition/generation/migration suites: **359 passed**;
- `uv run .claude/scripts/run_gates.py aigateway --skip-append-only`: **ALL GATES GREEN**
  (Ruff check, Ruff format, Pyright, no-enterprise, full pytest with coverage >=80);
- `git diff --check`: clean; touched source sizes: chat credentials 421, background error
  sink 257, background refresh 259, OAuth Connection model 59, migration 21 lines.

No external dependency, schema, migration operation, discovery call, credential resolver,
cache identity, Client/Engine file, unrelated worktree path, push, PR, merge, or live
provider state changed. Owner authorized a separate P3 follow-up commit; intended message:
`fix(aigateway): close implicit discovery review findings` with `Refs: OME-1026`.
