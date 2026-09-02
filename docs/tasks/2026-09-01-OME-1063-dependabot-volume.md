---
id: OME-1063
linear_url: https://linear.app/openmined/issue/OME-1063/cut-dependabot-pr-volume-without-weakening-the-securityminormajor
status: backlog
type: task
priority: 3
labels: [repo, agentic, autonomous, task]
created: 2026-09-01
closed:
---

# Cut Dependabot PR volume without weakening the security/minor/major split

Dependabot raised eight PRs in under a week — roughly a quarter of the open-PR board.
Seven were green and merged on 2026-09-01; this item slows the refill rate.

`.github/dependabot.yml` is heavily and deliberately tuned (OME-733, -736, -737, -740,
-747, -748) with the rationale in comments. It is not a file to rewrite from scratch.

**Do not collapse the `-security` / `-minor` / `-major` groups.** The file documents why:
with one group per ecosystem a single breaking major holds every security patch behind
it, and a major can slip in under cover of them. OME-736 was exactly that — react and
react-dom security bumps stuck behind an ESLint 10 crash, in a PR quietly carrying a
TypeScript 5 to 7 compiler rewrite. The split is load-bearing.

Three changes that reduce volume without touching it:

1. `weekly` to `monthly` on every `schedule:` block. Safe because groups declaring
   `applies-to: security-updates` are not governed by the version-update schedule and
   still fire on discovery. Biggest single lever.
2. One multi-directory `uv` entry in place of six per-directory entries, using the plural
   `directories:` list. Live proof: #728 and #733 were the same `ruff 0.16.3 -> 0.16.4`
   bump in two directories, with #729 and #775 in the same cycle. VERIFY the plural
   `directories:` key against current Dependabot docs before writing it — it was not
   confirmed at filing time and this change depends on it. If unsupported, ship 1 and 3.
3. Fix the `screamingface-python` group: `/packages/screamingface` declares one group with
   `patterns: ["*"]` and no `applies-to:`, which the file's own header explains defaults
   to version updates. That is the OME-733 fault that made security fixes arrive as nine
   ungrouped PRs. Every other ecosystem was fixed; this one was missed.

Verify: the next Dependabot run produces one grouped uv PR rather than one per directory,
and a security update still arrives grouped and on discovery.

Related: OME-1062 (#774, the one Dependabot PR still open, red).
