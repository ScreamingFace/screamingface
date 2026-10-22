# Verified open-weight releases plan

Implements [the approved scope](../spec/2026-10-22-glm-openness.md).

1. Audit the current catalog and official model repositories; record checked sources,
   revisions, license metadata, and explicit serving-alias evidence.
2. Reproduce missing release recognition and the two false-open Qwen classifications.
   Cover direct/prefixed routes, exact-match boundaries, mixed ensembles, overrides,
   unknown diagnostics, and read-time frontier/history behavior.
3. Replace the single GLM entry with one static route-to-weight-repository registry.
   Defer the two hosted Qwen routes before legacy owner matching. Update the new PR's
   Prime/Flash negative cases for now-verified releases while retaining future variants.
4. Run all scoreboard gates, replay the public snapshot, inspect the diff, and update
   draft PR #1534 and OME-1716 with the evidence, final scope, and validation results.
