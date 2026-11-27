---
ticket: OME-2045
stack: repo
status: in_progress
started: 2026-11-26
finished:
---

# Unit 8A fixed-label reference contract pins

## Intent

Pin the isolated fixed-label reference before implementation, using the existing scalar
classification path. Keep the deterministic reference proof independent of Router integration.

## Planned changes

- In `docs/spec/2026-11-16-router-recipe-extension/`, amend C7 in `contracts-replay.md`,
  the Unit 8 scope and pending approvals in `00-overview.md`, and the test plan in `test-plan.md`.

## Test plan

- Verify the pinned Hub metadata, compare the native contract with the existing scalar codec,
  and check the draft's diff, Markdown tables, links and headings. Specify the model-free first
  failing tests and the future isolation gates in the shared test plan.

## Acceptance

- The draft pins artifact identity and provenance, label order and softmax, native shape, token
  refusal, platform, and offline verification. Later Router integration and live qualification
  remain gated.

## Outcome

- **Actual files:** The three planned specification files, this ledger and the OME-2045 task mirror.
- **Base:** `4efb34bc6cd3af823e3b9324d73690e8c28a733d`.
- **Commits:** this PR; one conventional docs commit referencing OME-2045.
- **Checks:** Pinned registry/model-card metadata, config and tokenizer settings, shipped scalar codec
  and refusal mapping; exact fixture digests; repo gates; Markdown structure; 352 focused scalar-path
  tests in the final independent review. No model artifact was downloaded or provisioned.
- **Deviations:** Initial review required a closed artifact-manifest schema and exact HTTP media and
  refusal precedence. The corrected candidate adds those rules, path/symlink protections and
  model-free negative controls without changing checkpoint, labels, scores or isolation boundaries.
