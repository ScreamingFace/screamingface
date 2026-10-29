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
- New test modules `packages/screamingface/tests/test_connection_copy.py` and
  `packages/screamingface/tests/e2e/test_capture_proxy_headers.py` (beside the fixture it imports).
- `.claude/test-change-approvals/OME-N.json`, `docs/tasks/2026-10-29-OME-N-sdk-connection-copy.md`
  at PR-open.
- Added by the scope extension from the owner's close-out review (docstrings and comments only):
  `src/screamingface/models.py` (`sf.models.get`), `src/screamingface/discovery.py`
  (`ModelParameter`, `ModelCapability`, `ModelDetails` and the `__repr__` comment),
  `src/screamingface/_ui/cards.py` (`model_details_card_html`) and the `_validate_parameter`
  docstring in `src/screamingface/_evaluation/model_parameters.py`.

## Test plan

- RED: the preflight `provider_not_connected` hint names `sf.connect()`, says to connect the
  provider, addresses the hosted Engine case, and never says "profile" (sync and async evaluate).
- RED: a relayed `model_not_found` detail raises `PlanningError` whose message names the Model and
  never says "profile" or "selected" (sync and async `models.get`).
- RED: the R3 decoder still renders `profile_not_found` with its relayed name (guard that the
  retained branch is untouched).
- RED: the e2e capture proxy, run against a loopback recorder, forwards `Content-Type` and
  `Accept` but not `X-Profile`.
- RED: the `help()` docstrings of `Client.models.get`, `AsyncClient.models.get`, `sf.models.get`,
  `sf.ModelDetails`, `sf.ModelParameter` and `sf.ModelCapability` say "Connection-specific" and
  never "profile".

## Acceptance

- `git grep -n -i "provider profile\|profile-specific\|profile-bound\|profile fields" --
  packages/screamingface ':!packages/screamingface/tests/test_connection_copy.py'` finds nothing
  (the excluded module is the test that pins their absence).
- `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` appears nowhere in `packages/screamingface`.
- `x-profile` is not in the capture proxy's forwarded-header allowlist.
- `uv run .claude/scripts/run_gates.py screamingface` green; every changed prior test is in the
  manifest.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1779.json` and
  `docs/tasks/2026-10-29-OME-1779-sdk-connection-copy.md`.
- **Final copy:**
  - preflight hint: "Open sf.connect() to connect the provider, or ask the operator of your hosted
    Engine to connect it in AI Gateway, then retry." A hosted Engine lists provider access
    read-only (D15); an operator sets an account's Connection through the gateway's admin routes.
  - `model_not_found`: "AI Gateway does not list Model '<id>'". The gateway answers this code from
    what it lists (seeded, admitted, cached live listing) before any credential read, and a
    degraded live listing gives the same 404, so the message states what AI Gateway lists rather
    than what the provider serves. It agrees with the Engine's own 404 description ("AI Gateway
    does not know the model").
  - Model discovery docstrings, the card docstring and README: "Connection-specific".
- **Commits:** `fix(screamingface): describe Connections in the SDK's messages`, then
  `fix(screamingface): reword the Model discovery docstrings and the 404 message`.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface --base origin/main` (the merge
  base, `a7e5d8577`) — ALL GATES GREEN: append-only (2 approved OME-1779 transitions), ruff check,
  ruff format, pyright, pytest (4949 passed, 38 skipped; coverage 97.06%), notebooks, build, distribution.
  `check_mirror_status.py` passes.
- **Review:** two independent read-only reviews of the diff. Applied: the `model_not_found`
  wording; README:1206 uses the hint's own words; the four public "profile-specific" docstrings;
  the proxy test records the forwarded body and its INVARIANT states the allowlist; the
  `# quiet` comment is gone; the CHANGELOG line names only the messages this PR changes. Checked
  and kept: the proxy test's claim that every nonblank `X-Profile` is a 400
  `x_profile_unsupported` holds on `origin/main` (`routes/chat.py:477` calls
  `selector_from_request`; `main.py:424` sets `REJECT_EXPLICIT`).
- **R3 decoder:** no new guard test. The existing
  `tests/test_model_parameter_discovery.py::test_models_get_explains_a_missing_provider_profile`
  pins the rendered message ("Codex profile 'default' is not connected"), the code and the hint,
  and the diff leaves that branch untouched.
- **Follow-up (deferred, needs the owner's approval as further prior-test edits):**
  `_CaptureProxy` in `tests/e2e/fixtures/slice_snapshot.py` takes its port with bind-then-release
  `free_port()` (a small race under xdist, now reachable in the default lane) and its
  `shutdown()` never calls `server_close()`.
- **Deviations:**
  - Scope extended by the owner's close-out review: the public docstrings at
    `src/screamingface/models.py:18` and `src/screamingface/discovery.py:99,145,165`, the
    `discovery.py:222` comment, `_ui/cards.py:358` and the `_validate_parameter` docstring in
    `_evaluation/model_parameters.py`. They are in the unit's intent, though spec §4.8's line list
    missed them. In the card and `_validate_parameter` docstrings "profile" meant the contract's
    account context, so both now say Connection-specific.
  - The planned R3 guard test was not added (see above).
  - Two review decisions conflicted. For the `model_not_found` wording, the later decision's
    exact string ("AI Gateway does not list Model '<id>'") was used, not the variant ending "for
    its provider". The `free_port()` / `server_close()` fix was deferred per the later decision,
    not applied.
