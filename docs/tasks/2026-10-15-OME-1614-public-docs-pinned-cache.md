---
id: OME-1614
linear_url: https://linear.app/openmined/issue/OME-1614/document-reproducing-a-run-with-evaluatepinned-cache-and-the
status: done
type: docs
priority: medium
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1307
created: 2026-10-15
closed: 2026-10-22
---

# Document reproducing a run with evaluate(pinned_cache=…) and the submission metadata fields

Public docs for the E14 follow-up: the Reproduce snippet, `pinned_cache` / `score_id` replays,
partial replays, seeds, and author and paper metadata. Rewrites the pages that teach the removed
`sf.reproduce` and the renamed `frozen_copy_id`. Merged in PR #1535 after the owner authorized
publishing the docs ahead of the SDK release containing `OME-1613`.

- 2026-10-21: mirror filed (it was missing); scope updated in Linear after the OME-1613 design review.

- 2026-10-22: implemented the public docs and validated locally against the merged SDK.
  Initially draft pending release dependencies. Owner requested ready-for-review after independent
  review; at that point, merging still required the SDK release, released-SDK verification and the portal
  snippet update in OME-1655 / PR #1522.

- 2026-10-22: PR #1535 squash-merged as `8546bcbbd4d76edb85a5d550f2f8c8948fe40cdb`
  after a fresh clean code review and green CI. Owner authorization superseded the earlier release
  hold. Linear synced to Done; released-SDK/live-example verification and the sidebar release
  update remain tracked with OME-1655.
