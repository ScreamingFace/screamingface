---
ticket: OME-1211
stack: screamingface-engine
status: done
started: 2026-09-16
finished: 2026-09-16
---

# OME-1211 — Revert the engine tracing default; it is timing out on every deployed run

## Intent

`OME-1190` (#921) defaulted `tracing.enabled: true` with a hardcoded in-cluster collector
address. It is live in `sf-fusion` and is degrading every run. Revert it in full.

## The deployed evidence

Both of these appear in `sf-fusion` for every run since the deploy (topics `ukiMcoOF0…` 16:05,
`Ou1BQlZ4…` 15:59, 2026-09-15):

```
INFO  screamingface_engine.tracing.otlp … otlp span export enabled service=screamingface-engine
      Failed to export span batch due to timeout, max retries or shutdown.
```

`Failed to export` and `Max retries` each match on all observed runs. So: the exporter is on,
the collector is unreachable, and `SpanRelay.shutdown()` flushes at process exit — every run
now waits out the exporter timeout on a connection that never answers, then discards every
span. An empty trace view **and** a slower exit, with nothing in the log that explains the delay.

## Why it was wrong — the design error

`bitsofsteve` predicted this exactly, in the #921 review, and asked for the PR to be closed:

> The network boundary around your dev namespace allows only DNS, your own services, and the
> public internet on 443. The collector is inside the cluster, so every export packet is dropped.

Staging has no collector at all; previews share dev's boundary.

**My error: I reasoned "in-cluster Service DNS ⇒ reachable" and never considered NetworkPolicy.**
Enabling tracing requires opening the network path *and* setting the values. Those are one job,
owned by one team. I could only see the half I could reach — the chart — so that half looked
like the whole thing, and "I can't reach the infra repo" became a reason to route around it
rather than a signal that the work was not mine.

The failure is made worse by two of my own design choices, which are individually right and
together silent: the sink swallows exporter errors by contract (a collector outage must never
fail a run), and it flushes on shutdown so the tail of a trace is not lost. Combined with an
unreachable endpoint that yields a per-run timeout nobody is told about.

## Process failure, recorded because it is the more repeatable one

The review asking to close #921 landed at **13:07 UTC**. #921 was merged at **14:13 UTC** — an
hour later — by `sergio-bershadsky`. The merge went in after, and against, an explicit request
not to merge. Worth a convention (see `OME-1212`): a PR carrying a reviewer's "please close
this" should not be mergeable on a green CI signal alone.

## What the revert restores

`git revert -m 1 56334ee9`, applied cleanly with no intervening changes to those paths:

- `tracing.enabled: false`, `tracing.endpoint: ""` — as `OME-1131` shipped them
- the chart tests back to their off-by-default form
- the namespace-derived `OTEL_RESOURCE_ATTRIBUTES` default and the `OME-567` sunset note, gone

Nothing is kept. `bitsofsteve` is making the collector stamp the source namespace itself, which
retires the chart-side attribute, and they own turning tracing on.

**The revert also deletes `OME-1190`'s own ledger and mirror.** Deliberate: they document a unit
whose code no longer exists, and this ledger is the better record of that decision and its
outcome. `OME-1190` is Canceled in Linear with the same reasoning.

## Test plan

Restored by the revert, not rewritten — the chart tests return to the assertions `OME-1131`
merged and the suite must be green on them:

- default render emits NO OTLP variables anywhere
- `tracing.enabled=true` with an empty endpoint still fails the render
- the credential still travels by Secret only

## Acceptance

- `run_gates.py screamingface-engine` green.
- `git show origin/main:…/values.yaml` after merge shows `enabled: false` and `endpoint: ""`.
- **Deployed**: the next `sf-fusion` run logs neither `otlp span export enabled` nor
  `Failed to export`. The trace view stays empty — correctly — until the platform side opens
  the network path and sets the values.

## Outcome

- **Actual files:** `git revert -m 1 56334ee9` — `deploy/helm/values.yaml`,
  `deploy/helm/templates/configmap-runner-env.yaml`,
  `tests/unit/test_chart_render_tracing.py`, and the deletion of `OME-1190`'s ledger + mirror.
  Plus this ledger and `docs/tasks/2026-09-16-OME-1211-revert-tracing-default.md`.

- **Gates:** `run_gates.py screamingface-engine --skip-append-only` **ALL GREEN**.

- **The append-only gate fired, and this time assertions go DOWN: 17 → 12.** That is inherent to
  a revert — the five extra tests asserted the reverted behaviour (ON by default, the namespace
  attribute, the override precedence), so they have nothing left to assert. The 12 restored are
  byte-identical to what `OME-1131` merged, which is the point: this is a restoration, not a
  weakening. Called out explicitly because "assertions decreased" is normally exactly the signal
  rule 5 exists to catch, and it should not pass unremarked just because the diff is a revert.

- **Verified restored, not assumed:**
  - `values.yaml`: `enabled: false`, `endpoint: ""`.
  - Default `helm template` emits **no** OTLP key — the single remaining `OTEL_` match is the
    `# NOTE: OTEL_EXPORTER_OTLP_HEADERS is deliberately ABSENT here` comment `OME-1131` shipped,
    confirmed to be a comment line rather than a rendered key.
  - Chart tests 12/12 green.

- **Deviations:**
  - **`OME-1190`'s ledger and mirror are deleted rather than annotated.** They describe a unit
    whose code no longer exists; this ledger carries the decision and its outcome instead, and
    `OME-1190` is Canceled in Linear with the same reasoning.
  - **The deployed fix is not verified by this PR.** Merging restores the chart; the runner pods
    only stop timing out once ArgoCD syncs. The acceptance check (no `otlp span export enabled`,
    no `Failed to export` in `sf-fusion`) has to run after that sync, not at merge.
