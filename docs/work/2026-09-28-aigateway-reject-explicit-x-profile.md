---
ticket: OME-1394
stack: aigateway
status: done
started: 2026-09-28
finished: 2026-09-28
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
- Selector-less behavior is unchanged.
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
  that approved list. The pinned Spark worker was unavailable for this account, so a bounded
  general implementation agent made the same production-only GREEN change. No deployment or
  production access occurred; merge/deployment remains gated on the alpha drain proof.
