---
id: OME-1001
linear_url: https://linear.app/openmined/issue/OME-1001/start-the-local-stack-with-one-command-for-devs-and-users
status: in_progress
type: null
priority: 3
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-26
closed: null
---

# Start the local stack with one command for devs and users

Devs start the local stack with `just stack-up`, users with `screamingface up`; the two
paths build the stack differently, so user-only bugs (missing dependency pins, GitHub
`#735`) ship unseen by every dev machine.

Fix: `screamingface up` becomes the only start command — inside the repo checkout it
serves the live `apps/` code, outside it serves the installed package — the justfile's
env defaults move into the runtime, and the justfile is deleted. Full Before/After,
don't-regress list, and step list live in the Linear issue.
