---
id: OME-952
linear_url: # pending — owner creates the sub-issue in Linear under the OME-950 epic
status: todo
type: improvement
priority: 3
labels: [aigateway, autonomous, agentic]
created: 2026-08-22
closed:
---

# aigateway-ui: response-cache console section

PROVISIONAL id — see the epic mirror (`docs/tasks/2026-08-22-OME-950-admin-cache-snapshot-upload.md`).

Console half of OME-950, per `docs/spec/2026-08-22-OME-950-admin-cache-snapshot-upload.md`:

- New "Response cache" section: info panel (serving flag, row count, revision constants from
  `GET /v1/admin/cache/info`), upload form (file + optional manifest, mode `merge`/`replace`,
  `acknowledge_loss` shown only for replace, `force` for revision override), job list with
  polling of `GET /v1/admin/cache/snapshots/jobs`.
- Server actions in `src/app/actions.ts` stay the only mutation boundary; the upload is the
  first multipart action — extend the client (`src/lib/aigateway/client.ts`) with a multipart
  path; keep `cache: "no-store"` discipline.
- Errors surface through the existing `AdminApiError` taxonomy; warnings from the job record
  render verbatim (`revisions_unverified` and friends).
- Regenerate `schema.d.ts` from the gateway's OpenAPI after OME-951 lands its response models.
