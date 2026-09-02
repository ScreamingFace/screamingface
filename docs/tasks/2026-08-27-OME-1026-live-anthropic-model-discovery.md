---
id: OME-1026
linear_url: https://linear.app/openmined/issue/OME-1026/aigateway-automatically-discover-models-offered-by-anthropic
status: In Progress
type: feature
priority: 2
labels: [aigateway, agentic, autonomous]
created: 2026-08-27
closed:
---

# AIGateway: automatically discover models offered by Anthropic

> **The description in this section is SUPERSEDED.** It records the rejected deployment-key design.
> The current architecture is "Profile-scoped rework (2026-08-28)" at the bottom of this file.

Opt-in live model discovery for the Anthropic provider — the **second** implementation of the
`ModelListingProvider` port delivered by OME-972 (`cc9deb4a`), reusing the existing process-local
`ModelCatalog` (TTL 300 s, stale 3600 s, failure damping 30 s, single-flight) unchanged. A healthy
snapshot changes only the Anthropic **ID set** published by `GET /v1/models`; chat dispatch,
admission, and `anthropic:static` parameter evidence are untouched.

Anthropic's catalog is credentialed-only (401 without `x-api-key`), so discovery is strictly
opt-in behind one dedicated operator secret, `AIGW_ANTHROPIC_DISCOVERY_API_KEY`. Account API keys
(`credential_blobs`) and Claude-subscription OAuth tokens never feed the shared snapshot. The
three off-switches — no key configured (the default), `AIGW_ANTHROPIC_LIVE_MODELS=false`, and the
global `AIGW_DISCOVERY_ENABLED=false` — each mean zero Anthropic catalog egress and the exact
compiled seed listing. Anthropic has no provider-disable flag and introducing one is out of scope.

Completeness without a census: Anthropic's envelope carries no `total_count`, so completeness is a
strict `has_more`/`last_id` cursor walk under bounded pages, models, bytes, ID length, and one
aggregate deadline, with a cursor-progress guard over the SET of seen cursors. Cursors are
upstream-controlled URL material and must clear the same safe charset as publishable IDs before
being URL-encoded into the next dial. Aliases and date-stamped snapshots publish unfolded as
separate dispatchable IDs in upstream order, deduplicated on first occurrence (D7, owner-approved
2026-08-26) — no alias folding is inferred.

- Ledger: `docs/work/2026-08-27-OME-1026-live-anthropic-model-discovery.md`
- Planning pack: `.agent-team-AIGW/live-anthropic-model-discovery/` (local, untracked)
- Baseline: OME-972 / PR #739 merged as `cc9deb4a`; branch
  `OME-1026-live-anthropic-model-discovery`
- Related: OME-972 (foundation), OME-479 (§6.3 superseded for the model LIST only), OME-818
  (current seed catalog), SF-284 (historical removed Settings-dropdown consumer)

## Deviation accepted at start (owner decision, 2026-08-27)

The credentialed Anthropic Models probe named as this issue's "First implementation step" was
**not run** — `AIGW_ANTHROPIC_DISCOVERY_API_KEY` is not available in the execution environment,
and the Claude Code OAuth token is off limits for discovery by locked decision D2. The owner chose
to proceed without it. U3/U4 fixtures derive from the Context7-verified official Models API
contract recorded in the planning pack's `research_notes.md`. Real page-2 behavior and the
observed alias/snapshot interleaving remain unverified against production; every unverified shape
fails closed to stale-then-seeds. Zero credentialed egress occurs in this unit.

## Implementation status (2026-08-27)

Implemented through units U1–U8 and gate-green on branch
  `OME-1026-live-anthropic-model-discovery` (baseline `cc9deb4a`), and **committed as `72eaa390`** on
explicit owner authorization for that commit. A later review-fix pass (blank-discovery-key egress,
case-insensitive `Accept-Encoding` merge, stale comment/doc wording) is committed separately in the
commit containing this task-mirror update. No PR is open. Full detail in the ledger.

