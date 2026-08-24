---
ticket: OME-953
stack: aigateway-ui
status: in_review
started: 2026-08-24
finished:
---

# OME-953 — aigateway-ui: response-cache console section

## Intent

Console half of the approved OME-951 spec: a "Response cache" section with the live cache info
panel, the snapshot upload form (merge/replace, acknowledge_loss, force), and the polling job
history — all reads/writes through server-side client calls and server actions.

## Planned changes

- `src/lib/aigateway/schema.d.ts` (regenerated from the gateway's OpenAPI incl. OME-952 routes)
- `src/lib/aigateway/client.ts` — cacheInfo/listCacheJobs/getCacheJob/uploadCacheSnapshot (multipart)
- `src/app/actions.ts` — uploadCacheSnapshotAction, listCacheJobsAction
- `src/app/cache/page.tsx` (new) + `upload-form.tsx` + `jobs-panel.tsx` (new)
- `src/app/layout.tsx` — console navigation (Accounts / Response cache)
- `src/app/globals.css` — section styles on existing tokens
- tests: cache actions validation + upload client multipart shape

## Test plan

- Action: missing/oversized snapshot, bad mode, manifest passthrough, gateway refusal mapping.
- Jobs panel: renders states, polls only while active (render test).

## Acceptance

Spec acceptance criterion 11: the console uploads, polls, and renders job states and warnings
without an untyped object reaching the generated client.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (schema regenerated from the gateway OpenAPI on the stacked branch)
- **Commits:** (see PR)
- **Gates:** vitest 224/224 · eslint clean · stylelint clean · tsc clean · next build OK (/cache route)
- **Deviations:** SFDS design-system rules forced two corrections caught by its own tests: font tokens must be var(--f-*) and no authored max-width cap. `conflict` errors render the console's fixed copy (by design in lib/auth), pinned as such.
