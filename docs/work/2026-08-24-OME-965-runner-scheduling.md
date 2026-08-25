---
ticket: OME-965
stack: screamingface-engine
status: done
started: 2026-08-24
finished: 2026-08-24
---

# OME-965 — apply Engine scheduling to Runner Jobs

## Intent

Pass deployment-owned node selectors and tolerations into every Kubernetes
Runner Job. This closes the Preview scheduling failure without hardcoding
platform policy in tenant code.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/config.py`
- `apps/screamingface-engine/src/screamingface_engine/adapters/factory.py`
- `apps/screamingface-engine/src/screamingface_engine/adapters/k8s.py`
- `apps/screamingface-engine/deploy/helm/templates/configmap.yaml`
- `apps/screamingface-engine/deploy/helm/values.yaml`
- `apps/screamingface-engine/deploy/helm/README.md`
- `apps/screamingface-engine/tests/unit/test_runners_k8s.py`
- `apps/screamingface-engine/tests/unit/test_runners_factory.py`
- `apps/screamingface-engine/tests/unit/test_deploy_time_chart_contract.py`
- task, specification, plan, and work records for `OME-965`

## Test plan

- Prove configured node selectors and tolerations reach the Runner Pod.
- Prove empty scheduling settings omit both fields.
- Prove the factory passes both settings to the adapter.
- Prove Helm renders both values as JSON settings.
- Run the complete ScreamingFace Engine gate suite.

## Acceptance

- Preview Runner Jobs pass required scheduling fields to Kubernetes.
- Environment-neutral deployments keep their current Job shape.
- No prior test changes or security weakening occur.

## Outcome

- **Actual files:** all planned files, plus `deploy/helm/values.yaml` to repair the existing
  disabled-NATS schema default that blocked Helm rendering
- **Commits:** this change — `fix(engine): apply scheduling to Runner Jobs`
- **Gates:** focused suite: 55 passed; complete `screamingface-engine` gate: all green
- **Deviations:** the full gate exposed a pre-existing `nats.fullnameOverride: null` render
  failure. The chart now supplies the empty string required by its existing schema.
