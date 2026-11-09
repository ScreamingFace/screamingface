---
id: OME-1813
linear_url: https://linear.app/openmined/issue/OME-1813/websocket-nack-tests-fail-when-a-heartbeat-arrives-before-the-error
status: done
type: bug
priority: medium
labels: [bug, screamingface-engine, agentic, autonomous]
created: 2026-11-03
closed: 2026-11-03
---

# Websocket nack tests fail when a heartbeat arrives before the error reply

Three tests in the Engine's websocket suite sent one bad frame and asserted the bridge's error
reply (the nack) was the very first frame back. The bridge sends nacks and heartbeats through one
writer queue, and a heartbeat goes out whenever that queue has been idle for 50 ms in these
tests, so on a slow CI runner the heartbeat landed first and the test failed although the bridge
did its job (PR #1631, 2026-11-03; green on the rerun of the same commit). The three tests now
read their nack through a bounded "first frame that is not a heartbeat" helper, with every
assertion on the nack unchanged, and a new test pins the heartbeat-first ordering. The edit to
the existing tests is approved in `.claude/test-change-approvals/OME-1813.json`. Ledger:
`docs/work/2026-11-03-ws-nack-tests-tolerate-heartbeat.md`.
