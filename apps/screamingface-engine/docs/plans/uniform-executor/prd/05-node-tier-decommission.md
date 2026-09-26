# PRD: Node tier decommission

**Source:** prompt, ans:Q1, ans:Q2, ans:Q3, ans:Q4 · **Priority:** P2 (last; only after the parity gate)
**Lifecycle:** existing (characterize + delta: removal)
**Owner:** unassigned

## 1. Summary and the flows it serves

This is a component PRD. No user flow drives it. It removes the node tier after PRD 04 has
moved every mount call to the uniform path. It also defines the parity gate that must pass
first.

## 2. Background and constraints

- "simplify the concept and component `node tier` and the `workers` in a single component"
  `[stated prompt]`
- "Delete after parity gate": delete code, chart and tests in the last phase, with no flag,
  only after the behavior gates pass. `[stated ans:Q2]`
- "No latency gate": the gate measures and reports latency, but latency never blocks it.
  `[stated ans:Q3]`
- Validation: "local + emulated k8s using kind". `[stated ans:Q4]`

### 2.1 Current behavior (what exists and goes away)

- CLI mode `screamingface-engine node` → `world/node_tier/serve`. `[existing cli.py _node]`
- Package `world/node_tier/` (`tier.py` 378 lines, `build.py`, `settings.py`, `metrics.py`).
  `[existing world/node_tier/]`
- `rest/forwarder.py` (404 lines): `NodeForwarder`, `install_forwarder`, `ForwardContract`,
  `forwarded_headers`. `[existing rest/forwarder.py]`
- `NodeMountRoute` in `world/serving.py:288`. `[existing]`
- Settings `node_base_url`, `node_forward_timeout_s`. `[existing config.py:173-178]`
- Chart: `templates/deployment-node.yaml`, `service-node.yaml`, `networkpolicy-node.yaml`,
  `poddisruptionbudget-node.yaml`; `values.yaml` `node:` block; `values.schema.json` node
  section and the `node.enabled ⇒ s3` guard; `_helpers.tpl` `nodeName`, `nodeBaseUrl`,
  `nodeSelectorLabels`, `nodeLabels`; `NOTES.txt` lines 14–42. `[existing deploy/helm/]`
- Metrics `screamingface_engine_node_sync_*`. `[existing world/node_tier/metrics.py:47-68]`
- Tests: 7 node-tier unit files (~89 tests), `test_chart_render_node_tier.py`, the
  `node_tier_settings` fixture in `tests/conftest.py`. `[existing tests/]`
- Docs: `docs/plans/prd/03-node-tier-and-sync-surface.md`, `docs/plans/contracts.md` (C2, C6),
  `docs/protocol.md` (sync surface), `README.md`, `deploy/helm/README.md`,
  `docs/diagrams/ensemble-node-*.{svg,png}`. `[existing]`
- Node default: `node.enabled: false`. No values file in the repo enables it. `[existing deploy/helm/values.yaml; values-cloud.yaml]`

