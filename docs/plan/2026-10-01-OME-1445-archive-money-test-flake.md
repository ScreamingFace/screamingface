# OME-1445 — plan

Spec: `docs/spec/2026-10-01-OME-1445-archive-money-test-flake.md`. Branch
`OME-1445-archive-money-test-flake` from `origin/main`.

1. **RED.** Give `_CachedReplayTransport` an optional `completed_at`. Add
   `test_the_archive_rule_holds_when_the_clock_reads_zero_point_five`, which runs the archive case
   with `completed_at` = `2026-10-01T08:40:30.507912Z` and calls a shared `_assert_no_money(...)`
   helper that, at first, keeps today's text search. Confirm it fails on the pinned clock.
2. **GREEN.** Reimplement `_assert_no_money` on `_money_values(obj)`. Point `:220`, `:221` and
   `:98` at it. Confirm every test in the file passes.
3. **Mutation.** Temporarily make `_submission` add the archive amount under a new key; the
   value check must fail. Revert.
4. **Gates.** `run_gates.py screamingface --base origin/main`, once without the append-only skip
   to show only the three approved lines are flagged, then with it.
5. Ledger outcome, mirror, PR with `Refs: OME-1445`.
