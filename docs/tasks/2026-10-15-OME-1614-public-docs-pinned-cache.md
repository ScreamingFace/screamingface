---
id: OME-1614
linear_url: https://linear.app/openmined/issue/OME-1614/document-reproducing-a-run-with-evaluatepinned-cache-and-the
status: in_progress
type: docs
priority: medium
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1307
created: 2026-10-15
closed:
---

# Document reproducing a run with evaluate(pinned_cache=…) and the submission metadata fields

Public docs for the E14 follow-up: the Reproduce snippet, `pinned_cache` / `score_id` replays,
partial replays, seeds, and author and paper metadata. Rewrites the pages that teach the removed
`sf.reproduce` and the renamed `frozen_copy_id`. Lands with or right after the SDK release that
contains `OME-1613`.

- 2026-10-21: mirror filed (it was missing); scope updated in Linear after the OME-1613 design review.

- 2026-10-22: implemented the public docs and validated locally against the merged SDK.
  Initially draft pending release dependencies. Owner requested ready-for-review after independent
  review; merging still requires the SDK release, released-SDK snippet verification and the portal
  snippet update in OME-1655 / PR #1522.