**Keep** (still used by PRD 04): `world/serving.py` collision guard (F4) and
`node_mount_paths`; `artifacts/signing.py`; `templates/secret-artifact-signing.yaml` (its
render condition changes from `node.enabled` to "always when a key or existing secret is
set"); `rest/artifacts.py`. `[implied]`

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **DC-H1 parity gate passes.** Given PRD 01–04 are merged, when the gate runs, then all of
  these are true, and the result is recorded in `measurements/parity-gate.md`:
  1. Every MNT test is green, including MNT-9 against the MNT-C2 status table. `[stated ans:Q2]`
  2. Every behavior in the 7 node-tier test files is either ported to a test on the direct
     path (named in a mapping table in the gate record) or recorded as "not applicable" with
     a reason (for example "in-flight cap 2 per node worker": replaced by the queue cap).
     `[stated ans:Q2]`
  3. The kind suite (test-plan §5) is green, including the chaos cases. `[stated ans:Q4]`
  4. The measurement report exists and compares the node-tier mount call with the
     direct-run mount call. It blocks nothing. `[stated ans:Q3]`
  5. A human confirms, in the gate record, that no environment outside the repo sets
     `node.enabled: true`. `[proposed]`
- **DC-H2 removal.** Given DC-H1 passed, when the removal change merges, then none of the
  items in §2.1 (except the "Keep" list) exist, and every quality gate is green.
  `[stated ans:Q2]`

### 3.2 Error paths

- **DC-E1 gate fails.** Given any gate item in DC-H1 is false, then the removal does not
  start, and the gate record names the failing item. `[stated ans:Q2]`

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L |
|---|---|---|---|
| DC-D1 | An operator's values still set `node.enabled` | [proposed — gap §per-connection/dependency] | M×M |
| DC-D2 | A leftover import of the deleted package | [implied] | M×M |
| DC-D3 | The artifact-signing secret stops rendering | [implied] | H×L |
| DC-D4 | The CLI still accepts `node` | [implied] | L×M |
| DC-D5 | Docs still describe the node tier | [implied] | L×H |
| DC-D6 | Metrics dashboards query `node_sync_*` | [proposed — gap §cross-cutting/observability] | L×M |

- **DC-D1.** Given a values file with a `node:` block, when `helm template` runs, then it
  fails, and the message says the node tier was removed and names this plan.
  (`values.schema.json` already refuses unknown keys; the message must be clear.)
- **DC-D2.** Given the removal, when `check_layering.py`, `pyright` and the test suite run,
  then no module imports `world.node_tier` or `rest.forwarder.NodeForwarder`.
- **DC-D3.** Given `artifactSigning.signingKey` is set and there is no `node:` block, when the
  chart renders, then `secret-artifact-signing` renders, and the App gets
  `URL4_CLOUD_ARTIFACT_SIGNING_KEY`.
- **DC-D4.** Given `screamingface-engine node`, then argparse exits 2 with "invalid choice".
- **DC-D5.** Given the removal, then `docs/plans/00-overview.md` and
  `docs/plans/prd/03-node-tier-and-sync-surface.md` carry a "Superseded by
  `docs/plans/uniform-executor/`" banner at the top, the other docs listed in §2.1 no longer
  describe a node tier, and the architecture diagrams in `docs/diagrams/` show one executor.
- **DC-D6.** Given the removal, then the chart README lists the removed metric names and their
  replacements (`screamingface_engine_mount_calls_total`, `worker_handoff_latency_s`).

## 4. Non-functional requirements

- **Size.** Expected net deletion: about 1 100 lines of source, about 300 lines of chart, and
  about 90 tests (after porting). The gate record lists the real counts. `[proposed]`
- **Reversibility.** A git revert of the removal commit restores the node tier. The removal is
  one commit. `[proposed]`

## 5. Out of scope

- Keeping the node tier behind a flag. `[stated ans:Q2]`
- A latency threshold. `[stated ans:Q3]`

## 6. Open questions

None.

## 7. TDD plan

Order: gate first, then deletion. A deletion is proven by tests that fail while the old code
exists and pass after it is gone.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| DEC-C1 | CHAR `chart_renders_signing_secret_with_node_enabled` | unit (chart) | [existing templates/secret-artifact-signing.yaml] | H×L | passes today |
| DEC-1 | `parity_gate_record_complete` (script checks the record: 5 items, mapping table, no blank rows) | unit | [stated ans:Q2 — DC-H1] | H×M | `scripts/parity_gate_check.py` |
| DEC-2 | `chart_rejects_node_block_with_clear_message` | unit (chart) | [proposed — DC-D1] | M×M | schema + `fail` message |
| DEC-3 | `signing_secret_renders_without_node_block` | unit (chart) | [implied — DC-D3] | H×L | change the render condition |
| DEC-4 | `no_module_imports_node_tier` | unit (layering) | [implied — DC-D2] | M×M | delete the package; add the rule to `check_layering.py` |
| DEC-5 | `cli_rejects_node_mode` | unit | [implied — DC-D4] | L×M | remove the subparser |
| DEC-6 | `settings_have_no_node_fields` | unit | [implied] | L×M | remove `node_base_url`, `node_forward_timeout_s` |
| DEC-7 | `docs_have_no_live_node_tier_reference` (grep outside superseded files) | unit | [implied — DC-D5] | L×H | doc edits + banners |
| DEC-8 | kind: `full_suite_green_after_removal` | e2e (kind) | [stated ans:Q4] | H×M | rerun test-plan §5 |
| DEC-9 | `chart_readme_lists_removed_node_metrics_and_replacements` | unit | [proposed — DC-D6] | L×M | README table; test greps each `node_sync_*` name |
