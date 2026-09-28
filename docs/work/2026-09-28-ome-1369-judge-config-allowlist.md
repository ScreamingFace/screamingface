---
ticket: OME-1369
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---

# ome-1369-judge-config-allowlist — pin the judge's inherited delivery settings

## Intent

OME-1369 asked the judge provider to refuse every `GenerateConfig` field except
delivery-only ones, and to refuse tools. Verification (2026-09-28) found both already on
`main`: commit `6ca658a2`, merged in #1051 on 2026-09-24, a day before the ticket was filed
from the #1032 review. Three of the four acceptance tests exist and pass. The open one —
"inspect's default-filled transport fields pass" — exposed a real gap: inspect copies five
operational fields (`max_connections`, `adaptive_connections`, `max_retries`, `timeout`,
`cache`) from an eval's active config into every other model, and the allowlist lacks
`cache`, which the ticket lists as allowed. A judge running under an eval with caching set
would refuse its own inherited setting.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/judge_provider.py`: add
  `cache` to `_TRANSPORT_CONFIG_FIELDS`, with the WHY.
- `apps/screamingface-engine/tests/unit/inspect/test_judge_provider.py`: one new test.

## Test plan

- RED: run the judge as a non-active model under an active eval config carrying all five
  inherited operational fields; assert the call goes through. Fails today on `cache`.

## Acceptance

- The new test passes; the whole `tests/unit/inspect` lane stays green (FrontierScience
  board test included).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the `docs/tasks` mirror (none existed for OME-1369).
- **Commits:** `054a06a8` — `fix(screamingface-engine): let a judge keep the cache setting an eval hands it` (#1089, squash-merged).
- **Gates:** `uv run --extra inspect pytest -q -rs tests/unit/inspect` 360 passed (was 359);
  ruff check, ruff format --check, pyright, check_layering green. Paid lanes not run.
- **Deviations:** the ticket's main change (allowlist + tools refusal) was already merged in
  #1051, so this unit ships only the missing acceptance pin and the `cache` entry it exposed.
  Branch named `OME-1369-allow-inherited-judge-cache`: the lowercase work-start name collides
  with `OME-1369-judge-config-allowlist` on a case-insensitive filesystem.
