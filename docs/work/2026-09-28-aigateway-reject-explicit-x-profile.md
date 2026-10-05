---
ticket: OME-1394
stack: aigateway
status: done
started: 2026-09-28
finished: 2026-10-01
---

# aigateway-reject-explicit-x-profile — reject obsolete credential selectors

## Intent

Complete the offline AIGateway half of the accepted OME-1138 Stage D selector sunset. Once the
separately gated alpha drain is proven, AIGateway will reject every explicit `X-Profile` without
echoing or logging its value, while selector-less requests continue resolving the account/provider
pair's one effective Connection.

## Planned changes

- Add a focused Stage D route test module under `apps/aigateway/tests/unit/`.
- Activate the existing `SelectorPolicy.REJECT_EXPLICIT` at chat, model-parameters,
  model-admission, and provider-access availability boundaries.
- Make `x_profile_unsupported` rendering value-free and update `connection_ambiguous` guidance.
- Remove the retired selector dimension from relevant `Vary` headers.
- Add `docs/tasks/2026-09-28-OME-1394-aigateway-reject-explicit-x-profile.md`.
- Do not modify prior tests without an explicit, exact Confidence-Gate approval.

## Test plan

- RED: prove nonblank named and literal-default selectors reach the old behavior on each in-scope
  route, then prove the desired 400/value-free/no-I/O contract after implementation.
- Cover absent, empty, and whitespace-only boundaries, including chat streaming.
- Assert the rejected value appears in neither response nor captured logs.
- Assert `connection_ambiguous` remains 409 without selector advice.
- Assert private cache policy and post-sunset `Vary` on both success and error paths.
- Run focused affected suites, `git diff --check`, and the full AIGateway gate.

## Acceptance

- Every explicit selector is refused before credential, discovery, admission, cache, or dispatch I/O.
- Selector-less behavior is unchanged except for the owner-approved multi-Connection ambiguity
  tightening recorded in Stage D D12.
- Responses, logs, and telemetry disclose no selector value.
- Ambiguity remains explicit and actionable without a replacement selector.
- Full AIGateway gates are green, or the only remaining red is an exact prior-test list awaiting
  owner approval under the append-only rule.
- No deployment, production access, migration, dependency, URL4, Engine, SDK, D18, or Stage E work.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** five AIGateway route modules; one new Stage D test module; 16
  owner-approved prior-test re-pins; this ledger; and the OME-1394 task mirror.
- **Commits:** this commit — `feat(aigateway): reject explicit profile selectors`
- **Gates:** RED `14 failed, 4 passed`; focused GREEN `18 passed`; approved affected suites
  `234 passed`; `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` — ALL GATES
  GREEN (Ruff, format, Pyright, no-enterprise, full pytest coverage >=80); `git diff --check`
  clean.
- **Deviations:** the exact 16-file prior-test re-pin was approved after the unchanged old suite
  reported `70 failed, 4901 passed, 52 skipped, 37 deselected`; append-only was skipped only for
  that approved list. No deployment or production access occurred; at this checkpoint,
  merge/deployment remained gated on the alpha drain proof.

## Review follow-up

### Planned changes

- Reject a nonblank value in any repeated `X-Profile` header field through one authenticated edge
  helper whose policy is configured at the composition root.
- Keep every selector value out of the refusal exception as well as its HTTP rendering.
- Make selector-less resolution return `409 connection_ambiguous` whenever two or more active
  Connections exist, including when one is labelled `default`.
- Add mutation-resistant coverage for pre-cache refusal and target-local dispatch invalidation.
- Refresh current README, task-mirror metadata, and opt-in live suites for selector-less calls.

### Test plan

- RED: duplicate `X-Profile` values with blank first; default-labelled multi-Connection pair;
  cache lookup moved before refusal; and dispatch failure applied to every Connection.
- Cover absent/blank values across all four route families and preserve auth-before-selector order.
- Run focused selector/provider-access/live collection checks and the complete AIGateway gate.

