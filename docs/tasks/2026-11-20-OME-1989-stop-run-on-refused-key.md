---
id: OME-1989
linear_url: https://linear.app/openmined/issue/OME-1989/stop-a-run-when-the-provider-refuses-the-key-instead-of-failing-every
status: done
type: fix
priority: medium
labels: [screamingface-engine, agentic]
created: 2026-11-20
closed: 2026-11-20
---

# Stop a run when the provider refuses the key instead of failing every Case

When a provider refused a hosted key on every call, the Engine recorded each refusal as one
failed Case and moved on, so a 4,519-Case run sent 4,519 calls that could not answer. Seen in
production on 2026-11-19: 7,056 provider 403s across one account's 18 runs. The Engine now stops
sending Candidate calls once the key is refused (the first rejected or unfunded key, or the same
403 on 5 Cases in a row for one model) and ends the run with one run-level
`provider_key_refused` that names the cause. The gateway's record of a provider 402/403 now
carries the provider's screened reason.

- 2026-11-20: the ticket was filed before work started, with no parent epic; on 2026-11-21 it was placed under `OME-1314` (platform capacity). Owner action left:
  merge. No paid run was needed.
- Ledger: `docs/work/2026-11-20-stop-run-on-refused-key.md`
