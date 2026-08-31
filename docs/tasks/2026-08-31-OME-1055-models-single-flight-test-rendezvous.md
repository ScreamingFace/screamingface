---
id: OME-1055
linear_url: https://linear.app/openmined/issue/OME-1055/make-the-v1models-single-flight-concurrency-test-deterministic
status: in_progress
type: task
priority: 2
labels: [aigateway, agentic, autonomous, task]
created: 2026-08-31
closed:
---

# Make the /v1/models single-flight concurrency test deterministic

`test_concurrent_callers_share_one_upstream_fetch_chain_and_all_get_200` fails
intermittently in CI on Python 3.12 with `assert 4 == 6`, blocking unrelated aigateway PRs.
First observed on PR #782 (OME-1044), whose diff touches none of the code under test — the
same tree passed once and failed twice.

The test proves single-flight on `/v1/models`: six concurrent callers must cost one upstream
fetch. Two claims sit in it. The product invariant,
`assert http.dialed == [LIVE_MODELS_URL]`, passes on every observed run. The failing line is
the test's own self-check, `assert depth["peak"] == callers`, which exists for a good reason
— without it, "one dial" could be satisfied by a serialized server hitting a warm cache, and
single-flight would be unproven.

The flaw is only in how the overlap is arranged: a fixed `await asyncio.sleep(0.2)` races six
thread startups. On a loaded runner two threads arrive after the refresh completed, are served
from the warm cache, and never overlap — peak reads 4.

Fix: replace the timed window with an explicit rendezvous. The counting wrapper sets an
`asyncio.Event` when the last caller enters; the fake upstream client awaits it under a
timeout instead of sleeping. The overlap becomes structural, and a genuine failure to overlap
reports itself with a diagnostic instead of a bare `4 == 6`. Both original assertions stay.
No production code changes.

Introduced by `cc9deb4a` / PR #739 (OME-972), merged 2026-08-27; latent through ~16 runs.

Ledger: `docs/work/2026-08-31-OME-1055-models-single-flight-test-rendezvous.md`.