- Counts for `72eaa390`+`056971a4`: 155 new tests; full non-live suite 4208 passed / 0 failed;
  pyright 0 errors; coverage ≥80. **Superseded by the profile-scoped rework below.**
- `run_gates.py aigateway --skip-append-only` → ALL GATES GREEN.
- **One-file append-only waiver granted by the owner on 2026-08-28:**
  `apps/aigateway/tests/conftest.py`. The autouse no-egress
  tripwire hardcoded the legacy `get(self, url, *, timeout_s, max_bytes)` signature, so it gains
  and forwards an optional `headers` (`AssertionError` check still first). This is the CC-1
  blocker resolution disclosed in plan D1; the change is signature-compatible and alters zero
  test cases. Without it, every header-carrying dial through the real adapter would raise
  `TypeError`, which `ModelCatalog` sanitizes into a quiet seeds listing — a test that genuinely
  reached the internet would pass green.
- Deviation of note: D1's narrowing device is `cast`, not `isinstance` — pyright rejects the
  isinstance form as an unsafe protocol overlap (the static form of CC-2's finding). The
  argument-binding `TypeError` boundary remains the only runtime guarantee, exactly as D1 specified.

## Profile-scoped rework (2026-08-28) — supersedes the description above

The dedicated-key architecture described above is **rejected**. Authoritative brief:
`.agent-team-AIGW/live-anthropic-model-discovery/profile_scoped_rework_prompt.md`.

- `AIGW_ANTHROPIC_DISCOVERY_API_KEY` is **removed**, not deprecated. Setting it has no effect.
- Anthropic discovery is **private and profile-scoped**: one snapshot per
  `(account_id, provider, profile_name, credential_revision)`, fetched with that profile's own
  already-stored credential (no re-entry, no migration), served only to its owner via
  `GET /v1/auth/{provider}/profiles/{name}/models`.
- OpenRouter remains the **public global** catalog on `GET /v1/models`; Anthropic publishes only
  its compiled seeds there and performs zero catalog egress on that path.
- A credential-derived listing can never enter the global catalog: `ModelCatalog.entries_for`
  refuses any non-`PUBLIC_GLOBAL` scope before consulting the source, and the Anthropic plugin does
  not implement the public listing hook at all.
- Max 3 s user-facing wait (`AIGW_DISCOVERY_TIMEOUT_SECONDS`); the refresh is never cancelled by
  the wait expiring, so a later request observes it.
- Contract designed for future public Hugging Face and profile-scoped OpenAI/Gemini discovery;
  neither implemented here.

Counts for the rework: 5 new source modules + 9 modified; 4 new test suites, 1 renamed+rewritten,
3 rewritten. Full non-live suite **4268 passed / 0 failed**; `ruff check` / `ruff format --check` clean;
`pyright` 0 errors; `check_no_enterprise.py` OK; `git diff --check` clean;
`run_gates.py aigateway --skip-append-only` → ALL GATES GREEN (coverage ≥80).

Prior-test replacement is owner-authorized by the rework brief, and measured: every replaced test
was introduced by `72eaa390` on this same unmerged branch and has never existed on `origin/main`
(the OME-1026 test surface is +1778 / -0 against the merge base). The append-only check reports one
offender only — the already-waived `tests/conftest.py`. Uncommitted: no commit, push, or PR
authorized for this pass.

Open product decisions carried forward: per-account fairness of the shared 512-entry snapshot and
in-flight bounds; whether the user-facing wait should be tunable separately from the dial timeout;
whether `/v1/model-parameters` should consult the caller's private catalog (a discovered-only id is
deliberately not globally resolvable).

## Independent-review remediation (2026-08-28)

An independent review of the profile-scoped rework returned **NOT MERGE-READY** with eight
findings (`.agent-team-AIGW/live-anthropic-model-discovery/profile_scoped_rework_review_findings.md`).
All eight were re-verified against the code, reproduced with a failing deterministic test, and
closed at the root cause. No prior assertion was weakened.

