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

This adds every such path to both triggers. It also adds a guard test that fails when an Engine
test uses a repo path outside the filters, either by reading the path or by testing that it
exists. A path counts even before it exists, so a test that waits for a future fixture still
depends on it. A path built on a name the test imports counts too. When that name comes from a
module outside the repo, the guard fails unless the module is reviewed and listed. A directory
that a test finishes at run time stands for what the test reaches through it, and so does the
repo root. A test that passes the directory on stands for all of it, unless that test is
reviewed and listed.

The image, real-broker and chart jobs now run only when a change touches one of these:
- the Engine;
- url4;
- the root `.dockerignore`, which decides what the images copy;
- the workflow itself.

The unit tests run for every change. A push is compared by its two trees, and a pull request
by its own commits, as GitHub filters them. A manual run, or a base git cannot find, counts as
an Engine change.

Ledger: `docs/work/2026-11-24-engine-gateway-fixture-paths.md`.
Branch: `OME-2014-engine-gateway-fixture-paths`.
