---
ticket: OME-1616
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-15
finished:
---

# arc-agi-timeouts-30m — raise the model-call budget to 30 minutes

## Intent

ARC-AGI-2 runs on prod stop at 10 minutes on a single model call. Three budgets sit in a row and
the smallest wins: the Engine's `[aigateway] timeout_s` (sent to the gateway as
`x-aigw-execution-timeout-s`), the gateway cap `AIGW_PROVIDER_EXECUTION_TIMEOUT_S` (the gateway
takes the smaller of the header and the cap), and LiteLLM's own HTTP timeout, which falls back to
600 s when neither a call `timeout` nor `REQUEST_TIMEOUT` is set. All three move to 1800 s through
configuration only; no gateway code changes.

## Planned changes

- `apps/screamingface-engine/url4.toml`: `[aigateway] timeout_s` 600 → 1800 (baked into the
  Runner image; queue wait and HTTP read timeout follow it).
- `apps/aigateway/charts/aigateway/values.yaml` and `values-prod.yaml`: `extraEnv` gains
  `AIGW_PROVIDER_EXECUTION_TIMEOUT_S=1800` and `REQUEST_TIMEOUT=1800`. Both files, because Helm
  replaces a list wholesale and `values-prod.yaml` sets its own `extraEnv`.
- `values.yaml`: the `providerQueueTimeoutS` comment's "600s" becomes 1800s.
- `.github/scripts/verify_chart_wiring.py`: the default and prod renders carry both variables.
- Engine unit test: the shipped `url4.toml` budget is 1800.

## Test plan

- Chart check: default render and `values-prod.yaml` render both put
  `AIGW_PROVIDER_EXECUTION_TIMEOUT_S=1800` and `REQUEST_TIMEOUT=1800` in the gateway container.
- Engine: the shipped `url4.toml` resolves `timeout_s == 1800` and a transport timeout above it.

## Acceptance

- `charts.yml` checks and the Engine and aigateway gates green.
- After deploy, a model call longer than 10 minutes completes on prod.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the `docs/tasks` mirror.
- **Commits:** see the PR.
- **Gates:** `run_gates.py screamingface-engine` and `run_gates.py repo` all green;
  `verify_chart_wiring.py` passes (the four new checks failed before the values change);
  `helm lint` with `values-prod.yaml` clean. No aigateway code changed.
- **Deviations:** no spec or plan for a three-value configuration change. After deploy, the
  Engine change needs a new Runner image; the gateway change needs a chart rollout.
