---
title: Detect a missing [runtime] extra before the local stack boots
ticket: OME-1036
status: approved
date: 2026-08-28
spec: ../spec/2026-08-28-OME-1036-runtime-extra-preflight.md
---

# Detect a missing [runtime] extra before the local stack boots

1. Add failing tests in `packages/screamingface/tests/test_runtime_cli.py`:
   the missing-module probe (fake finder), the `require_runtime_extra` message (missing
   list injected), the probe-list invariant (`tortoise`, `litellm`, `kubernetes` pinned),
   the `_serve` install hint for `ImportError`, and the `_wait_ready` log tail.
2. Implement the probe in `_runtime/server.py`: the module tuple, `_missing_runtime_modules`
   with an injectable finder, and the friendly error before the vendored-app imports.
3. Implement the `_serve` `ImportError` branch and the `_wait_ready` log tail in
   `_runtime/cli.py`.
4. Update the README "Install" section with both commands and add the troubleshooting
   entry.
5. Run the screamingface stack gates (ruff, format, pyright, pytest, notebook check,
   build, distribution check).
6. Review `origin/main...HEAD`, fill the ledger outcome, commit, and push the branch. Do
   not open a PR until the owner requests it.
