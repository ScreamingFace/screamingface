---
id: OME-1204
linear_url: https://linear.app/openmined/issue/OME-1204/rename-the-provider-access-modules-and-test-helpers-without-leading
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-09-15
closed: 2026-09-15
---

# Rename the provider-access modules and test helpers without leading underscores

Follow-up to A1 (`OME-1200`) of `OME-1138`: owner decision that no provider-access file name begins with `_` (`__init__.py` excepted). Rename-only refactor of five package modules and two test helpers; imports and the package facade updated; no behaviour, API or OpenAPI change; A2 not started.

Ledger: `docs/work/2026-09-15-OME-1204-rename-provider-access-modules.md`.
Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md` §3.1. Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md` A1.

- 2026-09-15: rename done — naming test RED→GREEN; focused suite 164 passed; stack gates green with the append-only check skipped (that check flags the rename itself); OpenAPI byte-identical to `837ab5b6`; committed as `a762e7eb`.
- 2026-09-15: owner review — topology assertion removed from the naming test; plan U2/U3 now depend on U1, U1n; focused suite 164, static checks and the full gate green; committed as the OME-1204 unit and closed.