| # | Severity | What was wrong | Now |
|---|---|---|---|
| 1 | HIGH | the private listing carried no HTTP cache policy; in `cloudflare_headers` mode two accounts request one identical URL | every response carries `private, no-store` + `Vary: Authorization, X-User-Email`, on the normal return and on every raise |
| 2 | MEDIUM | a cold `GET /v1/models` could wait out OpenRouter's own 10 s refresh deadline | each provider is waited for at most `AIGW_DISCOVERY_TIMEOUT_SECONDS`; on expiry that provider serves seeds and its refresh continues |
| 3 | MEDIUM | the private cache identity used a wall clock, so two replacements in one tick collided | a durable `credential_generations` counter bumped inside the atomic index CAS |
| 4 | MEDIUM | private rows advertised a `parameter_contract_url` that returned 404 | the detail route resolves the caller's own private snapshot for its own profile; cross-account and sibling-profile ids stay `model_not_found` |
| 5 | MEDIUM | cancellation-resistant superseded refreshes stopped counting against capacity; shutdown could hang | capacity and the gauge count every live task; shutdown is bounded |
| 6 | MEDIUM | prewarm laundered programming errors; a fast post-commit failure could 5xx after the credential committed | a retention sink observed at an explicit hook; a zero budget is start-only; prewarm starts manager-owned tasks and never awaits |
| 7 | LOW | 512 identities x 2 000 rows was an unbounded memory footprint | a total row budget (`AIGW_DISCOVERY_PROFILE_CACHE_MAX_ROWS`, default 16 384) alongside the identity bound |
| 8 | LOW | docs named a nonexistent reason and mis-stated stale semantics; three acceptance claims were indirect | corrected reason table and stale semantics; restart-persisted credential, cross-account shared public snapshot, and private discovered-id detail + dispatch tests added |

Four open owner decisions are recorded in the work ledger (`docs/work/2026-08-27-OME-1026-*.md`,
"Deviations and open owner decisions"): the suite-wide background-error assertion, one prior
test's internal concurrency probe, the chosen row budget, and a reported accidental outbound
request during test authoring.

## Final remediation pass (2026-08-31) — SUPERSEDED

> Its closure claim was **withdrawn**: two adversarial schedules it did not cover were
> reproduced afterwards. The fix descriptions below are accurate for what that pass did;
> the authoritative status of every finding is the FINAL DISPOSITION table at the end of
> this file.

The independent-review closure report was itself reviewed and returned **NOT MERGE-READY**
(`.agent-team-AIGW/live-anthropic-model-discovery/profile_scoped_rework_final_fix_prompt.md`, which
also settled owner decisions 1-8). Eight fixes, each driven by a failing deterministic test first:

| Fix | What was still wrong | Now |
|---|---|---|
| F1 | the cache policy was set inside the endpoint body, so every **pre-handler** 401/403 from `CurrentAccount` was emitted with no cache directives at all | a `PrivateCacheRoute` route class wraps dependency resolution on both private routes, merging the policy into `exc.headers` on any raise — including exits nobody has written yet |
| F2 | 3 s was only a DEFAULT: raising `AIGW_DISCOVERY_TIMEOUT_SECONDS` to 10 lengthened the user's wait to 10 s | one hard ceiling, `user_wait_budget = min(configured, 3.0)`, on the global and profile listings. The wait is clamped; the refresh keeps running |
| F3 | manual OAuth refresh wrote the credential blob and bumped the generation in two separate durable writes | `credential_generation` is now an **ownership/authentication fence**: a routine refresh does not bump, so the un-atomic window stops existing rather than being guarded |
| F4 | `/v1/model-parameters` read the profile index twice and could return a 200 mixing two credential generations | the admitted generation is re-checked after resolution; a rotation (or deletion) at the seam is a retryable **409 `credential_generation_changed`** |
| F5 | (already closed) | unchanged, re-verified |
| F6 | a drain-only fixture, and `take_unexpected()` silently dropped overflow, so a background bug could pass green | suite-wide autouse assertion over all 4384 tests; overflow is loud; tests that do not exercise Anthropic profile discovery disable it, discovery suites opt in by name |
| F7 | a `len > 1` carve-out let one oversized snapshot exceed the row maximum; docs and code carried unmeasured byte estimates | the maximum is **hard, no carve-out** — an oversized snapshot is refused with `reason=cache_row_budget_exceeded`, damped by the provider failure TTL, and the last good snapshot survives. Every byte estimate removed |
| F8 | `main.py` 496 and `core/plugin_base/_contract.py` 475 were over the 450-line limit | split by responsibility into `discovery_lifecycle.py` (145, app layer) and `core/plugin_base/model_discovery.py` (218, a mixin). `main.py` **407**, `_contract.py` **307**. No compatibility wrappers |

