---
ticket: OME-1138
stack: aigateway   # umbrella coordination ledger; consumer stacks get their own sub-issue ledgers
status: in_progress
started: 2026-09-09
finished:
---

# OME-1138 — Deprecate Profiles and converge on Connections (umbrella: P0 baseline + P1 design)

## Intent

Replace the parallel Profile/ProfileIndex and OAuthConnection credential domains in
AIGateway with one canonical Connection per `(account, provider)` shared by Local and
Hosted, OAuth and API key, with one resolver for chat, model parameters, admission,
availability and future credential-scoped discovery. Profiles, `X-Profile` and
`listing_source="profiles"` leave the target runtime contract; compatibility is temporary
with a defined removal point. This ledger covers the umbrella's coordination work:
P0 (verified baseline, consumer/evidence maps) and P1 (target contract, defaults
migrate-or-remove, data migration, authority/rollback, owner decisions). Runtime code
starts only after G1 approval and agreed sub-issues, each with its own ledger.

Inputs: the owner-provided initial task description and implementation plan, plus Linear OME-1138
(read 2026-09-09: In Progress, High, no sub-issues, no comments,
blocks OME-1026/OME-1035).

## Baseline (P0)

- Branch `OME-1138-converge-connections` was created from `origin/main` `b47853ea` in the shared
  checkout (owner exception: no separate worktree). The handoff was actualised at `030c7163`; delta
  `030c7163..b47853ea` = 3 commits (OME-934/OME-1165 structured logs: engine
  `runner/executor.py`, url4 `observe.py`, analytics posthog) — no Profile/Connection
  paths touched.
- Foreign uncommitted state preserved untouched: `M .claude/commands/asana.md`,
  `D web/.gitignore`, untracked `solutions/` and other files.
- No prior OME-1138 branch, worktree, ledger, mirror, spec or plan existed in this clone.
- Baseline gates (untouched base, run 2026-09-09):
  aigateway `ruff check` / `ruff format --check` / `pyright` (0 errors) /
  `check_no_enterprise.py` green; `pytest --cov=aigateway` 4104 passed, 58 skipped,
  coverage 92.53%; one failure `tests/unit/auth/test_login.py::
  test_unknown_user_timing_close_to_wrong_password` (bcrypt timing comparison) also fails
  when rerun alone on the untouched base → pre-existing, environment-sensitive, unrelated
  to this unit; not modified. Meta tools: export 45 ops / 38 schemas / 8 providers,
  projector 40 models / 80 files, coverage 250 files, 146 unit tests OK, metaframework CLI
  0.5.1 valid 89 entities; `solutions/` byte-identical before/after (212 files hashed).
  Engine (`screamingface-engine`, untouched base): ruff / format / pyright (0 errors) /
  layering check green; pytest 2673 passed, 9 skipped, coverage 92.98%.
- Consumer map (Engine, Admin UI, SDK, URL4, Desktop) verified at b47853ea and recorded in
  the spec §8; Desktop tracked `out/*` bundles target the legacy SF server, not AIGateway.
- Meta as-is map (89 entities, Profile SRNs, tool guards, no successor/deprecation rule)
  recorded in the spec §11; `solutions/` read-only, unchanged.

## Re-plan input (2026-09-12): adapter-first direction

- New owner input: an adapter-first investigation brief (187 lines). Investigation and planning only: no
  runtime code, no data migration, no Profile removal, no new sub-issues in this pass.
- Branch state re-verified: `OME-1138-converge-connections` was fast-forwarded by the owner
  on 2026-09-10 (reflog: `merge origin/main: Fast-forward`) from b47853ea to 17048f5d; no
  local commits; `origin/main` is at c1c92562 with no `apps/aigateway` changes after
  17048f5d. Not moved further (no rebase/merge without instruction). AIGateway delta
  b47853ea..17048f5d: 44807b63 (model-parameters datasheet without a connected profile),
  0ddcab94 (Tavily retrieval cache), 802bed9a (gateway_call_id); spec §2 anchors must be
  re-verified at 17048f5d.
