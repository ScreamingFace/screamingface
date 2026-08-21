---
id: OME-925
linear_url: https://linear.app/openmined/issue/OME-925/say-what-the-benchmark-image-baked-fail-readably-and-prepare-assets
status: done
type: task
priority: medium
labels:
  - screamingface-engine
  - agentic
  - autonomous
  - task
created: 2026-08-21
closed: 2026-08-21
---

# Say what the benchmark image baked, fail readably, and prepare assets one way

Follow up OME-875 without changing benchmark bytes: retain each preparer's audit summary,
surface expected preparation failures without a traceback, use the registry-derived entrypoint
for local and image preparation, and name the complete benchmark-image build accurately in CI.
