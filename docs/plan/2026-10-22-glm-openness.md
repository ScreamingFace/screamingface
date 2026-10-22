# GLM-5.3 openness correction plan

Implements [the approved scope](../spec/2026-10-22-glm-openness.md).

1. Reproduce solo, all-open ensemble, and frontier/trend failures with new tests.
2. Add an exact `(owner, model)` allowlist beside existing owner/family rules,
   citing official evidence. Do not broaden GLM into a family rule.
3. Verify unknown suffixes/owners, mixed entries, overrides, and diagnostics.
4. Run scoreboard gates, review the diff, and prepare a PR linked to OME-1716.
