---
id: OME-775
linear_url: https://linear.app/openmined/issue/OME-775/register-draco-ifeval-and-healthbench-in-the-scoreboard-benchmark
status: In Review
priority: P1
labels: [scoreboard, agentic, autonomous]
created: 2026-08-11
closed:
---

# Register DRACO, IFEval and HealthBench in the Scoreboard benchmark catalogue

Scoreboard's deployed registry seeded only the legacy `hle` / `livetruth` / `livetruth-latest`
demo entries, so the Leaderboard v1 catalogue rendered no real board and a Client submission for
a real benchmark failed with `unknown_leaderboard` **after** a successful Engine evaluation — the
failure landing at the end of the user's run rather than the start. Launch-critical: verified
against the live dev board on 2026-08-16, which advertised no real benchmark.

Registers the three canonical flat identities the Engine now advertises after OME-836/837/838 —
`draco`, `ifeval`, `healthbench-worst30` — each carrying the Engine's computed `REVISION`, and
gives the board the revision identity needed so scores measured against incompatible
dataset/protocol revisions are not ranked against each other.

The revision was already arriving on every submission, untyped, inside the free-form `metadata`
dict, so this promotes an existing wire value rather than waiting on any upstream producer.

Owner decisions: build the full ticket including revision partitioning (not seeding alone); keep
the legacy demo entries registered alongside; the revision joins the dedup identity hash with no
backfill.

Spec: `docs/spec/2026-08-16-OME-775-flat-benchmark-registration.md`
Plan: `docs/plan/2026-08-16-OME-775-flat-benchmark-registration.md`
Ledger: `docs/work/2026-08-16-OME-775-register-flat-benchmarks.md`
