---
ticket: OME-1779
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-29
finished:
---

# sdk-connection-copy — the Client SDK speaks of Connections, not provider profiles

## Intent

OME-1138 close-out leaf L8 (findings X2, X4, X5, OPS-5, P-F9). Stage D made provider access
selector-less (D12) and D20 made Connection the product noun, but the Client SDK still tells
users about a "selected provider profile": in the live evaluate preflight hint, in the
`model_not_found` catalogue message and in the README. The SDK also keeps a runtime comment and a
test rationale about `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE`, a variable the gateway no longer
reads for anything but a retirement warning, and the e2e capture proxy still forwards the retired
`X-Profile` header. This unit rewrites that copy in Connection terms and removes the leftovers.
The R3 decoder for the retained wire codes (`_engine/catalog.py`, the `profile_not_found` /
`profile_pending_auth` / `auth_required` branch) stays as it is.

Spec: `docs/spec/2026-10-29-ome-1138-closeout.md` §4.8, §6, §8.
Plan: `docs/plan/2026-10-29-ome-1138-closeout.md` §2 and §3 "L8".

## Planned changes

- `packages/screamingface/src/screamingface/_evaluation/model_parameters.py` — the
  `provider_not_connected` preflight hint in Connection terms.
- `packages/screamingface/src/screamingface/_engine/catalog.py` — the `model_not_found` message
  and the two "profile-specific" `get` docstrings.
- `packages/screamingface/src/screamingface/_runtime/bootstrap.py` — remove the
  `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` comment.
- `packages/screamingface/README.md` — the preflight paragraph and the `ModelDetails` sentence.
- `packages/screamingface/CHANGELOG.md` — one Unreleased line.
- `packages/screamingface/tests/test_runtime_cli.py` — drop the rationale and the absence
  assertion for the variable nothing reads (prior test; manifest).
- `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` — the capture proxy stops
  forwarding `x-profile` (prior test file; manifest).
- New test module `packages/screamingface/tests/test_connection_copy.py`.
- `.claude/test-change-approvals/OME-N.json`, `docs/tasks/2026-10-29-OME-N-sdk-connection-copy.md`
  at PR-open.

## Test plan

- RED: the preflight `provider_not_connected` hint names `sf.connect()`, says to connect the
  provider, addresses the hosted Engine case, and never says "profile" (sync and async evaluate).
- RED: a relayed `model_not_found` detail raises `PlanningError` whose message names the Model and
  never says "profile" or "selected" (sync and async `models.get`).
- RED: the R3 decoder still renders `profile_not_found` with its relayed name (guard that the
  retained branch is untouched).
- RED: the e2e capture proxy, run against a loopback recorder, forwards `Content-Type` and
  `Accept` but not `X-Profile`.
- The `Models.get` / `AsyncModels.get` docstrings carry no "profile" wording.

## Acceptance

- `git grep -n -i "provider profile"` over `packages/screamingface` finds only the new test that
  pins its absence.
- `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` appears nowhere in `packages/screamingface`.
- `x-profile` is not in the capture proxy's forwarded-header allowlist.
- `uv run .claude/scripts/run_gates.py screamingface` green; every changed prior test is in the
  manifest.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `packages/screamingface/tests/e2e/test_capture_proxy_headers.py`
  (the capture-proxy test lives beside the fixture so it can import it),
  `.claude/test-change-approvals/OME-1779.json` and
  `docs/tasks/2026-10-29-OME-1779-sdk-connection-copy.md`.
- **Final copy:**
  - preflight hint: "Open sf.connect() to connect the provider, or ask the operator of your hosted
    Engine to connect it in AI Gateway, then retry." A hosted Engine lists provider access
    read-only (D15); an operator sets an account's Connection through the gateway's admin routes.
  - `model_not_found`: "Model '<id>' is not in AI Gateway's catalogue". The gateway answers it
    from its own catalogue (seeded, admitted, cached live listing) before any credential read, so
    the message names that catalogue rather than the provider.
  - `Models.get` / `AsyncModels.get` docstrings and README: "Connection-specific".
- **Commits:** `fix(screamingface): describe Connections in the SDK's messages` (one commit; the
  sha is in the PR and the close comment).
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface --base origin/main` — ALL GATES
  GREEN: append-only (2 approved OME-1779 transitions), ruff check, ruff format, pyright, pytest
  (4945 passed, 38 skipped; coverage 97.06%), notebooks, build, distribution.
  `check_mirror_status.py` passes.
- **Review:** independent read-only review of the diff. Fixed from it: the `model_not_found`
  message first read "is not available from its provider", which blames the provider when live
  discovery is degraded; README:1206 now uses the hint's own words; the proxy test's INVARIANT
  states the allowlist. Not changed (outside spec §4.8, returned as a question): the public
  docstrings still saying "profile-specific" at `src/screamingface/models.py:18` (`sf.models.get`)
  and `src/screamingface/discovery.py:99,145,165` (`ModelDetails` and its row types), plus the
  private "profile-bound" / "profile fields" docstrings at
  `src/screamingface/_evaluation/model_parameters.py` (`_validate_parameter`) and
  `src/screamingface/_ui/cards.py:358`. Noted, not changed: `_CaptureProxy` takes its port with
  bind-then-release `free_port()`, a small pre-existing race now reachable in the default lane.
- **Deviations:** the planned R3 guard test was not added; the retained decoder is already pinned
  by `tests/test_model_parameter_discovery.py::test_models_get_explains_a_missing_provider_profile`
  (message, code, hint), and the diff leaves that branch untouched.
