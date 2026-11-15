# Plan — Fidelity Records, the check script, the audit agent, the IFEval calibration (OME-1471)

- Spec: `docs/spec/2026-11-06-OME-1471-benchmark-fidelity.md`. Ticket: OME-1471 (epic OME-1299).
- Ledger: `docs/work/2026-11-06-ome-1471-benchmark-fidelity.md`. One PR, branch
  `OME-1471-benchmark-fidelity` (owner decision 2026-11-06); the three parts below are its order
  of work, not separate PRs.
- Numbers ① to ⑥ are the ticket's Architecture boxes. Every step names its file and the test
  that proves it; RED before GREEN per `sdlc-python`.
- Paths: `E = apps/screamingface-engine`, `R = E/docs/benchmarks-fidelity`.

## Part 1 — spec, plan, glossary, record format, check script

1. `CONTEXT.md` → two glossary entries after Benchmark Saturation: **Fidelity Record**,
   **Fidelity Verdict**. Verify: the `**Term**: / _Avoid_:` shape.
2. `docs/spec/…`, `docs/plan/…` (these files). Verify: every number in the spec header was read
   from the registry today (94 ids, 75 + 18 + 1).
3. Box ⑤, the format: `R/TEMPLATE.md` — the §2.1 front matter with every key present and a
   placeholder value, then the six §2.2 sections with one-line guidance each, the seven
   dimension rows pre-filled, the verdict rule and `COMPARABLE_TOLERANCE` restated in a
   comment. `R/README.md` — what a record is, how to read a verdict, the command that prints
   the live table, how a record is produced (agent → session writes → PR), what makes one
   stale. Verify: the script skips both (test "upper-case stems are not records").
4. Box ②, the script, RED first: `E/tests/unit/test_fidelity_check.py` loads
   `E/scripts/fidelity_check.py` by path (the `test_parity_gate_check.py` idiom) and writes
   the §3.4 table as tests against `tmp_path` records and a hand-built `Declared` mapping:
   fresh · stale on fingerprint · stale on harness_url · both · no record · orphan · parity
   `yes` / `none` / `MISSING` · four malformed shapes · skipped template · offline (`socket.socket`
   patched to raise). Run: all fail with "no such file" / `AttributeError`.
5. GREEN: `E/scripts/fidelity_check.py` per §3.3 — `Record`, `Declared`, `Row`,
   `load_records` (front matter via `yaml.safe_load`, PyYAML is a dev-group dependency and
   ships with the inspect extra), `declared_today` (imports the plugin lazily inside the
   function, so the module loads without the extra), `compare`, `render`, `main`. Stage
   comments ① to ④ in execution order; docstring with the IFEval worked example. Run the new
   tests, then `uv run pytest tests/unit/test_fidelity_check.py tests/unit/test_parity_gate_check.py tests/unit/inspect/test_benchmark_bump.py`
   (the sibling script tests, to confirm the shared idiom still holds).
6. With the extra: `E/tests/unit/inspect/test_fidelity_check_catalogue.py` —
   `importorskip("inspect_ai")`, `importorskip("inspect_evals")`; asserts `declared_today()`
   keys equal `{imported_benchmark(s.key).benchmark.id for s in BENCHMARKS} | {"medxpert"}`
   and that `declared_today()["ifeval"].fingerprint == _FINGERPRINTS["ifeval"]` imported from
   `test_benchmark_fingerprints`. Run with `uv run --isolated --extra inspect pytest <that file>`.
7. `E/justfile` → recipe `fidelity-check *args` beside `benchmark-bump`, same `--isolated
   --extra inspect` shape. Verify by running `just engine fidelity-check` and
   `just engine fidelity-check --markdown` from the repo root: 94 rows, all `no record`,
   exit 0.
8. Gates: `uv run .claude/scripts/run_gates.py screamingface-engine` (ruff, format, pyright,
   layering, pytest) and `run_gates.py repo` (mirror-status gate reads the ledger).
   The new test module needs `# pyright: reportMissingImports=false` only if it imports the
   plugin at module level; the extra-less test does not, so it should not need the directive.
9. Commit this part before starting Part 2, so the script's history is separate from the
   prose that follows.

## Part 2 — the audit agent and the reviewer line

1. Box ③: `.claude/agents/sf-benchmark-fidelity.md`. Front matter like `sf-code-review.md`
   (name, description, tools: Read, Grep, Glob, Bash). Body in this order: the one-paragraph
   mental model (two examiners, one stack of answer sheets); inputs (Benchmark id, optional
   our-side override); the §4.1 rules as a checklist the agent ticks in its report; the §4.2
   reference chain with the exact calls to load our side (`imported_benchmark(key)`, the local
   Task module, MedXpert's definition) and the reference (`importlib.resources` for the
   inspect_evals task; `git clone` + `git checkout <sha>` from `harness_url` into `$SCRATCH`;
   `uv venv` + `uv pip install -e .` in the scratch env); the §4.3 free checks as runnable
   recipes with the IFEval commands as the worked example; the §2.3 verdict rule with
   `COMPARABLE_TOLERANCE`; the §2.4 severities; the output contract (§4.4) with a filled
   skeleton; what the agent never does (write under the repo, call a model, read a key, bump a
   pin, edit a Case). Verify: a dry read by a fresh session against `inspect-gsm8k` produces the
   six sections with no step the reader has to invent.
2. Box ⑥: one line in `.claude/agents/sf-code-review.md` Lane 2, per §4.5. Verify: the
   `## Lane 2` section grows by that one bullet and nothing else.
3. One line each in `E/docs/adding-a-benchmark-manually.md` and
   `E/docs/adding-an-imported-benchmark.md`: the record ships with the onboarding PR or the PR
   body says when it follows. Verify: both files link `apps/screamingface-engine/docs/benchmarks-fidelity/README.md`.
4. Gates: `run_gates.py repo`. Commit.

## Part 3 — the IFEval record and the planted deviation

1. Run the agent on `ifeval` (no override). The session writes `R/ifeval.md` from the report
   without editing its evidence; `audited_at` is the main sha the agent read. Verify:
   `just engine fidelity-check` lists `ifeval` as `fresh`, `parity test: yes`, the other 93 as
   `no record`.
2. Planted deviation per §5: copy `E/src/screamingface_engine_inspect/local_tasks/ifeval/` to
   `$SCRATCH/ours`, change one checker, run the agent with the override. Verify: exactly one
   undeclared `score-changing` deviation naming the checker, bound listed as Case ids, verdict
   `not-comparable`; the environment check line shows no key. The report goes in the PR body
   under a `<details>`; nothing from the scratch copy is committed.
3. Record review: every `match` cell names a command and output lines or two source locations;
   the declared deviation carries bound `2/541` and links the README paragraph; `## Checks run`
   lists the parity test run and the answer-sheet run with their counts.
4. Close in the same PR: ledger Outcome, mirror `docs/tasks/2026-10-05-OME-1471-benchmark-fidelity.md`
   with `status: done` (the ticket was filed 2026-10-05), ticket Scope patched to the one-PR
   delivery with the five spec §1 deviations named for review, ticket close comment at merge
   (commits, gates, the record path, the planted-run evidence), Linear → Done by hand.

## Later (own tickets, on the owner's go)

- The sweep: one record per remaining Benchmark, batched by origin and by shared harness
  (the 75 inspect_evals rows share one reference tree at `v0.20.0`), each batch its own PR
  under the size cap.
- Paid judge parity runs where records recommend them.
- Any deviation found that should be fixed.
