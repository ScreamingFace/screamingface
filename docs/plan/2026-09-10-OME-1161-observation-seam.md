# OME-1161 — Plugin and deployment review split

Owner update, 2026-09-15: keep plugin implementation in PR 931 against main and mark it
ready for review. Stack deployment/integration as a separate draft; rebase that child onto
main after 931 merges. This supersedes the combined-PR plan, without a 500-line cap.

## Delivered foundation

PR 897 merged the design, PR 899 the observation ports, and PR 915 generic execution
integration and the OME-1201 prompt inline-hook contract. No generic core edits are needed.

## PR 931: plugin implementation

Keep activity schema, safe fields, rolling admission/session, operation lifecycle, observer,
fixed heartbeats and direct tests. Preserve sink-loss accounting, interruption-safe collective
timer cleanup and inert disabled callbacks. This PR does not register or enable the plugin.

## Stacked draft: deployment and integration

Move observation registration, local/worker configuration, Helm wiring and deployment,
run-scope, stream/Client-decoding and removal tests here. Preserve explicit local Settings
precedence and run-level disabled masking. This is the PR that makes deployment full/off
selectable; generic executor defaults stay empty. It depends on PR 931 and stays draft.
After 931 merges, rebase only the child's commits onto main and retarget its base.

## Verification and scope

Both branches run full Engine gates. The combined runtime must match f418f53e exactly;
relocated direct observer tests plus child integration tests preserve all prior coverage.
Review both axes and report each PR's actual diff. Keep the same shared spec, plan, task
mirror and work ledger. OME-1161 remains open until both PRs merge.

Client rendering, benchmark-stage producers, semantic attribution, aggregate policy and
provisional scores remain separate. This pair completes the Engine model-call producer.
