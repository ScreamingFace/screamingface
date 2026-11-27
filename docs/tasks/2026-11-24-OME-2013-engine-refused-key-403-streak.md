---
id: OME-2013
linear_url: https://linear.app/openmined/issue/OME-2013/pin-that-two-undeclared-403-codes-extend-one-refused-key-streak
status: in_progress
type: task
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1306
created: 2026-11-24
closed:
---

# Pin that two undeclared 403 codes extend one refused-key streak

The Engine lifts a Gateway error's `detail.code` only when the Gateway declares that code
(OME-2010). Any other code reads `aigateway_http_<status>`. The refused-key watch (OME-1989)
counts a model's 403 Cases per code and starts the count over when the code changes.

So two different undeclared 403 codes now extend one streak. A proxy that refuses the key with a
different code each time still stops the run after five Cases. Before OME-2010, the two codes
alternated and the count started over on every Case.

The behavior is already on `main`. This adds the test that pins it:
`apps/screamingface-engine/tests/unit/test_refused_key_stop.py::test_two_undeclared_403_codes_extend_one_streak`.
No production code changes.

Ledger: `docs/work/2026-11-24-engine-refused-key-403-streak.md`.
Branch: `OME-2013-engine-refused-key-403-streak`.
