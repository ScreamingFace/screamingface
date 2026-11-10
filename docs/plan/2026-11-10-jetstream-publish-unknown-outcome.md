# A run-queue publish with an unknown outcome keeps its slot — Implementation Plan

**Goal:** an unknown publish outcome holds the attempt's reservation until evidence settles it
(spec `docs/spec/2026-11-10-jetstream-publish-unknown-outcome.md`). One PR (#1732), Engine only,
replacing its first approach (re-send and wait-after-cancel), which is reverted.

## Tasks

- [ ] **Revert** the re-send in `runner_queue.py` and the wait-after-cancel in
  `adapters/queue_runner.py`; drop their tests.
- [ ] **RED, runner** (`tests/unit/test_queue_schedule_unknown_publish.py`): an unknown outcome
  (a publish timeout, a cancel mid-publish) holds the slot and records nothing; a definite
  failure releases it; a retry is admitted past its own hold and counted once; a retry that
  fails outright leaves the earlier hold; a late timeout after a landed retry is released; two
  holds of one topic end on their own; the run's terminal frame, a stop's tombstone, the run's
  lifetime and the lease free a hold; the #1648 review's two repros.
- [ ] **RED, real NATS** (`tests/integration/test_run_queue_publish_settles_nats.py`): the first
  publish's acknowledgement dropped after the broker stored it; the start answers
  `RunQueueUnavailable`, the retry succeeds, the stream holds the run once, the caller holds one
  slot. Added to the NATS job's file lists in `.github/workflows/screamingface-engine-tests.yml`.
- [ ] **GREEN, `adapters/queue_runner.py`:** `_UNKNOWN_PUBLISH_OUTCOMES`, `_HELD_SLOT_SLACK_S`,
  the `_Hold` entries; `_settle_failed_publish` holds or releases; `_cap_count`, so a topic
  whose attempts are all held counts once and a held attempt beside a live one adds nothing;
  `_prune_holds`. `runner_queue.py`: `PublishOutcomeUnknown`
  from the run's own send.
- [ ] **Prior tests:** `test_a_schedule_cancelled_mid_publish_releases_its_reservation` (a cancel
  is now unknown: assert the slot is held and the landed retry is counted once), byte-pinned in
  `.claude/test-change-approvals/OME-1859.json`. A plain timeout from the queue stays definite,
  so `test_a_failed_publish_releases_the_reservation_it_made` is unchanged.
- [ ] **Docs:** the `RunQueueUnavailable` docstring and route comment, the CHANGELOG line, the
  ledger, the PR description.
- [ ] **Gates:** ruff, ruff format, pyright, layering, the Engine suite; the append-only check.