- The AIGateway metamodel now lives in `screamingface-design` (branch
  `OME-1178-add-the-aigateway-metamodel`, HEAD 679aa8f, PR #18); the app-repo `solutions/`
  working copy is English v1 with the generator tooling (`_tools`, `_coverage`) that the
  design repo does not carry. Spec §11 (written against the Russian catalog) is stale.
- Established owner decisions restated by the new input: saved ProfileDefaults are to be
  removed in full (supersedes the earlier "migrate" recommendation); defaults behaviour is
  preserved until an explicit cutover; no defaults in Connections, slots, presets or jobs.
- Correction: the Admin UI DOES write defaults on API-key set/replace
  (`apps/aigateway-ui/src/app/actions.ts:170-209`, all six fields; the form exposes name,
  model, temperature, max_tokens). Spec §8.2 was wrong on this point.
- Linear update prepared for the re-plan; issue status and scope remain authoritative.
- Owner clarification (2026-09-12, in conversation): an adapter WILL be introduced; Profiles
  are NOT removed now; consumers reach Profiles only implicitly through the adapter; the
  later step is either a proper transfer to Connections and removal of Profiles, or a rework
  of Profiles into a "provider account" model. The backing model behind the adapter is
  therefore an explicit open decision, not a settled Connection-only target.

## Execution approval (2026-09-14)

- Owner approved the adapter-first plan: D7 re-approved (Stage 0 → A1 first; stop after A1 for
  review; A2–A4 and backing migration need new authorisation); D15 decided (explicit Engine
  mutability flag, Hosted `mutable=False`, Local `mutable=True`, refuse before I/O); D17 decided
  (`GET /v1/provider-access`, provider + status only, no `needs_reauth` from the Profile-backed
  implementation in the window, private/no-store, `X-Profile` non-selecting, golden equivalence at
  A3, Engine switch at A4). Recorded in OME-1138 (comment 235ac23d-f288-428e-8205-087650e4f2c7),
  spec §8 and plan §1.
- Sub-issues filed under OME-1138: `OME-1198` U0 gateway characterisation (In Progress),
  `OME-1199` U0e Engine characterisation (In Progress), `OME-1200` U1 port + Profile-backed
  implementation (Todo, blocked by OME-1198/OME-1199). Each has its own ledger and mirror dated
  2026-09-14.

## Planned changes (this unit — no runtime code)

- `docs/tasks/2026-09-09-OME-1138-converge-connections.md` — work-item mirror (status note).
- `docs/spec/2026-09-09-OME-1138-converge-connections.md` — adapter-first revision: problem and
  end state, boundary (two interfaces, opaque target, typed refusals, HTTP rendering table),
  before/after call paths, consumer migration table, staged sequence 0/A1–A4/B/C/D/E, conditions
  for switching the backing and retiring Profile APIs/selectors/storage/history, retained
  option-(a) mechanism (slot, E/B/C, R0–R4), decision register D1–D10 preserved + D11–D18 open,
  differences from the previous plan, risks, test matrix, metamodel.
- `docs/plan/2026-09-09-OME-1138-converge-connections.md` — stage status, unit decomposition for
  D7 re-approval (U0/U0e/U1–U4/U4e, then S1/S2'/S4 or B', S7, S11, S6, S8, S9, S12, S13),
  per-stage work with tests first, gates, branch/catalog notes, commands.
- No changes under `apps/`, `packages/`, `solutions/`, and no Linear mutation in this unit.

## Re-plan output (2026-09-13): adapter-first investigation and design

- Evidence produced (all read-only, at HEAD 17048f5d): gateway read paths, gateway write paths,
  Engine, UI/SDK/URL4, metamodel and tests/tooling were checked against the load-bearing claims
  (missing selector → default path; defaults before cache and cache hit bypasses credentials;
  keyless datasheet ≠ keyless chat; in-process vs queued ambient `AIGATEWAY_PROFILE`; Hosted vs
  Local listing). Follow-up review converged on the boundary written into spec §3.
- Follow-up reads the critique demanded were performed directly: slot naming
  (`credential_name_for` vs `credential_key_for`, strategy cache key and eviction by string),
  ProfileIndexStore fence lines, `GET /v1/auth/profiles` handler and DTO, access-control and
  Client product cards, `available_auth_modes()` ordering, the unguarded resolver index read,
  dead `compatibility_profile_name` and test-only `OAuthConnectionStore.complete()`, anthropic
  `keychain_account` configurability, and the `aigateway-ui`/`url4` diff against `origin/main`
  (empty).
- Review corrections are folded in: the test-coupling census (three by-path imports, one module-object
  scan, two `routes.chat` namespace patches that break at A2, one class-level patch) replaces the
  earlier "seven modules import by path"; the Profile-backed implementation is split into at least
  three modules because the relocated bodies exceed 450 lines; A2 re-expresses exactly two suites;
  the selector reject policy has one enforcement point (the parse step); the legacy defaults read
  is a composable component so backing switch and defaults cutover stay independent; A4 is two
  units under the epic. Additional corrections (concrete package layout, `UnsupportedAuthMode`
  raised by the auth-mode/authorize operations rather than `resolve`, shim rendering through the
  edge table, D16 options, Admin UI fieldset timing) are folded in.
- Owner review (2026-09-14) found three errors, each verified against 17048f5d and corrected:
  (1) the 25 `ProfileIndexStore` test files split by lifecycle into 18 feature seeders, 4
  storage-invariant suites (legacy store until E), 2 facade suites (HTTP contract kept through A3/B,
  storage-specific assertions split at B) and 1 bootstrap suite (re-targeted at B) — none of those 7
  is a shared-fixture candidate; (2) the availability aggregation lives only in the Engine
  decoder (`profile_availability.py:14-37`), the gateway listing is raw — A3 reproduces the Engine
  rule with a golden test; (3) two conflict contracts documented separately: CAS-retry exhaustion →
  503 `profile_index_conflict`, superseded publish (delete-wins) → 409 `profile_conflict`.
- Owner review (2026-09-14, second pass): the 18/7 split was right for the fixture question but too
  broad for the test lifecycle (spec §4, §5 and §6.1 said all 7 stay on the legacy store until E);
  refined to 18/4/2/1 as above. The prior checkpoint record was internally contradictory and was
  rewritten as one normalised record.
- Corrections applied to the spec: CAS-retry exhaustion is 503 `profile_index_conflict` (not 409), distinct from the 409 `profile_conflict` delete-wins contract; the Admin UI writes
  defaults with wholesale replacement; `/v1/models/admit` does not inject `default`; Engine local
  status mapping and dead `revoked` branch; +6-line anchor drift from 44807b63; catalog location
  and generator input revision 802bed9a; the resolver reads `X-Profile` at exactly three sites.
- `origin/main` advanced to c1c92562 during the pass (tracing OME-1132). Affected anchors:
  `routes/chat_dispatch.py` +1 line before the failure marker, `main.py` +5 lines before the
  conflict handler, Engine `runner/main.py:281` → `:283`. Branch not moved (no instruction).
- Conflicts presented, not resolved: D7 (first units were S1–S3; adapter-first makes Stage 0 and
  A1–A3 first and moves S1/S4 behind D11); spec-text §4.4 selector-less signature and §4.6
  Connection-shaped successors superseded as consumer contracts, retained as mechanism.
- New open decisions D11–D18 (backing model; selector semantics after cutover; approved protocol
  surface; dual OAuth write owner; hosted read-only rule; defaults source during transition;
  availability successor; admin HTTP successor).
- Checks actually run in this pass: none of the project gates (documentation-only unit; the
  2026-09-09 baseline stands); `git diff --stat 17048f5d origin/main` for the consumer paths;
  source inspection only. No live credential or data access, no migration,
  no deployment, no staging, no commit, no push, no catalog write.
- Linear: after re-authorisation on 2026-09-14 the issue was read in full (unchanged since
  2026-09-08: In Progress, High, `aigateway`, no sub-issues, blocks OME-1026/OME-1035) and updated:
  the section "Adapter-first revision (2026-09-14)" was appended to the description without
  rewriting the existing text (the Target/Done-when conflict with D11 is presented explicitly), and
  one comment (id 2dfa9fbd-70a1-4234-8806-46c8a40bbe19) records the verdict, that no sub-issues were
  created, the D7 re-approval request and the smallest next step. Status, labels, priority and
  relations untouched. The text below is the earlier compact proposal, superseded by the applied
  section.

### Proposed Linear update for OME-1138 (not applied)

Description addition (after the existing summary):

> **Adapter-first revision (2026-09-13).** The convergence proceeds through a provider-access
> boundary introduced first and backed by the existing Profile mechanisms; consumers move onto it
> while Profiles remain the only storage; the storage/authority transition happens later behind
> the same boundary. Profiles are not removed in this step. The final backing (transfer to
> Connections with the retained slot design, or a rework of Profiles into a provider-account
> model) is an open owner decision (D11). Saved ProfileDefaults are still removed in full at an
> explicit cutover (D2). Spec and plan: `docs/spec/2026-09-09-OME-1138-converge-connections.md`,
> `docs/plan/2026-09-09-OME-1138-converge-connections.md` (revision 2026-09-13).
>
> Staged sequence: 0 characterisation tests → A1 port + Profile-backed read implementation (no HTTP
> change) → A2 in-process consumers → A3 admin interface + management shells → A4 Hosted Engine on
> a backing-neutral availability listing → B backing transition (after D11, D14) → C defaults
> cutover → D selector sunset and carrier retirement → E retirement and cleanup.
>
> Owner decisions needed before code: re-approval of the first units (D7: Stage 0 + A1 instead of
> S1–S3), then D15/D17 before A4, D11/D14 before B, D16 before C, D12/D4 date before D, D13/M0 for
> the catalog, D18 for the admin successor.

Comment (same text as the description addition, plus): "No sub-issues were created in this pass;
the unit table in the plan is a proposal for D7 re-approval."

## Stage 0 + A1 execution (2026-09-14)

Executed under the owner's approval of 2026-09-14 (D7 order Stage 0 → A1; stop after A1). Work began
from 17048f5d on branch `OME-1138-converge-connections` in the shared checkout. Stage 0 committed as
`48fa1d78` and `c7d767f7`; A1 is committed with this ledger.

- **Stage 0 — `OME-1198` (gateway) and `OME-1199` (Engine):** characterisation tests only, green at
  HEAD with `apps/*/src` untouched and every existing test unedited. Details in their ledgers.
- **A1 — `OME-1200`:** new `apps/aigateway/src/aigateway/core/provider_access/` (nine modules, all
  ≤260 lines), `routes/provider_access_http.py` (the one refusal → HTTP table), `main.py` wiring of
  `app.state.provider_access`, and `routes/chat_credentials.py` / `routes/chat_profile_defaults.py`
  turned into shims that keep every name the routes import. Route call sites, schemas, stores,
  Engine and existing tests untouched; OpenAPI export byte-identical to HEAD (compared against a
  `git archive HEAD` copy, 78 065 bytes both sides). New suite: 130 tests across six modules,
  the port contract parameterised over an in-memory fake and the Profile-backed implementation.
- **Consumer gates run explicitly:** Engine gate ALL GREEN (no Engine change); `packages/url4`
  ALL GREEN; `packages/screamingface` ALL GREEN after `uv sync --extra notebook` (what CI does
  before pyright — the local venv lacked the extra, so the first run failed pyright on
  `ipywidgets` imports; environmental); `apps/aigateway-ui` lint + typecheck + `test:ci` green
  after `npm ci` (the first attempt ran from the wrong directory).
- **PostgreSQL lane:** 16 passed, 5 failed — all five in
  `tests/integration/test_cache_snapshot_upload_postgres.py`, failing on `pg_dump` exit 1 because the
  local `pg_dump` is 15.13 while the test pins `postgres:16-alpine`. Identical failures against the
  untouched HEAD export; pre-existing and unrelated to A1.
- **Known flake:** `tests/unit/auth/test_login.py::test_unknown_user_timing_close_to_wrong_password`
  failed once in the first full gate run (five lanes sharing the CPU) and 1 of 3 isolated reruns on
  the same tree; it is the bcrypt timing failure already recorded in the 2026-09-09 baseline.
- **Not started (per instruction):** A2–A4, any backing migration, the Hosted Engine switch.
- **A1 follow-up — `OME-1204` (2026-09-15):** the five provider-access package modules and the two
  test helpers renamed without the leading underscore (owner decision, spec §8 D19); rename-only —
  imports and the facade updated, every export unchanged, OpenAPI byte-identical against `837ab5b6`,
  a filename-policy test added. Ledger `docs/work/2026-09-15-OME-1204-rename-provider-access-modules.md`.

## Test plan

- P0: record existing gate results for aigateway and the meta tool checks (baseline only,
  no test edits).
- P1: enumerate the RED tests per invariant in the spec test matrix; they land with the
  P2 sub-issue, not here.

## Acceptance

- G0: scope, checkout and repo delta verified; unknowns (Q01–Q07) listed, not guessed.
- P1 deliverables exist and are internally consistent with I01–I14; owner decisions are
  stated as questions with options, not assumed.
- G1 remains open until the owner approves the contract/policies and sub-issues are filed.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `docs/spec/2026-09-09-OME-1138-converge-connections.md` (rewritten in place,
  adapter-first), `docs/plan/2026-09-09-OME-1138-converge-connections.md` (rewritten in place),
  `docs/tasks/2026-09-09-OME-1138-converge-connections.md` (status note), this ledger. All four
  are committed with the OME-1200 feature unit; the P1 design pass itself changed nothing under
  `apps/`, `packages/` or `solutions/`.
- **Commit:** documentation included in `feat(aigateway): introduce provider access port`.
- **Gates:** not run in this documentation-only pass; baseline of 2026-09-09 stands (aigateway
  4104 passed / 58 skipped / 92.53 %, one pre-existing bcrypt timing failure; engine 2673 passed).
- **Deviations:** first units reordered (D7 conflict presented for re-approval); `origin/main`
  moved to c1c92562 during the pass and the branch was deliberately not moved; the Linear update
  was applied on 2026-09-14 after re-authorisation; the unit
  stays `in_progress` while A2 and later stages await separate approval.
