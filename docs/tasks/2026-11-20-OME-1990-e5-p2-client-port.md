---
id: OME-1990
linear_url: https://linear.app/openmined/issue/OME-1990/leave-the-client-one-transport-port-follow-a-run-e5-p2
status: in_progress
type: refactor
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1837
created: 2026-11-20
closed:
---

# Leave the Client one transport port: follow a Run (E5 P2)

The Client port step of a detached Run (plan step CP1). The Engine runs every Candidate and the
Client follows the Run, so `run_transport` takes a transport that follows a Run (register, follow,
cancel, close); the per-Candidate `run()`, the Client's own pool and its read of the per-caller
cap go. The rules the Client used to read a Candidate's record by are tested on the Engine's fold.
It also restores what an abort shows: the Candidates still running read `stopped` (`OME-1071`).

One PR, one commit, stacked on the Client PR #1878 (`OME-1943`), which is stacked on the Engine
PR #1759 (`OME-1895`). It merges before the next Client release. 17 rules about malformed
figures land with `OME-1988`.

- 2026-11-20: filed at PR-open.
- Ledger: `docs/work/2026-11-20-e5-p2-client-port.md`
