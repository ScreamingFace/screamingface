---
ticket: OME-1643
stack: repo
status: done   # planned | in_progress | done | blocked
started: 2026-10-17
finished: 2026-10-17
---

# community-cache-docs — document the community-cache pull and `use_cache=` on docs.screamingface.ai (epic OME-1311, PR 4/4)

## Intent

The public docs say a local engine's cache "starts empty and stays yours … giving up the
community's hits". With PRs 1–3 (#1433 / OME-1631, #1439 / OME-1635, #1446 / OME-1639) that is no
longer true: `sf.cache.pull_from_remote()` / `screamingface cache pull` copy the community cache
into the local gateway, the local gateway caches by default, and `evaluate(..., use_cache=False)`
opts one evaluation out. This unit brings the public docs (`public-docs/`) in line, as of the
stacked branches' heads after their review rounds (PR 1 `baf7f1d3f`, PR 3 `3dbda4817`). Plan "PR 4"
in `docs/plan/2026-10-15-community-cache.md`.

## Planned changes

- `public-docs/src/pages/learn/CachingPage.vue` — correct the local-engine paragraph; a new section
  on bringing the community cache to a local engine (the call and the command, the exact model
  filter, sign-in, which local gateway it writes to, what crosses, progress, retries and resume,
  requirements) and on opting a run out (`use_cache=False`; the local cache is on by default).
- `public-docs/src/pages/sf-client/api/ModulesPage.vue` — an `sf.cache` section (module-only: no
  `client.cache`), the module count, `use_cache` on `sf.evaluate`.
- `public-docs/src/pages/sf-client/api/ClientsPage.vue` — `use_cache` in `Client.evaluate`'s
  signature and parameter table.
- `public-docs/src/pages/sf-client/guides/EvaluationPage.vue` — `use_cache` in the API table.
- `public-docs/src/pages/sf-client/api/ErrorsPage.vue` — `CachePullError` (`sf.cache`).
- `public-docs/src/pages/sf-client/InstallationPage.vue` — the local gateway caches by default; fill
  it with `screamingface cache pull`.

## Test plan

- `public-docs` has no test suite; its CI is `npx oxlint .`, `npx eslint .` and `npm run build`
  (`vue-tsc --noEmit` + Vite). All three green.
- Every statement is checked against the SDK on `OME-1639-community-cache-sdk` (`3dbda4817`):
  signatures, defaults, error codes and hints, CLI flags and exit codes, retry and resume rules.

## Acceptance

- No page says a local engine cannot get the community's hits.
- `sf.cache.pull_from_remote`, `PullResult`, `CachePullError`, `screamingface cache pull` and
  `use_cache=` are documented where a reader of the caching page, the module reference, the Client
  reference, the evaluation guide and the error reference looks for them.
- The public-docs CI commands pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `learn/CachingPage.vue` (the local-engine paragraph corrected,
  "Bring the community cache to a local engine" with "Opting a run out", the compute figure's
  caption), `sf-client/api/ModulesPage.vue` (`sf.cache` section, module-only note, counts,
  `use_cache`), `sf-client/api/ClientsPage.vue` (`use_cache` in the signature and the table),
  `sf-client/guides/EvaluationPage.vue` (`use_cache`), `sf-client/api/ErrorsPage.vue`
  (`CachePullError` in the hierarchy and the table), `sf-client/InstallationPage.vue` (an optional
  `screamingface cache pull` step).
- **Commits:** `docs(public-docs): the community-cache pull and use_cache= (OME-1311 PR 4)`.
- **Gates:** the public-docs CI commands — `npx oxlint .`, `npx eslint .`, `npm run build`
  (`vue-tsc --noEmit` + Vite) — green; Prettier applied to the changed files.
- **Review rounds checked:** the stacked branches' newest commits (PR 1 `baf7f1d3f`: the loader's
  `check_database`, a `load_page` transaction per call; PR 3 `3dbda4817`: the database checked
  before any request, resume only into the same database after a completed page, 408/429/520–524
  transient with `Retry-After` up to 60 s, `--model ""` a usage error, which local gateway a pull
  writes to). The pages state the behaviour as of those commits; none needed a code change here.
- **Deviations:**
  - Prettier also reflowed one unrelated paragraph on `InstallationPage.vue`; reverted to keep the
    diff to this unit.
  - The docs' `SF_ENGINE_URL` (`src/lib/engine.ts`) names the dev engine while the SDK's default is
    production; the pull's default is stated as the production engine. Aligning that constant is
    out of scope here.

## Follow-up from the gateway and Engine reviews (#1433, #1439 round 2, 2026-10-20)

The fixed #1446 branch is merged in. `ModulesPage` lists `PullResult.rows_skipped`, and
`CachingPage` says a row the local gateway could not serve is skipped, counted and not loaded.
- After the second #1446 review round (merged in): `CachingPage` says one sign-in serves every
  later pull in the process, and that an interrupted pull's `KeyboardInterrupt` carries its counts.