### Acceptance

- Every present nonblank header value is refused before cache, catalog, resolve, or dispatch work.
- Authentication still returns `401` before selector refusal.
- Multi-Connection pairs never auto-select a literal `default` label.
- A dispatch failure mutates only its resolved target.
- No exception, response, log, or telemetry retains the rejected selector value.

### Outcome

- **Actual files:** selector parser/refusal types, Profile-backed resolution and its fake, the
  composition root, five HTTP route modules, six focused unit/contract test modules, five opt-in
  live suites, the AIGateway README, task mirror, and this ledger.
- **Commits:** this follow-up commit — `fix(aigateway)!: harden selector sunset boundary`.
- **Gates:** RED `11 failed, 127 passed`; focused GREEN `138 passed`; expanded affected suites
  `276 passed`; credential-free live check `37 skipped`; three final runs of
  `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` — ALL GATES GREEN (Ruff,
  format, Pyright, no-enterprise, full pytest coverage >=80); `git diff --check` clean.
- **Deviations:** owner-approved review corrections update prior selector/live tests, so the
  append-only precheck is skipped for that reviewed set. Real live provider calls were not run
  because credentials are absent. No deployment or production access occurred; at this checkpoint,
  merge remained blocked on the alpha drain proof.

## Decision and rollout clarification

### Planned changes

- Record that Stage B label selection was window-only and Stage D intentionally returns `409` for
  every selector-less pair with multiple active Connections, including `[default, backup]`.
- Add a privacy-safe count of affected unmigrated pairs to the pre-merge drain gate without
  authorising or performing the production read.
- Record the deliberate absence of `_aigw` accounting on pre-body selector refusals and the exact
  breaking PR title/body requirement.
- Strengthen the blank-header matrix and remove test helpers that still imply label selection.
- Track stale AIGateway UI copy, generated schema, and identity diagrams separately in `OME-1398`.

### Acceptance

- Spec, mirror, ledger and future PR metadata describe the same breaking cohort.
- A `500` cannot satisfy the blank-header matrix, and test inputs remain valid HTTP field values.
- The rollout gate names the required aggregate evidence and its separate authorisation boundary.
- Runtime behavior remains unchanged from commit `8e60d435`.

### Outcome

- **Actual files:** AIGateway selector parsing and refusal rendering, chat/model-parameters/
  admission/provider-access route boundaries, ambiguity behavior, focused unit/live tests, the
  Stage D specification, OME-1394 task mirror and this ledger.
- **Decision record:** Linear comment `d5148392-6578-4889-a6c2-3b100c135f77` records the owner
  clarification, breaking PR metadata, accounting decision, rollout census, and production-read
  boundary. UI copy, generated schema, and diagrams are tracked in `OME-1398`.
- **Gates:** focused tests and the complete AIGateway gate passed; PR checks passed for Python 3.12
  and 3.13, replay, CodeQL and image planning. `git diff --check` was clean.
- **Deviations:** prior contract assertions were re-pinned under the recorded owner approval. No
  production read or deployment occurred.

## Activation waiver

- **Decision:** on 2026-09-29 the owner accepted the residual fail-closed risk and waived the
  pre-merge alpha drain proof and multi-active/default-label census. No production or cluster read
  was performed and no zero-count claim is made.
- **Disposition:** `OME-1401` was canceled as waived and its `blockedBy` relation was removed from
  `OME-1394`; PR #1114 may proceed through normal review and CI.
- **Rollback:** treat alpha as the canary; an unexpected increase in `400 x_profile_unsupported` or
  `409 connection_ambiguous` restores Gateway selector honoring while Engine remains producer-off.

## Merge closure

- PR #1114 merged to `main` on 2026-09-30 as `3083640b6be5d67b909d93643c6878d5fe67e318`.
- `OME-1394` is complete. Stale UI/schema/diagram guidance remains in `OME-1398`; URL4/Engine
  compatibility-carrier cleanup, D18 and Stage E remain separate work under `OME-1138`.
