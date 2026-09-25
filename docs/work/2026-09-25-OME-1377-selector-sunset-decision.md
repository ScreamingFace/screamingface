---
ticket: OME-1377
stack: repo
status: in_progress
started: 2026-09-25
finished:
---

# OME-1377-selector-sunset-decision — decide the Profile selector sunset and record it

## Intent

Stage D of `OME-1138` retires `X-Profile`, `AIGATEWAY_PROFILE` and `JobRunner.schedule(profile=...)`
as ways to choose a credential, without silently ignoring or retargeting a selector and without
breaking work accepted before the cutover. This unit records the owner's contract, rollout and
catalog decisions in the tracked spec and plan, and gates everything else on the Stage D metamodel
landing (`OME-1380`). It changes no runtime code.

## Preflight (2026-09-25)

- App `origin/main` `b8478c50`; Stage C merged as `e8c7d262` (PR #1061).
- Design `origin/main` `1de95b5` (PR #24) has no Stage D target: `REJECT_EXPLICIT` is described as
  declared and unused (`component/provider-access` v5, draft).
- Verified seam at `b8478c50`: `core/provider_access/selector.py:39-49` (`from_header`, both
  policies); readers `routes/chat.py:279`, `routes/model_admission.py:115`,
  `routes/model_parameters.py:115` (`Vary: Authorization, X-Profile` at :74); availability accepts
  the header as non-selecting. Engine: `rest/routes.py:506-556` → `schedule(profile=)` →
  `adapters/inprocess.py:185-187` (pops ambient) or `runner_queue.py:231` (field only when present)
  → `runner/main.py:94` → `world/connector.py`; also `rest/catalog.py:117,174` (`Vary` at :46),
  `rest/connections.py:149`, `request_scope.py:162`.
- Findings that shaped the decisions:
  - the dormant 400 rendering (`routes/provider_access_http.py:129-133`) echoes `requested_label`;
  - `409 connection_ambiguous` (`routes/provider_access_http.py:31-33`, raised at
    `core/provider_access/profile_backed.py:196-213`) tells the caller to set `X-Profile`;
  - Engine logs the raw profile label when it schedules a run (`rest/routes.py:225`);
  - the spec's D13 row named `completions` v6; design `main` has v7;
  - the SDK never sends `X-Profile` and maps only `profile_not_found`, `profile_pending_auth` and
    `auth_required` (`packages/screamingface/src/screamingface/_engine/catalog.py:284-295`).
- No production or dev data was read.

## Decisions (owner, 2026-09-25)

- **D12:** absent/blank/whitespace are selector-less; every nonblank value, literal `default`
  included, gets non-retryable 400 `{code: x_profile_unsupported, message}` without the value;
  scope is gateway chat, model parameters, admission and provider-access availability plus Engine
  execution, catalog, model parameters and connections; pairs with several active Connections keep
  their 409 with a message that no longer suggests `X-Profile`; no replacement selector; no code
  renames in Stage D.
- **D4 rollout:** two-phase drain — Engine producer-off, drain proof, then the gateway reject;
  rollback floor is the producer-off Engine build.
- **D13/M0:** version bump of the existing catalog cards with a "Stage D target, not live"
  section; `supersedes`/`deprecated` only at Stage E.
- Design landing filed as its own issue (`OME-1380`); decisions recorded on `OME-1377` and here.

## Planned changes

- `docs/spec/2026-09-09-OME-1138-converge-connections.md` — §3.6 sunset paragraph, §8 D4/D12/D13
  rows and intro, §10 multi-Connection risk, §12 `completions` version; `updated: 2026-09-25`.
- `docs/plan/2026-09-09-OME-1138-converge-connections.md` — stage rows C (merged) and D (decided),
  S13 row, D13/M0 gate; `updated: 2026-09-25`.
- `docs/tasks/2026-09-25-OME-1377-selector-sunset-decision.md` and
  `docs/tasks/2026-09-25-OME-1380-stage-d-metamodel-target.md` — mirrors.
- This ledger.
- Design repository (`OME-1380`, its own branch and PR): the eleven catalog cards and the catalog
  README listed in the `OME-1380` mirror.

## Test plan

- Docs only; no tests. Check: every edited anchor still matches `origin/main` source, and the spec,
  plan, Linear `OME-1377` comment and `OME-1380` body state the same contract.

## Acceptance

- One unambiguous selector contract and rollout are recorded in Linear and the tracked spec/plan.
- The `OME-1380` metamodel merge commit is recorded here and on `OME-1377` before any census or
  runtime landing is filed.
- Still open after this unit: evidence window and sunset date (after the census), production
  evidence access (`OME-1333`), the remaining landings (census, Engine producer-off, gateway
  reject, URL4, Engine consumer cleanup).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — the spec, the plan, the two `docs/tasks/` mirrors and this
  ledger. Design repository (`OME-1380`): the eleven catalog cards and the catalog README.
- **Metamodel merge (acceptance):** screamingface-design PR #25, merge commit
  `3ba6a3df808f705f4f71390c900302a5c26c0d63` on design `main` (2026-09-25); its tree is identical
  to the reviewed commit `0e071dd`. Recorded on `OME-1377`; `OME-1380` closed.
- **Commits:** design `0e071dd` — `docs(catalog): describe the Stage D selector sunset target`
  (merged as `3ba6a3d`). App: this docs commit, `Refs: OME-1377` in the PR body.
- **Gates:** docs-only. Design catalog check (metaframework 0.5.1): 0 errors, 3 warnings, the same
  as design `main` `1de95b5`; `--since origin/main` reports 11 entities changed, each
  version-bumped.
- **Deviations:** `environment/aigateway-mesh` and `protocol/http-api` were in the expected card set
  but needed no change. `protocol/provider-credential-admin` had promised to drop `legacy_name` in
  Stage D; its target section now keeps it until D18/Stage E. Solution `completions` still says
  saved defaults are read before the cache lookup — stale since Stage C, left for a later catalog
  refresh.