Verification: full non-live suite **4384 passed / 18 skipped / 37 deselected / 0 failed**;
`ruff check` + `ruff format --check` clean; `pyright` **0 errors**; `check_no_enterprise.py` OK;
`run_gates.py aigateway --skip-append-only` → **ALL GATES GREEN**; `git diff --check` and
`--check --cached` clean. No live provider probe was run (owner decision 8); the 37 deselected are
the `live` marker.

Append-only against `origin/main` is RED on exactly three files: `tests/conftest.py` (the
pre-existing owner waiver of 2026-08-28) plus the two owner-approved re-pins —
`test_profile_index_serializes_with_version` and
`test_concurrent_callers_share_one_upstream_fetch_chain_and_all_get_200` (which now proves six
concurrent callers, one shared manager task, one upstream fetch, and six 200s).

The four previously open owner decisions are resolved: D-R1 (suite-wide assertion) and D-R3 (row
budget 16 384 as a hard total) are **closed by owner decision**; D-R2 (the two re-pins) is approved;
D-R4 (chat-transport no-egress guard) stays a separate proposal, deliberately not folded into this
unit. `routes/auth.py` (1509) and `plugins/openrouter_provider/plugin.py` (572) remain over the
450-line guideline and were already non-compliant on `origin/main`.

Still uncommitted: no commit, push, staging, or PR is authorized for this pass.

## Final disposition (2026-08-31)

Authoritative status of every finding, superseding both closure tables above.

**Scope correction (owner, 2026-08-31 19:26).** The last-mile prompt
(`profile_scoped_rework_last_mile_prompt.md`) is itself now marked **SUPERSEDED — DO NOT
EXECUTE**: it broadened OME-1026 into shared OAuth refresh behaviour for Anthropic, Gemini,
Codex and Antigravity. The authoritative contract is
`.agent-team-AIGW/live-anthropic-model-discovery/initial_task_description.md` +
`implementation_plan.md`, which place **chat dispatch and automatic OAuth token-refresh
behaviour outside this unit** ("Excluded Scope"; plan U10). The automatic-refresh fence built
against the superseded prompt was reverted from the worktree accordingly — see the hand-off
below.

