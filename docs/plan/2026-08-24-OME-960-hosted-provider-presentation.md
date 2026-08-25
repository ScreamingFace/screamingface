---
title: Implement hosted provider status presentation
ticket: OME-960
status: approved
date: 2026-08-24
spec: ../spec/2026-08-24-OME-960-hosted-provider-presentation.md
---

# Implement hosted provider status presentation

1. Replace the inherited hosted-all-connected assertion with failing tests for connected,
   unavailable, and non-terminal/error provider states across widget text, static HTML, and repr.
2. Pin the absence of every hosted provider mutation control and preserve the existing loopback
   BYOK behavior.
3. Update the shared provider presentation helper so hosted rows trust Engine status, derive the
   `Unavailable` label for `not_connected`, and claim ScreamingFace availability only when
   connected.
4. Run the focused connection-panel tests and the complete ScreamingFace gate suite.
5. Review the `origin/main...HEAD` diff, fill the ledger outcome, and commit locally. Do not open a
   Client PR until the owner explicitly requests it.

## Review follow-up

6. Replace the weak substring assertions with exact hosted status-cell assertions for every
   non-connected wire state.
7. Consolidate hosted/local wire-state, label/class, and source decisions into one presentation
   projection; remove the second branching helper.
8. Collapse every hosted non-connected wire state to the quiet SFDS `Unavailable` presentation,
   rerun focused and full gates, commit, and update draft PR #703.
