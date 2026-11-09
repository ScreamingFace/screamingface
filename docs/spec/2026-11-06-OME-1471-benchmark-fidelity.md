# Spec — a Fidelity Record per Benchmark says which published number ours is comparable to

- Status: draft for owner review (one PR, owner decision 2026-11-06). Design decisions D1 to D7 on the ticket (owner,
  2026-10-05); the six deviations in §1 are this spec's, for owner review on this PR.
- Component: `apps/screamingface-engine` (the check script, the records under its `docs/`). The
  agent lives at the repo root (`.claude/agents/`), like `sf-code-review`.
- Ticket: [OME-1471](https://linear.app/openmined/issue/OME-1471/benchmark-fidelity-agent-checking-a-benchmark-against-its-paper-and).
  Parent epic: OME-1299. Was blocked by OME-1455 (Benchmark Provenance), Done 2026-10-06.
- Ledger: `docs/work/2026-11-06-ome-1471-benchmark-fidelity.md`.
- Pinned to: main `3499efbb8`, inspect-evals 0.20.0 (`apps/screamingface-engine/pyproject.toml`).
  Catalogue on that day: 94 Benchmarks (75 `origin="inspect_evals"`, 18 local Tasks with
  `origin="screamingface"`, plus the MedXpert folder).
- Glossary: Fidelity Record, Fidelity Verdict (`CONTEXT.md`, this PR). The ticket carries the
  Before/After, Data Flow, Failure modes and Architecture diagrams; this spec does not repeat
  them. It adds the exact shapes, the rules a test can check, and the delivery order.

## TLDR

A Benchmark is one exam: a fixed set of Cases plus the Grading that marks them. Every Benchmark we
serve is a translation of someone else's exam: the paper describes it, the authors' original
harness produced the published number, and for an Imported Benchmark inspect_evals is a second
translation between the paper and us. Benchmark Provenance (OME-1455) already pins the paper and
the harness on every row. Nothing yet says whether our translation gives the same marks.

A **Fidelity Record** is one reviewed markdown file per Benchmark, `apps/screamingface-engine/docs/benchmarks-fidelity/<id>.md`,
that answers that: every place the exam could differ (seven dimensions), the evidence checked
for each, every deviation found, and one **Fidelity Verdict**: `comparable-to-paper`,
`comparable-to-inspect`, `not-comparable` or `unverified`. The record also carries a fingerprint
of what the verdict rested on, so a later change to our exam or to the pinned harness turns the
record stale.

Three pieces:

1. **The record format** (§2): front matter a script can read, a body a reviewer can read.
2. **The check script** (§3): `fidelity_check.py`, run by a dev, offline. For every Benchmark in
   the catalogue it prints `fresh`, `stale` (with the old and new value), or `no record`, plus
   whether a parity test exists. Deterministic; no model.
3. **The audit agent** (§4): `sf-benchmark-fidelity`, run on one Benchmark at a time. Read-only
   on the repo, runs the pinned harness in a throwaway environment with no keys, makes no model
   call, and returns the record body. The calling session writes the file; a PR reviews it.

Rules that hold:

- **A verdict never claims more than its evidence.** Every dimension in a record carries either
  evidence (a command and its output, or the two source lines compared) or `not applicable` /
  `unchecked` with a reason. A record with an evidence-free `match` is a review comment (F5).
- **An audit that cannot finish says `unverified` and why.** Never a silent pass (F1, F2).
- **Nothing paid runs.** Where only a judge run can settle a question, the record recommends it;
  the owner runs it (F6).
- **Nothing here changes a Benchmark.** No Case, Grading or Benchmark Revision moves. A deviation
  found gets its own ticket on the owner's ask.

## 1. Deviations from the ticket, for owner review

| | Ticket says | This spec does | Why |
|---|---|---|---|
| S1 | D2: fingerprint = Benchmark Revision + harness commit + inspect_evals version + paper version | fingerprint = the **computed** fingerprint + the full `harness_url`; inspect_evals version and arXiv version are recorded as evidence, not compared | The published revision is frozen (owner, 2026-10-22) and does not move on a grading fix, so it cannot detect a change. The computed fingerprint (`imported_benchmark(key).fingerprint`, `medxpert.FINGERPRINT`) hashes our Cases, scorer, pins **and** `inspect-evals==0.20.0`, so one value covers three of the ticket's four. No declaration holds an arXiv version (the importer strips `vN`), so there is nothing to compare it against. |
| S2 | Box ⑤: an index with a verdict table | `README.md` explains the records and names the command; the **live** table is the check script's output (`--markdown` prints it) | A hand-kept table drifts from the records the day someone forgets it; the script reads the records, so its table cannot. |
| S3 | Tasks: "Spec in `docs/spec/`, then plan in `docs/plan/`" as the first step; D7 implies the tooling and the record ship in separate PRs | one PR carries spec, plan, record format, check script, agent, reviewer line and the IFEval record | Owner decision 2026-11-06. The only code is the script and its tests (~400 lines); the rest is prose. Design lives on the ticket, no spec-only PR (owner rule since 2026-10-22). |
| S4 | TLDR: "Hand-built ones (IFEval, HealthBench, DRACO, GDPval, MedXpert, ContractEval)" | the two kinds are `origin="screamingface"` (18 local Tasks + MedXpert) and `origin="inspect_evals"` (75) | OME-1527 moved every hand-built Benchmark but MedXpert into the inspect plugin as a local Task. The audit path is the same for both origins; only the reference chain differs (§4.2). |
| S5 | Acceptance: the planted deviation yields "exactly one undeclared `score-changing` deviation" | IFEval already carries one **declared** deviation (official keys 1122 and 1129 graded against the literal character; `local_tasks/ifeval/README.md`), so the calibration record lists one declared entry, and the planted run must report exactly one **undeclared** entry **in addition** | The ticket was written before that README; the invariant is unchanged (declared entries are listed, not findings). |
| S6 | Box ⑤: records in repo-root `docs/benchmarks-fidelity/` | records in `apps/screamingface-engine/docs/benchmarks-fidelity/` | Owner, 2026-11-09. The records describe Engine Benchmarks and the check script lives in the Engine; an app script reading repo-root `docs/` would cross the app boundary (today only the SDK-notebook check does, flagged as the exception). Repo-root `docs/` is SDLC artifacts; the Engine's `docs/` already holds the Benchmark how-tos that will point at the records. |

## 2. The Fidelity Record

One file per Benchmark, named by the catalogue id: `apps/screamingface-engine/docs/benchmarks-fidelity/ifeval.md`,
`apps/screamingface-engine/docs/benchmarks-fidelity/inspect-gsm8k.md`, `apps/screamingface-engine/docs/benchmarks-fidelity/medxpert.md`.
`TEMPLATE.md` and `README.md` sit beside them and are not records (the script skips every
upper-case file name).

### 2.1 Front matter — what the script reads

```yaml
---
benchmark: ifeval                      # the catalogue id, equal to the file stem
origin: screamingface                  # screamingface | inspect_evals, copied from the declaration
verdict: comparable-to-paper           # §2.3
verdict_reason: ""                     # required non-empty for not-comparable and unverified
audited: 2026-11-06                    # ISO date the audit ran
audited_at: 3499efbb8                  # main sha the audit read
fingerprint:
  benchmark: ada07458a23c55ab          # the COMPUTED fingerprint, never the published revision
  harness_url: https://github.com/josejg/instruction_following_eval/tree/0c495b2f95155e8b10acb919ae283bfb4d5be6e2
references:                            # evidence for the reader; the script does not compare these
  paper: https://arxiv.org/abs/2311.07911v1
  inspect_evals: 0.20.0                # the installed version the audit ran against
parity_test: tests/unit/inspect/test_local_task_ifeval_parity.py   # Engine-relative path, or `none`
parity_test_reason: ""                 # required non-empty when parity_test is none
---
```

Rules a test can check (§3.4 tests them):

- `benchmark` equals the file stem; a mismatch is a malformed record.
- `verdict` is one of the four words; `verdict_reason` non-empty when it is `not-comparable` or
  `unverified`.
- `fingerprint.benchmark` is 16 lower-case hex; `fingerprint.harness_url` is the declaration's
  string, byte for byte.
- `parity_test` is a path relative to `apps/screamingface-engine/` (the records' own app) that exists, or the literal
  `none` with `parity_test_reason` non-empty ("judge-graded, parity needs a paid run" is a valid
  reason; "not written yet" is also valid and is what the sweep will show).
- Any missing key, wrong type or unknown verdict is **malformed**: the script names the file and
  the key and exits 1. A malformed record never reads as `fresh`.

### 2.2 Body — what the reviewer reads

Fixed section order, so two records compare side by side:

1. `## Verdict` — one paragraph: the verdict, the number it is comparable to (the paper's
   headline, or inspect's), and the one sentence that carries it.
2. `## Dimensions` — one table, seven rows in this order, columns
   `dimension | status | severity | bound | evidence`:

   | dimension | what is compared |
   |---|---|
   | dataset | source, revision, split, row count, subset / exclusions, row order where it matters |
   | prompt | template, system message, few-shot examples, how Case fields are rendered; bytes the Candidate receives |
   | answer extraction | how a mark-able answer is pulled from the reply (regex, letter, last number, JSON field) |
   | metric | the per-Case mark rule (exact match, normalised match, checker code, pass@k) |
   | roll-up | how per-Case marks become the headline (mean, pooled, per-group then mean, k attempts) |
   | judge | model, prompt bytes, parameters, how the judge's reply is parsed; `not applicable` when no judge |
   | sampling | temperature, max tokens, seed, attempts per Case, stop sequences, anything that changes what the Candidate produces |

   `status` is `match`, `deviation`, `not applicable` or `unchecked`. `unchecked` carries its
   reason in `evidence`. `match` **must** carry evidence; an evidence-free `match` is a review
   comment, not a record.
3. `## Deviations` — one `### D<n> — <plain name>` per `deviation` row, each stating: declared
   or undeclared (declared = a `# NAMED DEVIATION` line on the row, or a README paragraph the
   row links, for an `origin="screamingface"` Benchmark); where (our file and line, theirs);
   what differs; `severity` and `bound` (§2.4); evidence.
4. `## Checks run` — every command the audit executed, in order, with the environment used and
   the output lines that carry the result. This is what makes F5 reviewable.
5. `## Recommended paid runs` — what a judge run would settle, Case count, which judge; `none`
   when nothing is pending.
6. `## Upstream notes` — places where the original harness and the paper disagree (D3: the
   harness wins; the disagreement is recorded, not counted as ours), and places where
   inspect_evals disagrees with the harness (the `comparable-to-inspect` evidence).

### 2.3 Verdicts

| verdict | meaning | rule |
|---|---|---|
| `comparable-to-paper` | our headline number can sit beside the paper's | every dimension is `match` or `not applicable`, or a `deviation` whose severity is `cosmetic` or `score-changing` with a stated bound, and the bounds against the **original harness** sum to at most `COMPARABLE_TOLERANCE` |
| `comparable-to-inspect` | ours matches inspect_evals; inspect_evals differs from the paper beyond tolerance | same rule as above against **inspect_evals**, and the inspect-vs-harness gap is recorded in `## Upstream notes` with its own bound; Imported Benchmarks only |
| `not-comparable` | the number is reproducible but not the paper's | any `score-changing` deviation without a bound, or bounds summing above tolerance, or a published number produced by a different process by design (vendor- or human-run grading, a judge model other than the one the paper's number used) |
| `unverified` | the audit could not settle it | any of `prompt`, `answer extraction`, `metric`, `roll-up` is `unchecked`, or a `possibly-score-changing` deviation is open (judge agreement pending a paid run) |

`COMPARABLE_TOLERANCE = 0.005` of the headline metric: half a percentage point, because papers
and our Leaderboard report one decimal, so a deviation that cannot move the first decimal cannot
change what a reader concludes. One named constant, in `TEMPLATE.md` and the agent file; a
judgment call like `SATURATION_HEADROOM`.

Worked example, IFEval: one declared deviation, two of 541 Cases can grade differently, bound
`2/541 = 0.0037 ≤ 0.005`, every other dimension `match` with evidence → `comparable-to-paper`.
Had the deviation touched 3 Cases (`0.0055`), the verdict would be `not-comparable` with the
reason "declared deviation on 3 Cases exceeds tolerance", and the owner would decide whether to
fix the Cases or accept the verdict.

### 2.4 Severities and bounds

| severity | meaning | `bound` |
|---|---|---|
| `cosmetic` | cannot change any Case's mark (a log line, a metric's name, whitespace the scorer strips) | `0` |
| `score-changing` | can change marks | `N/case_count` when the affected Cases are enumerable (IFEval's two rows), else `unbounded` |
| `possibly-score-changing` | cannot be bounded without a run that costs money (a judge model's behaviour) | `unknown` + the recommended run |

A bound is a claim and carries evidence like any other cell: the list of affected Case ids, or
the command that enumerated them.

## 3. The check script

`apps/screamingface-engine/scripts/fidelity_check.py`, run as
`just engine fidelity-check` → `uv run --isolated --extra inspect python scripts/fidelity_check.py [--markdown]`
(the same shape as `benchmark-bump`; `--isolated` keeps the inspect extra out of `.venv`).

### 3.1 What it reads

- **Records:** every `docs/benchmarks-fidelity/*.md` under the Engine root whose stem is not upper-case, front matter
  per §2.1.
- **Declarations:** the catalogue. For every `BenchmarkSpec` in `screamingface_engine_inspect.benchmarks.BENCHMARKS`,
  `imported_benchmark(spec.key)` gives the catalogue id (`.benchmark.id`), `.fingerprint`,
  `.benchmark.harness_url` and `.benchmark.origin`; plus MedXpert from
  `screamingface_engine.benchmarks.medxpert.definition` (`MEDXPERT.id`, `FINGERPRINT`,
  `MEDXPERT.harness_url`). This is exactly what `test_benchmark_fingerprints.py` does, so the
  two can never disagree on what "the fingerprint" is.
- Nothing else. **No network**: no socket is opened; the test asserts it by patching
  `socket.socket` to raise.

### 3.2 What it prints

One row per catalogue id, sorted, plus one row per orphan record:

| column | values |
|---|---|
| benchmark | the catalogue id |
| status | `fresh` · `stale` · `no record` · `orphan record` (a record whose id is not in the catalogue) |
| moved | empty, or `fingerprint abcd…→ef01…`, or `harness_url` (old and new URLs on the next lines), or both |
| verdict | the record's verdict, or empty |
| audited | the record's date, or empty |
| parity test | `yes` · `none: <reason>` · `MISSING <path>` (the record names a file that does not exist) |

`--markdown` prints the same as a GitHub table (this is the index table of S2). A final line
counts each status. Exit code `0` when every record parsed; `1` when any record is malformed
(each named with file and key) or `MISSING` (a parity path that does not exist). `stale` and
`no record` are findings for a human, not errors, so they leave the exit code at `0`: the
script is a report, not a gate (ticket Scope: Out → CI gating).

### 3.3 Module shape, so the pure part tests without the inspect extra

```python
@dataclass(frozen=True)
class Record:          # parsed §2.1 front matter
    benchmark: str; origin: str; verdict: str; verdict_reason: str; audited: str; audited_at: str
    fingerprint_benchmark: str; fingerprint_harness_url: str
    parity_test: str | None; parity_test_reason: str

@dataclass(frozen=True)
class Declared:        # one catalogue row today
    benchmark: str; origin: str; fingerprint: str; harness_url: str | None

@dataclass(frozen=True)
class Row:             # one output line
    benchmark: str; status: str; moved: tuple[str, ...]; verdict: str; audited: str; parity: str

def load_records(records_dir: Path, engine_root: Path) -> tuple[dict[str, Record], list[str]]   # records, malformed messages
def declared_today() -> dict[str, Declared]          # the only function that imports the plugin
def compare(records: Mapping[str, Record], declared: Mapping[str, Declared]) -> list[Row]
def render(rows: Sequence[Row], *, markdown: bool) -> str
def main(argv: Sequence[str]) -> int
```

`compare` and `load_records` are pure and tested with `tmp_path` fixtures in the extra-less
suite; `declared_today` is covered by one `importorskip("inspect_evals")` test that asserts
every `BENCHMARKS` key plus `medxpert` appears exactly once and that `ifeval`'s declared
fingerprint equals `_FINGERPRINTS["ifeval"]` from the fingerprint test module.

### 3.4 Tests (`tests/unit/test_fidelity_check.py`, extra-less; `tests/unit/inspect/test_fidelity_check_catalogue.py`, with the extra)

| test | protects |
|---|---|
| a record whose fingerprint and harness_url equal today's → `fresh` | the happy path |
| record fingerprint ≠ today's → `stale`, `moved` names both values | F3: our exam changed after the audit |
| record harness_url ≠ today's → `stale`, `moved` names both URLs | F4: a new harness pin |
| both differ → `moved` lists both | one line per changed value |
| a catalogue id with no file → `no record` | F7 |
| a file whose id is not in the catalogue → `orphan record` | a renamed Benchmark leaves no ghost verdict |
| `parity_test: none` with a reason → `none: <reason>`; a path that exists → `yes`; a path that does not → `MISSING` and exit 1 | the "no parity test" column is honest |
| missing key / unknown verdict / stem ≠ `benchmark` / `unverified` without a reason → malformed, file and key named, exit 1, never `fresh` | a broken record cannot read as a good one |
| `TEMPLATE.md` and `README.md` are skipped | the template is not a record |
| `socket.socket` patched to raise → `main` still returns | offline by construction |
| with the extra: `declared_today()` keys == `{spec.key → id}` ∪ `{medxpert}`, and `ifeval` fingerprint == the golden literal | the script and the fingerprint test agree on what a fingerprint is |

## 4. The audit agent

`.claude/agents/sf-benchmark-fidelity.md`. Tools: Read, Grep, Glob, Bash. Invoked by a session
with one Benchmark id and, optionally, an **our-side override** path (a scratch copy of our
Benchmark's grading code, used by the planted-deviation calibration and by nothing else).

### 4.1 Rules the agent file states

- **Read-only on the checkout.** It never writes under the repo; every file it creates lives
  under one scratch folder it names at the start (`$SCRATCH`), deleted at the end. It returns
  the record body (§2.2) and the front-matter values (§2.1) as its report; the calling session
  writes `apps/screamingface-engine/docs/benchmarks-fidelity/<id>.md`.
- **No keys, no model.** Every command that runs third-party code runs as
  `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" …`, and before the first
  such command the agent prints `env | grep -iE 'key|token|secret'` and requires it empty. It
  never calls a model, a gateway or a provider; a judge question becomes a recommended paid run.
- **Harness over paper (D3).** When the paper and the original harness disagree, the harness is
  the reference and the disagreement goes to `## Upstream notes`.
- **Declared is not a finding (D4).** A `# NAMED DEVIATION` line on the row, a `named_deviations/`
  scorer, `dropped_scorers`, `excluded_sample_ids`, or a README paragraph the row links, makes
  the deviation declared: listed in `## Deviations`, counted in the bound, not a finding.
- **Every cell has evidence (F5).** A `match` names the command and the comparing output lines,
  or the two source locations compared. Reading code is evidence for `dataset`, `judge` and
  `sampling`; for `prompt`, `answer extraction`, `metric` and `roll-up` the free checks of §4.3
  are required where the harness installs, and `unchecked` with the reason where it does not.

### 4.2 The reference chain

| our origin | references, in order | what `comparable-to-inspect` means |
|---|---|---|
| `inspect_evals` | the inspect_evals task at the pinned version (installed, `importlib.resources`), the original harness at `harness_url`, the paper | ours == inspect_evals, inspect_evals ≠ harness beyond tolerance |
| `screamingface` | the original harness at `harness_url`, the paper | not applicable; the verdict is against the harness |

### 4.3 The free checks

1. **Prompt bytes.** Render every Case (or the first 50 and every 50th when rendering is slow)
   through our Case Preparation and through the reference's own prompt path; compare bytes.
   The Candidate's input is what counts; Grading Material (instruction lists, gold) is compared
   under `dataset`, not here.
2. **Answer sheets.** For each Case build the same stack of pre-written answers: the gold as
   written; the gold in the formats the harness's extractor documents (`C`, `(C)`,
   `The answer is C.`); one wrong answer; the empty answer; and every real reply recorded in our
   goldens for that Benchmark where they exist. Run every sheet through our scorer and the
   reference's; any Case where the marks differ is a `deviation` with the Case ids as its bound.
   On the full official row set when the scorer is deterministic (D6).
3. **Roll-up.** Feed one fixed vector of per-Case marks (all 1, all 0, alternating, and the
   marks from step 2) into our aggregator and the reference's; compare the headline.
4. **Judge.** Byte-compare the judge prompt and the parsing of the judge's reply; compare the
   pinned model and parameters with the ones the paper's number used. Same model and prompt →
   `possibly-score-changing`, recommend the paid run; a different model → `not-comparable` by
   rule (§2.3), because the examiner differs.

### 4.4 Output

The agent returns one markdown document: the front-matter block of §2.1 with every value filled
(`audited_at` is `git rev-parse --short HEAD`), then the six sections of §2.2. It computes the
verdict by the §2.3 rule and shows the arithmetic of the bound in `## Verdict`.

### 4.5 One line in `sf-code-review` Lane 2

After the "manually onboarded benchmark cites its paper and its original harness" rule: *a PR
that onboards a Benchmark ships its Fidelity Record (`apps/screamingface-engine/docs/benchmarks-fidelity/<id>.md`), or
states in its body why the record follows (`sf-benchmark-fidelity` is the auditor; this lane
only asks for the file)*. The two Lane 2 rules stay where they are; the new agent links to them
and never copies them.

## 5. Calibration on IFEval

Expected outcome, from what is already known: `dataset` match (541 rows, `google/IFEval` at
`966cd895` cross-checked against the vendored official file; official key 2785's prompt
difference is already resolved in the official file's favour); `prompt` match (the prompt is sent
untouched); `answer extraction` not applicable (the checker reads the whole reply); `metric`
match on 539 of 541 and one declared deviation on keys 1122 and 1129 (bound `2/541`);
`roll-up` match (the four published numbers, pooled instruction accuracy); `judge` not
applicable; `sampling` match or a deviation to record (the paper does not fix a temperature;
record what both sides do). Verdict `comparable-to-paper`. The record's `parity_test` is
`tests/unit/inspect/test_local_task_ifeval_parity.py`.

**Planted deviation.** Copy `local_tasks/ifeval/` to `$SCRATCH/ours`, alter one checker in the
vendored `instructions.py` (for example let `CommaChecker` accept one comma), and run the agent
with the our-side override pointing at the copy. Pass: the report lists exactly two deviations,
the declared one on keys 1122/1129 and one **undeclared** `score-changing` entry naming
`CommaChecker` with the affected Case ids as its bound, and the verdict is `not-comparable`
(the planted bound exceeds tolerance). The planted run's report is attached to the PR as evidence
and is not committed as a record. It goes in the PR body under a collapsed block.

## 6. Delivery

One PR, branch `OME-1471-benchmark-fidelity`, in this order so each step has what it needs:
glossary → spec + plan → `apps/screamingface-engine/docs/benchmarks-fidelity/README.md` + `TEMPLATE.md` → the check
script with its tests (RED first) and the `just engine fidelity-check` recipe → the agent file,
the Lane 2 line, one line in each onboarding doc → the agent run on IFEval and the record →
the planted-deviation run (evidence in the PR body) → ledger, mirror, ticket Scope patched. The
first `just engine fidelity-check` run after the record lists `ifeval` as `fresh` and the other
93 as `no record`. The sweep of those 93 is its own later ticket (D7).

## 7. Acceptance (test-checkable)

- `just engine fidelity-check` against main lists every catalogue id (94 on 2026-11-06, counted
  from the registry, not typed) as `no record`, opens no socket, exits 0.
- A fixture record carrying an old fingerprint prints `stale` with both values; one carrying a
  parity path that does not exist prints `MISSING` and exits 1; one missing `verdict_reason` on
  `unverified` is named as malformed and exits 1.
- The IFEval record covers all seven dimensions, each `match` with evidence, `not
  applicable` or a declared deviation with bound `2/541`; the verdict is `comparable-to-paper`;
  the script reports it `fresh`.
- The planted run reports exactly one undeclared `score-changing` deviation naming the altered
  checker, and the agent's environment check shows no key.
- `sf-code-review` Lane 2 carries the one-line rule.

## 8. Known limitations of this design

- **Stale means our declared references moved, not upstream.** A harness bug fix on GitHub or a
  new arXiv version is invisible until someone bumps `harness_url` or the inspect pin; accepted
  so the check stays offline (ticket limitation 1).
- **Judge-graded Benchmarks stop at bytes.** Same prompt, same pinned model, and still the
  verdict is `unverified` until the owner runs the recommended paid parity; a different judge
  model is `not-comparable` by rule, which will be the common case for HealthBench-style exams
  (the paper's grader was a vendor model we do not run).
- **The verdict is model judgment with evidence, reviewed by a human in a PR.** It is not a CI
  gate; the check script only says whether the judgment is current.
- **Third-party harness code runs on the dev's machine.** Pinned, in a throwaway environment
  with no keys, but not a sandbox; a hostile harness can waste a scratch folder and read what
  the user can read.
- **The tolerance is a judgment call.** `0.005` matches one-decimal reporting; a Benchmark whose
  paper reports two decimals would need its own line in the record, not a change to the
  constant.
- **`origin="screamingface"` Benchmarks declare deviations in prose.** No field holds them, so
  the record's `## Deviations` and the README paragraph can drift; revisit if a record and a
  README ever disagree.