| Area | Status | Where it stands |
|---|---|---|
| F1 private cache policy | **CLOSED** | a `PrivateCacheRoute` route class wraps dependency resolution on both private routes, so 2xx, `HTTPException`, 422, unexpected 500 and pre-handler 401/403 all carry `private, no-store`; existing `Vary` tokens are merged, not overwritten |
| F2 hard user wait | **CLOSED** | `user_wait_budget = min(configured, 3.0)` on both listings — a hard ceiling, not a default. The wait is clamped; the shared refresh is never cancelled |
| F3 ownership fence | **CLOSED for this unit** | the in-scope fence is the manual profile-credential path: `BufferedRefreshCredentialStore` defers every provider write into the publication transaction, where a byte-exact credential CAS sits beside the profile-index CAS (presence + expected generation + expected auth type) in the OME-307 index-before-credential order. Either check failing rolls both back and answers 409 `credential_owner_changed`. Automatic OAuth refresh is excluded by the corrected contract |
| F4 generation consistency | **CLOSED** | `/v1/model-parameters` re-checks the admitted ownership generation after resolution, so a rotation or delete at the seam is a retryable 409 `credential_generation_changed` instead of a 200 mixing two generations. It no longer depends on the automatic-refresh path: discovery is **API-key only** (settled decision 4 — an OAuth profile returns `unsupported_auth_type` before any credential read), so no OAuth refresh can produce or invalidate an Anthropic discovery snapshot, and API-key replacement bumps the generation through the fenced lifecycle path above |
| F5 task lifecycle | **CLOSED** | cancellation-resistant tasks stay strongly tracked and counted after a bounded close |
| F6 background sink | **CLOSED** | the retained record was already sanitized; this pass linearized the last race — the observed MARKER is now read and written inside the same `_sink_lock` section that appends or removes the record, so an observed error is never left retained and an unobserved one is never lost. Cap (32), exact dropped count, atomic drain/reset, cancelled-task behaviour and the suite-wide assertion fixture are unchanged, and the lock is never held across an await |
| F7 row-bound semantics | **CLOSED** | hard row maximum with no oversized-snapshot carve-out; TTL-based fresh/stale/fallback classification; row counts only, no byte estimates |
| F8 module/file compliance | **CLOSED** | every hand-maintained source file this pass touched is ≤450 lines, and `test_module_decomposition_contract.py` now asserts that over the WHOLE package instead of a hand-listed subset, with the four pre-existing oversized files (each byte-identical to `origin/main`) pinned so they may shrink but never grow |

### Hand-off: automatic OAuth refresh publication is unfenced (separate work item required)

Recorded here so the finding is not lost with the reverted code. **Out of scope for OME-1026**
(plan U10: "explicitly outside OME-1026 and must be tracked separately"), and it does **not**
affect this unit, because Anthropic discovery never uses an OAuth profile.

A cached `BaseOAuthStrategy` refreshes and persists inside `_refresh_credential` with a
last-writer-wins `ORMStore.write`. Evicting `CredentialStrategyCache` removes only the map entry
— it cannot stop a strategy instance that is already refreshing. Reproduced schedule:

```text
owner A generation:                 1
owner B reauthentication commits:  generation 2, blob owner-B-new
cached strategy A resumes refresh: writes owner-A-refreshed
final profile:                      owner B, generation 2
final credential blob:              owner-A-refreshed
```

The durable generation then says the blob belongs to B while the bytes belong to A, and the
generation fence cannot detect it because the generation is legitimately 2. The write seam is
byte-identical in `AnthropicOAuth`, `CodexOAuth`, `GeminiOAuth` and `AntigravityOAuth` (each ends
`_refresh_credential` with one `await self._write_to_store(creds)`), so injecting an
ownership-aware conditional store at the single strategy build site fences every provider and
every entry point with no provider edits. `credential_ownership_fence.py` already holds the CAS
protocol to reuse.

### Gate status (this worktree, 2026-08-31)

All required gates green:

| Gate | Result |
|---|---|
| `uv run ruff check .` | clean |
| `uv run ruff format --check .` | 576 files already formatted |
| `uv run pyright` | **0 errors, 0 warnings, 0 informations** |
| `uv run python scripts/check_no_enterprise.py` | OK: no LiteLLM Enterprise imports |
| `uv run pytest -q -m "not live"` | **4694 passed, 18 skipped, 37 deselected, 0 failed** (4:11) |
| `uv run pytest --cov=aigateway --cov-fail-under=80 -q` | run 1: 1 failed (login timing), 4693 passed, 55 skipped, coverage **92.89%**. run 2: **passed** |
| `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` | **ALL GATES GREEN** (lint · format · typecheck · enterprise · coverage) |
| `git diff --check` / `--check --cached` | clean |
| append-only vs `origin/main` | red on exactly the three approved files, no fourth |

