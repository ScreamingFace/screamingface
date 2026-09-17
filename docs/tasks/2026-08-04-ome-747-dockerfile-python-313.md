---
id: OME-747
linear_url: https://linear.app/openmined/issue/OME-747/move-aigateway-and-scoreboard-dockerfiles-to-python-313-across-both
status: in_review
type: task
priority: P2
labels: [repo, autonomous, agentic]
created: 2026-08-04
closed:
---

# OME-747 — aigateway + scoreboard Dockerfiles to Python 3.13, and ignore 3.14

Sub-issue of `OME-733`. `OME-737`'s new docker coverage began working within minutes of merging
and immediately opened #489, #490 and #491 — all three repeating the #439 fault `OME-740` closed.

> **Label note (D9):** touches `apps/aigateway` and `apps/scoreboard`, which would normally mean
> an epic plus a sub-issue each. Filed as one `repo` unit — a single mechanical pattern applied
> twice plus one config edit. Flagged rather than silently deviated.

## What those PRs proved

**Grouping cannot pair multi-stage images.** #491 was the direct experiment and it failed: it
moved `python:` alone and left the `ghcr.io/astral-sh/uv` builder behind. `OME-737` had claimed
grouping would at least "make the mismatch visible in one diff" — **too generous, and corrected
in the config**. Dependabot does not treat the uv image as version-bearing at all, so the group
holds exactly one member. No setting can fix this.

**Real drift on two apps.** Both sat on Python 3.12 in both stages with no guard comment, and both
share url4-cloud's exact vulnerable shape — `COPY --from=builder /app /app` entered via
`PATH=/app/.venv/bin`, where the venv is version-keyed. **Worse than url4-cloud:** neither app's
CI builds its image, so a mismatch would surface at deploy rather than in CI.

**3.14 is untested everywhere.** All Python matrices run 3.12/3.13, so merging any of the three
would ship an interpreter no test here exercises.

## Result

Both Dockerfiles on **3.13 across both stages**, each carrying the `INVARIANT:` + `AIDEV-NOTE:`
guard. `python >=3.14` ignored on the three python docker entries — **lift when the CI matrices
gain 3.14**.

Parity **asserted programmatically** (every `FROM` parsed and compared), not eyeballed — eyeballing
is how #439 shipped. `run_gates.py` green for both stacks.

⚠️ **No runtime verification exists for this change** — no Docker daemon locally and neither app's
CI builds its image. `OME-740` had `Smoke both modes` as real proof; this has only the assertion.
Stated plainly rather than implied.

## Follow-up

Neither `aigateway` nor `scoreboard` CI builds its Docker image, so nothing exercises these files.
`url4-cloud` only gained that job because `592e4a89` broke at release time. Worth its own ticket.

Ledger: `docs/work/2026-08-04-OME-747-dockerfile-python-313.md`
