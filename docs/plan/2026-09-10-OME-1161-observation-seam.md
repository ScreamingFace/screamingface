# OME-1161 — Complete model-activity producer

Owner update, 2026-09-15: combine the remaining plugin work into PR 931 against main.
This replaces the earlier split and its 500-line cap for this PR. Report the complete diff,
including tests/docs, and preserve the rationale and reviewable module boundaries.

## Delivered foundation

PR 897 merged the design, PR 899 the observation ports, and PR 915 the generic execution
integration and OME-1201 latency contract. Core reports execution facts; the activity
plugin owns schema, policy, identity, admission and heartbeat resources.

## Combined PR 931

1. Keep the current activity contract/session and direct tests, including the fix that
   excludes uncertain sink delivery from producer-suppression counters.
2. Restore operation scopes, fixed 60-second heartbeats and the activity observer.
3. Restore local/deployed entry-point registration, full/off settings and Helm wiring.
4. Restore lifecycle/stream/deployment/removal tests and verify with fake providers.
5. Run full Engine gates, Helm renders and independent Standards/Spec reviews.

The generic executor factory keeps its explicit empty-by-default observer argument.
Do not add activity imports to connector/executor or change requests, retries or results.

## Preservation and follow-ups

The complete snapshot is 2bc435bb on OME-1161-complete-plugin-preserved. Extract only
missing components; its old session must not overwrite the sink-accounting fix.
Use the same shared spec, plan, task mirror and ledger. Keep the ticket open until merge.
Client rendering, benchmark-stage producers, semantic attribution and provisional scores
remain separate. PR 931 completes the planned Engine model-call producer, not full-stage UI.
