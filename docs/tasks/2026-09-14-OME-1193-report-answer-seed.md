---
id: OME-1193
linear_url: https://linear.app/openmined/issue/OME-1193
status: In Review
type: task
priority: Medium
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-14
closed:
---

# The run report doesn't name the answer seed, so a researcher can't cite which sitting produced a score

Implemented on the `OME-1038-answer-seeds` branch (PR #927, owner decision): the seed
rides the compiled Candidate the transport already receives, `evaluate(answer_seed=…)`
sends `X-Answer-Seed` on run start (also on url4 replays), and `CandidateResult.answer_seed`
serializes into `report.json` as an always-present key (null when unseeded). Public
surface widened deliberately: changelog entry + regenerated surface snapshot.
