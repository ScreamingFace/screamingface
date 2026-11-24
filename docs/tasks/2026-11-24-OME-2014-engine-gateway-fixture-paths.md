---
id: OME-2014
linear_url: https://linear.app/openmined/issue/OME-2014/run-the-engine-suite-on-every-repo-file-an-engine-test-reads
status: in_progress
type: task
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1321
created: 2026-11-24
closed:
---

# Run the Engine suite on every repo file an Engine test reads

The Engine test workflow starts only when its `paths:` filters match a change. Engine tests also
read files outside the Engine and url4: Gateway fixtures and source, SDK source and metadata, a
scoreboard schema and repo scripts. Several of those paths were missing from the filters. A
change to one of them alone did not run the Engine suite, so a break in an Engine contract twin
merged green and surfaced on the next unrelated Engine change.

This adds every such path to both triggers, and a guard test that fails when an Engine test
reads a repo path outside the filters. The image, real-broker and chart jobs now run only when
a change touches the Engine, url4 or the workflow itself. The unit tests run for every change.
A manual run, an empty diff or a base git cannot find counts as an Engine change.

Ledger: `docs/work/2026-11-24-engine-gateway-fixture-paths.md`.
Branch: `OME-2014-engine-gateway-fixture-paths`.
