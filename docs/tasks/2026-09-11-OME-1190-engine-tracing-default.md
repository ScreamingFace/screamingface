---
id: OME-1190
linear_url: https://linear.app/openmined/issue/OME-1190
status: in_review
type: null
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-11
closed: null
---

# Default engine tracing ON so ArgoCD ships it without an infra-repo change

`OME-1131` shipped the `tracing` stanza off by default; turning it on needs four lines in a repo
(`OpenMined/infrastructure`) the agent account cannot reach. Owner decision: default it ON in the
chart, since ArgoCD merges chart defaults **under** the deployment's values file.

Three things worth knowing before touching this area:

- **⚠️ THIS HAS A SUNSET CONDITION.** Defaulting a *cluster-specific* endpoint is only
  defensible because neither chart here is published — the engine's OCI publishing is deferred
  (`OME-567`) and aigateway's `chart:` job only lints. **When `OME-567` lands, both
  `tracing.enabled: true` and the hardcoded endpoint must go back to opt-in.**

- **`{{ .Release.Namespace }}` must NOT go in `values.yaml`.** Helm does not template values
  files — written there it renders as that literal string, and every service reports the
  template source as its environment. The namespace default lives in the ConfigMap template,
  and a test pins it (`assert "{{" not in preview`).

- **`resourceAttributes` defaults but `serviceName` does not**, and the asymmetry is the point.
  The chart knows something the code cannot — which namespace it is in — so it supplies a
  meaningful default. For the service name the code already has the right default, so the chart
  stays out of the way; rendering `""` there would report a blank `service.name`, which a
  tracing backend cannot distinguish from unconfigured.

**Modifies prior tests** (rule 5 Confidence-Gate, owner-approved, `--skip-append-only`): the
off-by-default pair inverted, and the unset-descriptive-values test was SPLIT rather than
weakened. Net assertions 12 → 17.

Why previews are tagged rather than excluded: a direct OTLP export carries the app's own
Resource, and the k8s collector's namespace enrichment applies to scraped LOGS, not to spans an
app posts itself — so without the attribute a preview's spans are indistinguishable from dev's.

Ledger: `docs/work/2026-09-11-OME-1190-engine-tracing-default.md`