Append-only attribution (`--base origin/main`, now `9e739a05`): `tests/conftest.py` (the
pre-existing owner waiver), `tests/unit/core/test_models_route_live_catalog.py` and
`tests/unit/test_profile_index.py` (the two owner-approved re-pins). Nothing else.

Focused suites: 64 background/sink · 59 manual-refresh + generation-fence · 545 across the four
providers' OAuth strategies · 410 chat credential/dispatch · 148 private cache + profile
catalog/row-bound/scope · 239 auth · 1035 OpenRouter · 251 module/size contract. All passed.

Six-caller concurrency contract: **5/5 isolated** fresh processes, plus green inside **both** full
coverage runs. The barrier replaced the 0.2 s sleep; all four assertions are unchanged.

#### `test_unknown_user_timing_close_to_wrong_password` — load-sensitive flake, not a regression

It is neither reliably green nor reliably red, so both halves are recorded. One real production
defect was found and fixed while diagnosing it:

* **Fixed:** `verify_password_or_dummy` made **two** threadpool round-trips for an unknown user and
  one for a known user. A hop measures ~1 ms at the median and ~14 ms at p95 on this machine —
  against a ~300 ms bcrypt(12) verification that is up to half of the test's entire 10 % budget, and
  it could only ever push in the direction that reveals which usernames exist. Both paths now make
  exactly one hop, and the handler is otherwise symmetric: one `Account.get_or_none`, one
  verification, one generic 401.
* **Observed outcomes after the fix:** 14 isolated fresh-process runs → **9 passed, 5 failed**. The
  five failures all came from runs taking 20-31 s while the machine was loaded; the six runs on a
  quiet machine took 13-18 s and all passed. In full runs: the non-live suite passed, coverage run 1
  failed, coverage run 2 passed.
* **Why it flakes:** the test compares two *sequential* 20-sample medians of bcrypt(12) against a
  `<10 %` tolerance. Applying that same methodology to ONE path against ITSELF failed 1 run in 6
  (12.06 % between two identical batches), and individual samples inside a single batch span
  250-650 ms. Four HTTP-level measurements after the fix gave +21.9 ms, −33.0 ms, +51.3 ms,
  +7.4 ms — the sign flips, which a systematic asymmetry cannot do.
* The tolerance is below this machine's noise floor under load. Making it deterministic means
  changing the prior test's methodology, which is an append-only decision outside this unit.

### Acceptance-criteria evidence (authoritative contract, this worktree, 2026-08-31)

Against the 14 criteria in
`.agent-team-AIGW/live-anthropic-model-discovery/initial_task_description.md`. 457 tests, all
passed, no live egress (canned transports + the no-egress tripwire).

| AC | Claim | Evidence |
|---|---|---|
| 1, 2 | a saved API-key profile returns live `anthropic/<id>` rows privately, without re-entering the key | `test_profile_models_route.py` |
| 3 | another account cannot read those rows, same profile name included | `test_private_identity_ownership_changes.py` |
| 4 | a sibling profile cannot resolve another profile's discovered-only ID | `test_private_parameter_contract_url.py`, `test_private_parameter_generation_fence.py` |
| 5 | OAuth profiles do zero Models-API egress, report `unsupported_auth_type`, serve seeds | `tests/unit/anthropic/` |
| 6 | `live_models=false` and `AIGW_DISCOVERY_ENABLED=false` each yield zero egress | `tests/unit/anthropic/test_settings.py`, `test_model_discovery_scope.py` |
| 7 | historical phase: `/v1/models` contained only seeds (superseded below) | `test_models_route_anthropic_scope_boundary.py` |
| 8 | a malformed or incomplete catalog never replaces a good snapshot | `tests/unit/anthropic/test_live_models_port.py` |
| 9 | no credential material in any row, cache key, reason, error or log | `test_discovery_acceptance_gaps.py`, `test_profile_model_catalog.py` |
| 10 | dialed only at `https://api.anthropic.com` with the exact allowlisted headers | `tests/unit/anthropic/test_live_models_fetch.py` |
| 11 | concurrent callers share one refresh chain; bounded waiting does not cancel it | `test_models_route_live_catalog.py`, `test_listing_wait_budget.py` |
| 12 | retained rows never exceed the hard row limit | `test_profile_catalog_row_bound.py`, `test_profile_snapshot_memory_bound.py` |
| 13 | every private response path carries `private, no-store` | `test_profile_models_private_cache_policy.py`, both `test_private_cache_policy_*.py` |
| 14 | focused tests and project gates pass without live egress | see the gate table above |

