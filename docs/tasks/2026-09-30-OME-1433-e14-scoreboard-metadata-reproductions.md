---
id: OME-1433
linear_url: https://linear.app/openmined/issue/OME-1433/build-e14-metadata-ownership-frozen-copy-fields-and-reproductions-in
status: in_progress
type: feature
priority: high
labels: [scoreboard, agentic, autonomous]
created: 2026-09-30
closed:
---

# Build E14 metadata ownership, frozen copy fields and reproductions in the scoreboard

Parent: OME-1307. 2 PRs, in the E14 stack.

Ledger (A1): `docs/work/2026-10-06-e14-a1-scoreboard-metadata.md`.
Ledger (B4): `docs/work/2026-10-06-e14-b4-scoreboard-cache-version.md`.
Spec: `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` (binding).

Scope:

- A1: paper link, edit and edit log. Migration `0019`. `PATCH /v1/scores/{id}` changes `authors` and `paper_url` for the verified submitter only. An owner-only route serves the edit log.
- B4: migration `0020_score_frozen_copy` adds `frozen_copy_id`, `capture_status` and `answer_seed`, and the `score_reproductions` table.
- B4: `POST /v1/scores/{id}/reproductions` records exact replays. It answers 409 `not_reproducible`, 422 `not_exact` or 409 `run_id_conflict`.

- 2026-10-09: PR opened on branch `OME-1433-e14-a1-scoreboard-metadata`; gates green against the branch below.
- 2026-10-09: PR opened on branch `OME-1433-e14-b4-scoreboard-cache-version`; gates green against the branch below.
