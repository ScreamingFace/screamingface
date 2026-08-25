# OME-986 — Retire the legacy news demo benchmarks

**Ticket:** [OME-986](https://linear.app/openmined/issue/OME-986/retire-the-legacy-news-demo-benchmarks-from-the-scoreboard-catalogue)
· **Ledger:** `docs/work/2026-08-25-OME-986-retire-news-benchmarks.md`
· **Stack:** scoreboard · **Date:** 2026-08-25

## 1. Problem

`hle`, `livetruth` and `livetruth-latest` are leftovers from the previous SF project. They are
still advertised on the public catalogue, on the board being handed to internal testers this week.

> *"still need to remove the old news benchmark as they are just old leftovers from the previous
> SF project"* — Irina, `#scream-dev`, 2026-08-25 07:18

## 2. Established facts

Verified against `origin/main` and the live dev board; none assumed.

| # | Finding | Evidence |
|---|---|---|
| F1 | **Seeding never deletes.** `seed_benchmarks` only registers and updates, and no delete path exists anywhere in the codebase | `seed.py`; `register_benchmark` is `update_or_create` |
| F2 | So removing the three from `seedBenchmarks.benchmarks` stops them being re-created and changes nothing a reader sees — the rows persist and are still served | F1 + `routes/leaderboard.py::list_benchmarks` |
| F3 | All three are empty on the live board: 0 entries, 0 baselines | `GET /v1/leaderboard/{id}` for each |
| F4 | `Score.benchmark` and `Baseline.benchmark` are both `on_delete=RESTRICT`, so deletion is refused while anything references them | `models/score.py:107`, `models/baseline.py:35` |
| F5 | Absent `revision` is the clean discriminator — the other five benchmarks on the board all carry Engine revisions | live `GET /v1/benchmarks` |
| F6 | The deployed values are **not** this repo's chart defaults: the chart lists all three and sets `engineUrl: ""`, yet the live board serves five Engine-published benchmarks | `charts/scoreboard/values.yaml` vs live API |

F3 + F4 together are why this is cheap **today** and not later: nothing blocks deletion right now,
and that stops being true the moment a tester submits against one of them.

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | A **read-only-by-default operator module**, not a migration and not raw SQL | Owner call. Matches the `seed.py` / `import_baselines.py` / `export_private_submissions.py` precedent: `main(argv)`, no HTTP surface, run where database credentials already are. Reviewable and repeatable. |
| D2 | It **refuses** when any score or baseline references the benchmark | F4 makes the database refuse anyway; the point is to report *which* rows block it, rather than surface an `IntegrityError` traceback at an operator. Never destroys submissions. |
| D3 | Scope is exactly the three revision-less ids | Owner call. Precisely what Irina named, and precisely the set F5 identifies. The five Engine-published benchmarks are a different conversation, and retiring one of those would need Engine-side work too. |
| D5 | The module is named `retire_benchmark`, and its docstring states plainly that it performs an irreversible DELETE | Owner call, 2026-08-25. Keeps the language the ticket and Irina used. The naming risk — "retire" reading as a reversible state the row does not get — is answered in the docstring rather than the filename. |
| D6 | Deletion requires an explicit `--yes` | Owner call. Every other operator module here is additive or read-only; this is the first that destroys, so the destructive step is opt-in rather than the default outcome of a correct-looking command. |
| D7 | An unknown benchmark id is refused with a non-zero exit | Owner call. "Already gone" and "you typed it wrong" must not look identical to someone cleaning up a live board. Matches `export_private_submissions`, which exits 2. |
| D4 | Also remove the three from the chart seed list | Otherwise the next deploy recreates what the module just removed. Necessary but, per F2, not sufficient on its own. |

## 4. Explicitly rejected

**Teaching the seed job to prune any benchmark absent from its list.** During an Engine catalogue
outage `published_rows` is empty, so the prune would delete every Engine-published benchmark. That
is the exact failure shape review caught in `OME-894` — a transient outage silently changing board
state — and it would be strictly worse here, because the loss is not recoverable by re-running.

**A data migration.** It re-runs against every fresh database including local dev, is hard to
reverse, and bakes a one-off cleanup into schema history.

**Raw SQL by hand.** Fastest today, but unreviewable, unrepeatable, and it has to be redone on any
fresh environment.

## 5. Owner action, not code

Per F6 the config half of this may land nowhere. **Confirm with Stephen which values file actually
feeds the deployed seed job** — the same conversation as the `authMode` question on `OME-894`.

The module itself is unaffected: it reads the database directly, so it works whichever file is
deployed.

## 6. Acceptance

- The module deletes a benchmark that has no scores and no baselines, **only** when `--yes` is given.
- Without `--yes` it reports what it would do and deletes nothing.
- It refuses, naming the blocker, when either exists — and the benchmark survives.
- An unknown benchmark id is refused rather than reported as success.
- The three ids are gone from the chart seed list.
- `GET /v1/benchmarks` no longer advertises them once the module has run.
- Full gates green.