This acceptance matrix records the superseded explicit-profile-only phase. The
current `/v1/models` contract is the dated implicit-default section below.

Counts by batch: 55 · 18 · 281 · 25 · 36 · 42. U11 verification is complete on this worktree.

## Final naming cleanup (2026-09-01)

The owner required the two OME-1026 decomposition modules to use public filenames, with no
compatibility wrappers:

- `core/plugin_base/_model_discovery.py` → `core/plugin_base/model_discovery.py`;
- `routes/_auth_context.py` → `routes/auth_context.py`.

All import sites and decomposition references now use the public paths. Two append-only layout/import
contracts prove each new path exists, each old path is absent, and the exported symbols originate
from the new module. Focused auth/decomposition suites: **362 passed**. The full AIGateway gate is
green: Ruff, format, Pyright, no-enterprise, tests and coverage. No schema or migration change. Final
commit authorized by the owner; push explicitly prohibited.

## Implicit default credential (2026-09-02) — supersedes the seeds-only `/v1/models` rule

Authoritative brief:
`.agent-team-AIGW/live-anthropic-model-discovery/implicit_default_credential_implementation_prompt.md`
(owner-confirmed product model: ONE implicit credential per provider per account).

- `GET /v1/models` now resolves each `PROFILE_CREDENTIAL` provider's effective credential for the
  CALLER — hosted: the Profile named `default`; local: the sole active Connection, any label —
  through one shared resolver (`core/effective_credential.py`) also used by
  `GET /v1/model-parameters` and chat dispatch.
- The caller's own credential-scoped live rows join THEIR OWN `/v1/models` response, served from
  the revision-keyed private catalog. **Unchanged boundary:** a credential-derived row never
  enters the deployment-global `ModelCatalog` and never another account's response.
- Every non-resolving outcome — no credential, unsupported auth type, more than one active local
  Connection (ambiguous; never an arbitrary pick), a non-`default` hosted profile — keeps the
  byte-compatible compiled seeds with zero provider egress.
- Connections carry a durable `credential_generation` (migration
  `0011_connection_credential_generation`), published as generation one for API-key creation and
  bumped atomically for in-place API-key replacement; generic OAuth activation and refresh do not
  claim an ownership change. The private cache identity for Connection-backed credentials is
  `{auth_type}@conn:{id}@gen{n}` under the logical profile name `default`.
- `/v1/model-parameters` resolves discovered-only ids without `X-Profile` for the effective
  credential (hosted and local) and fences the finished document on the credential REVISION
  (409 `credential_generation_changed`), extending the F4 mixed-generation fence to Connection
  replacement/delete.
- Every `/v1/models` response class now carries `Cache-Control: private, no-store` plus
  identity-aware `Vary` via the same route class as the explicit profile listing endpoint.
- The implicit `default` name never breaks a local tie: `default` plus any other active Connection
  is ambiguous, serves seeds, and funds zero private discovery egress.
- Expected discovery failures degrade normally; unexpected programming errors propagate to an
  awaiting caller or the bounded sanitized background-error sink.

Ledger: `docs/work/2026-08-27-OME-1026-live-anthropic-model-discovery.md`
(section "Implicit default provider credential (2026-09-02)").
