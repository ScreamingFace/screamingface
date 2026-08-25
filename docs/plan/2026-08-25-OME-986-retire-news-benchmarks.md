# OME-986 — Implementation plan

**Spec:** `docs/spec/2026-08-25-OME-986-retire-news-benchmarks.md`
· **Ledger:** `docs/work/2026-08-25-OME-986-retire-news-benchmarks.md`
· **Branch:** `OME-986-retire-news-benchmarks` · **Stack:** scoreboard

Gates after every step:
`uv run .claude/scripts/run_gates.py scoreboard --base origin/main`

`tortoise-dev` applies (queryset + delete semantics), though no model or migration changes here.

## Ordering principle

The refusal path is built and tested **before** the deletion path. This module's only real risk is
destroying submissions, so the guard exists before the thing it guards.

---

### Step 1 — refuse to retire a benchmark that is referenced

**RED:** `retire_benchmark` raises a typed refusal when the benchmark has a score; likewise for a
baseline; the message names which of the two blocks it and how many rows; **the benchmark still
exists afterwards**.

**GREEN:** `scoreboard/retire_benchmark.py` with `collect_blockers(benchmark_id)` returning the
counts, and a refusal raised from them. Nothing deletes yet.

**Why first:** `on_delete=RESTRICT` means the database refuses anyway (spec F4). The value added
here is telling an operator *what* blocks it instead of surfacing an `IntegrityError` traceback.

---

### Step 2 — refuse an unknown benchmark

**RED:** an unregistered id raises rather than reporting success.

**GREEN:** existence check, mirroring `export_private_submissions.collect_submissions`.

**Why:** "nothing to remove" and "you typed the id wrong" must not look identical to an operator
cleaning up a live board.

---

### Step 3 — delete an unreferenced benchmark

**RED:** a benchmark with no scores and no baselines is deleted and disappears from
`list_benchmarks()`; a second run reports it unknown rather than crashing.

**GREEN:** the delete, reachable only past Steps 1 and 2.

---

### Step 4 — the CLI wrapper

**RED:** `main(["--benchmark", "hle"])` exits non-zero on a refusal and zero on success; it prints
what it did.

**GREEN:** `_build_parser` / `main(argv)`, shaped like `seed.py` and
`export_private_submissions.py`. `parser.error` for refusals, so the exit code is non-zero without
a traceback.

---

### Step 5 — chart seed list

Remove `hle`, `livetruth` and `livetruth-latest` from
`apps/scoreboard/charts/scoreboard/values.yaml`. Without this the next deploy recreates them
(spec F2). Existing seed tests must stay green — this changes deployment data, not behaviour.

---

### Step 6 — close out

Ledger Outcome · conventional commits with `Refs: OME-986` · PR · green CI · squash-merge · close
comment per the card's `close_template` · close the `docs/tasks/` mirror.

## Verification

1. Gates green.
2. Against a scratch database: seed a benchmark **with** a score, run the module, confirm it
   refuses and the benchmark survives. Then an empty one, confirm it goes and
   `GET /v1/benchmarks` stops advertising it.
3. `git grep -n 'livetruth\|"hle"' apps/scoreboard/charts` returns nothing.

## Risks

| Risk | Handling |
|---|---|
| Destroying real submissions | Step 1 lands before Step 3; RESTRICT is a second line of defence, not the first |
| Deleting the wrong benchmark | Exact id only, no globbing, no "delete everything without a revision" shortcut |
| Config change landing nowhere | Not a code risk — spec §5, needs Stephen to confirm which values file is deployed |

## Out of scope

The five Engine-published benchmarks · any seed-job pruning behaviour (spec §4) · `OME-894` ·
anything touching the Engine catalogue.
