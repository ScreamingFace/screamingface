---
id: OME-1983
linear_url: https://linear.app/openmined/issue/OME-1983/ci-picks-a-different-helm-when-the-latest-release-lookup-fails-and-a
status: done
type: bug
priority: none
labels: [bug, repo-dev-processes, agentic, autonomous]
parent: none
created: 2026-11-20
closed: 2026-11-20
---

# CI picks a different Helm when the latest-release lookup fails, and a chart test then fails

Eight CI `setup-helm` steps had no `version:`; a failed latest-release lookup made one #1896 run
use Helm v3.18.4, whose schema error wording a chart test does not expect. All eight now pin
v4.3.2, the version green runs use.

- Ledger: `docs/work/2026-11-20-pin-helm-in-ci.md`
