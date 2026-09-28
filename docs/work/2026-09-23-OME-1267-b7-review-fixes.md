---
ticket: OME-1267
stack: screamingface-engine
status: done
started: 2026-09-23
finished: 2026-09-23
---

# OME-1267 — B7: whole-PR code review fixes (FX-91..FX-94)

## Intent

A `/code-review` of the whole PR #1030 found four issues. This batch fixes all four. The
owner chose the fix for FX-91: warn only (no render refusal).

- **FX-91 (medium):** with no `artifactSigning.existingSecret` or `signingKey`, an offline
  render (GitOps) makes a new random signing key on each sync. The pod checksum is fixed, so
  pods do not restart, and pods that start at different times can hold different keys. Then
  signed `303` URLs fail with 401. The README warns about this, but the render does not, and
  the `_helpers.tpl` and `deployment*.yaml` comments say the fixed checksum is safe.
- **FX-92 (low):** the node tier's `/healthz` has no `config_digest`. The spec (erd.md §2,
  contracts.md C2) puts it on both tiers, so an operator can see App/node config drift during
  a rollout. Only the App reports it.
- **FX-93 (low):** the App Deployment writes `podLabels` without removing the chart-owned
  keys. A `podLabels` `app.kubernetes.io/component` gives a duplicate mapping key. The node
  template already uses `omit`.
- **FX-94 (low):** `check_layering.py` records the imported NAMES as submodules only for
  `from screamingface_engine import X`. So `from screamingface_engine.world import serving`
  (and the relative `from ..world import serving`) gets past the runner/`world.serving` rule.
  The same hole applies to the `adapters.factory` rule.

## Planned changes

- FX-91: `deploy/helm/templates/NOTES.txt` (warning block), `deploy/helm/templates/_helpers.tpl`,
  `deploy/helm/templates/deployment.yaml`, `deploy/helm/templates/deployment-node.yaml`
  (correct the comments).
- FX-92: `world/config.py` (public `config_file_digest(env)`), `rest/forwarder.py` (use it),
  `world/node_tier/build.py` (compute it), `world/node_tier/tier.py` (`config_digest` param,
  `/healthz` body).
- FX-93: `deploy/helm/templates/deployment.yaml` (`omit` name/instance/component).
- FX-94: `.claude/scripts/check_layering.py` (`record(module.alias)` for every from-import).
- `apps/screamingface-engine/docs/plans/04-review-fixes.md` (B7 row).

## Test plan

New files only (append-only):

- `tests/unit/test_chart_signing_key_warning.py`: `helm install --dry-run=client` NOTES has the
  warning with no key; no warning with `existingSecret`, with `signingKey`, or with the node off.
- `tests/unit/test_node_healthz_config_digest.py`: a tier built from a real config file
  reports the file's sha256 on `/healthz` (a literal from `hashlib` of the written bytes);
  an unreadable config path omits the field; App and node digest of one file are equal.
- `tests/unit/test_chart_app_pod_labels_omit.py`: render with
  `podLabels.app\.kubernetes\.io/component=other` → the raw App pod template has the key once,
  and its value is `control-plane`; an unrelated `podLabels` key still renders.
- `tests/unit/test_layering_from_import_submodules.py`: synthetic trees — absolute
  `from screamingface_engine.world import serving` in `runner/` fails; relative
  `from ..world import serving` fails; `from screamingface_engine.adapters import factory` in
  `runner/` fails; `from screamingface_engine.world import build_world` still passes.

Each test must fail on today's code for the reason it names (RED observed, then a mutation
check).

## Acceptance

- `uv run .claude/scripts/run_gates.py screamingface-engine` green (append-only check included:
  no existing test edited).
- `python3 .github/scripts/verify_chart_wiring.py` green.
- Default render of the chart unchanged except NOTES.txt.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `deploy/helm/templates/secret-artifact-signing.yaml`
  (warning comment in the rendered Secret), `deploy/helm/values.yaml` (GitOps line),
  `deploy/helm/README.md` (drop Flux), and `apps/screamingface-engine/README.md` (the
  `config_digest` section now says both tiers report it). New tests: the four planned files.
- **Commits:** one per fix on `OME-1267-sync-surface-node-tier`, in the order FX-94, FX-92,
  FX-93, FX-91. This ledger and the `04-review-fixes.md` B7 section ride with FX-91. Not pushed.
- **Gates:** `run_gates.py screamingface-engine` ALL GATES GREEN, append-only check included
  (no existing test edited). `verify_chart_wiring.py` 159/159. `check_layering.py` OK on the
  real tree. Parsed chart render equal to HEAD for the default values and for node + S3, except
  the checksums of randomly generated Secrets, which differ on every render (HEAD too).
  `values-cloud.yaml` alone does not render on HEAD or here (it needs more values).
- **Reviews:** one design review: ACCEPT-WITH-FIXES, no structural finding. All three FIX items
  and the useful NITs are applied (see Deviations).
- **Deviations:**
  - FX-91: NOTES.txt alone was not enough. `helm template` (ArgoCD's path) never prints NOTES,
    so the warning also goes into the rendered Secret as a YAML comment, and into
    `values.yaml`. Flux is removed from the "offline render" list: its helm-controller runs a
    real install/upgrade, so `lookup` works there.
  - FX-93 also omits `name` and `instance`. Their duplicates were already on `main`; the fix is
    the same line, and it matches the node template.
  - FX-94 is wider than the finding: relative imports and the `adapters.factory` rule had the
    same hole. The trade-off: a non-submodule name that matches a forbidden two-part rule is
    now flagged (the safe direction for a boundary gate).
  - Some new tests pass on the old code too (guards, not RED):
    `test_an_unreadable_config_file_omits_the_digest`,
    `test_a_runner_module_importing_other_world_names_still_passes`,
    `test_an_unrelated_pod_label_still_renders`, and the "no warning" cases in
    `test_chart_signing_key_warning.py`. Each fails under a named mutation (always write the
    digest; flag every world import; drop all `podLabels`; warn unconditionally).
  - Found, not fixed (outside the four findings): the node pod's `checksum/artifact-storage`
    hashes the RENDERED storage Secret, which has random values when the chart generates them,
    so under GitOps the node restarts on every sync. That is the pattern review round #2
    rejected for the signing key. Follow-up.
