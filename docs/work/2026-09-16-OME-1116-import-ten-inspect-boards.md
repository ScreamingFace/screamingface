---
ticket: OME-1116
stack: screamingface-engine
status: in_progress
started: 2026-09-16
finished:
---

# OME-1116 — Import ten single-shot inspect_evals benchmarks into the catalogue

## Intent

Turn benchmark import into a data operation: a board becomes one `SnapshotSpec` row +
one `BoardSpec` row (no per-board Python module — owner decision 2026-09-16, which
closed OME-1115's #955/#956 unmerged), then push gsm8k + mmlu (the OME-1115 proof
boards, re-landed as rows) and ten new single-shot boards through the row machine.
Also absorbs OME-1115's docs close (spec §7 amendment, ledger/mirror), which rode the
closed #956.

## Planned changes (stacked PRs, planned up front per the ≤500-line rule)

**PR A1 — the row machine:** `boards.py` (BoardSpec + empty BOARDS + generic
assembler/installer), the owner-approved conformance amendment
(`test_benchmark_deployment.py`: installer-function `ASSET_BUNDLE_ID` first),
`test_inspect_single_shot.py` (factory suite, probe boards), this ledger + mirror.

**PR A2 — gsm8k row:** the check-surface handler (`single_shot.py`, from closed
#955), the gsm8k `BoardSpec` row, `test_inspect_gsm8k_board.py`, the declaration
roster amendment.

**PR A3 — mmlu row + OME-1115 docs close:** the mmlu row, `test_inspect_mmlu_board.py`,
spec §7 two-board amendment, OME-1115 ledger Outcome + mirror close.

**(superseded plan below, kept for context)**

**PR A — the row machine + the two proof boards (rows):**
- `apps/screamingface-engine/src/screamingface_engine_inspect/boards.py` — `BoardSpec`
  dataclass (title/description/focus/dataset_url · scorer as dotted `"module:attr"`
  reference + kwargs · `with_check_surface` · `multiple_correct`) + `BOARDS` table
  (gsm8k, mmlu rows) + generic installer factory stamping `ASSET_BUNDLE_ID` on the
  installer FUNCTION + `imported_board(key)` accessor + looping `board_registrations()`.
  Revision pins derive from the board's `SnapshotSpec` (dataset/config/split/revision
  + shuffle seed) — no pin duplication.
- `tests/unit/test_benchmark_deployment.py` — OWNER-APPROVED prior-test amendment:
  `_installer_bundle_id` reads the installer-function attribute first, module constant
  fallback (home-grown families unchanged).
- Board tests and metadata cherry-picked from donor branches `OME-1115-5-gsm8k` /
  `OME-1115-6-mmlu` (check-surface sealed feedback, refuse-early, factory identity,
  MCQ surface refusal), rewired to `imported_board("gsm8k"|"mmlu")`.
- `docs/spec/2026-09-09-OME-1113-inspect-evals-import.md` §7 two-board amendment +
  OME-1115 ledger Outcome + `docs/tasks` mirror close (from the donor branches).

**PRs B1 + B2 — the pin generator (importer tool)** (owner decisions 2026-09-16:
edit files in place so `git diff` is the review artifact; auto-introspect from the
task name with dev review as the gate; license check warns but emits; split in two
stacked PRs by the ≤500-line rule — B1 = stages 1–2 reading facts, B2 = stage 3 +
CLI writing rows):
- `src/screamingface_engine_inspect/importer.py` — build-side command
  (`python -m screamingface_engine_inspect.importer <task_ref> --key <k>`):
  1. *introspect* — import the eval's task module, patch its `hf_dataset` binding
     with a recorder returning a stub dataset, call the task function, then read
     the recorded kwargs (dataset path/config/split, `record_to_sample`, pinned
     revision if the eval pins one) and the Task's solver/scorer registry metadata
     (family: templated | mcq | raw; scorer ref + kwargs; template attr resolved
     by identity scan of the module).
  2. *capture* — observations the eval's code can't provide: HF revision sha (when
     not pinned upstream), row count at that sha, dataset license (warn-only
     gate; the license lands as a comment in the generated rows).
  3. *emit* — insert the three row fragments in place at anchor comments: pin
     constants (pins.py), the `SnapshotSpec` entry (prepare.py), the `BoardSpec`
     entry (boards.py, title/description/focus as TODO placeholders for the dev).
- Anchor comments added to pins.py / prepare.py / boards.py (the insertion contract).
- `tests/unit/test_inspect_importer.py` — fabricated eval module (no network):
  introspection facts, renderer goldens (emitted code parses), in-place insertion
  round-trip on file copies, license-warn path, duplicate-key refusal; capture
  layer injected/faked.

**PR D — the onboarding runbook (docs only):**
- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md` — the AI-first
  import walkthrough (agent runs/writes, human verifies the diff) + refusal table +
  new `importer-pipeline` diagram (.drawio + PNG, sf-dark).
- Rename `adding-a-benchmark.md` → `adding-a-benchmark-manually.md`; cross-link the
  pair; update the two path references (README, `benchmarks/__init__.py`).

**PR C+ — the ten boards, in reviewable batches** (onboarding is AI-first — owner
direction 2026-09-16: the agent runs the importer, writes the TODO catalogue prose
from the eval's own docs, and resolves every TODO(review) flag; the human's role is
reviewing/verifying the generated diff, plus the paid acceptance runs):
- Ten generated row pairs (single-shot, license-cleared, `match`/`includes`/`choice`
  scorer families first), each with its per-board definition test; free-text boards
  opt into the check surface, MCQ boards refuse it (OME-796).

**PR C amendment (owner decisions 2026-09-17): ONE PR, nine boards, + the MCQ
template renderer** (supersedes "2–3 batches"; branch `OME-1116-6-ten-boards`
stacked on #966):
- Nine generated row triples via the importer: `arc_easy`, `arc_challenge`,
  `commonsense_qa`, `truthfulqa`, `mmlu_pro`, `winogrande`, `race_h` (MCQ, surface
  refused), `paws`, `boolq` (free-text, check surface ON). With gsm8k + mmlu the
  catalogue holds 11 imported boards (≥10 acceptance).
- Selection method: ran the importer's stage-1 introspection over every
  inspect_evals 0.20.0 task; excluded agentic / multimodal / judge-graded /
  code-exec / gated / importer-incompatible ones (drop: non-literal scorer kwarg +
  custom solver; math, squad: multi-scorer; gpqa, piqa, medqa, mgsm: no
  `hf_dataset`; hellaswag: unbaked system message; secqa: CC-NC license; wmdp:
  excluded on product grounds — it ranks models by hazardous knowledge). Owner
  approved this list + the license-warned rows (paws "other", boolq cc-by-sa-3.0,
  winogrande no card license, race "other") emitting with their note — the diff
  review is the gate.
- The family renderer batch 3 anticipated: `SnapshotSpec.choice_template` (dotted
  reference), `mcq_prompt(..., template=)`, importer captures a resolvable custom
  `multiple_choice` template instead of flagging (all three targets resolve to one
  module attribute; placeholders exactly question/choices/letters). Plugin-only,
  zero spine edits.
- Tests: renderer RED suite (spec field, mcq_prompt template arg, importer capture
  + emission) + one parametrized definition suite over the nine keys + fixture-row
  bake checks per new render path.

## Test plan

- RED first per PR: row-machine identity/registration tests (ported + new), the
  amended conformance test proving the function-attribute path AND the fallback,
  generator golden test (emit rows for a known task, byte-stable), per-board
  definition tests for each batch.

## Acceptance

- ≥10 imported boards evaluate end to end, each board ≤150 lines including its rows
  and tests (bar from the ticket), zero spine edits, `origin="inspect_evals"` +
  license note each, extra-less installs byte-identical, plugin never named in core.
- Solo / fusion structurally covered by the row machine's tests; corrective_loop on
  free-text boards via the check surface; paid `limit=50` acceptance runs remain the
  owner's.

## Outcome — PR C (milestone C, branch `OME-1116-6-ten-boards`)

- **Actual files:** `src/screamingface_engine_inspect/{pins,prepare,boards}.py`
  (8 generated row triples + filled catalogue prose + verified provenance
  comments), `importer.py` (choice_template capture; task-local
  record_to_sample refusal; emitted comment lines wrapped under the
  100-column gate), `tests/unit/test_inspect_imported_boards.py` (new
  definition suite, 10 keys), appends to `test_inspect_snapshots.py` +
  `test_inspect_importer.py`, roster rows in `test_benchmark_declaration.py`,
  owner-approved amendment in `test_inspect_mmlu_board.py`.
- **Commits:** see PR #970 (multiple commits on the branch; squash-merged as one).
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` ALL GREEN
  (ruff check/format, pyright, layering, pytest 3072 passed / 9 skipped,
  coverage 93%). Skip flag owner-approved 2026-09-17 for the two prior-test
  files below. Every new board full-bake verified offline from the pinned
  revisions (8/8 baked; counts match pins).
- **Deviations:**
  - truthfulqa DROPPED (was in the approved nine): its `record_to_sample` is a
    task-local closure, so the row's dotted reference can never resolve. The
    importer now refuses that shape at import time. Catalogue holds 10
    imported boards — acceptance (≥10) still met.
  - Prior-test changes (owner-approved via --skip-append-only ask):
    `test_inspect_mmlu_board.py` exact two-board list → proof-boards-in-order
    (full set owned by the new suite); `test_benchmark_declaration.py` +8
    roster rows (the table's designed extension path).
  - Shuffle seeds (exam identity, policy rows): mmlu_pro + race_h + none for
    the rest — grouping verified empirically (mmlu_pro first-100 rows are one
    discipline; race_h arrives in per-passage runs; all others mixed).

## Review round 2026-09-17 (blocker + should-fixes 1–4, owner-scoped)

- **Blocker confirmed and fixed — dataset-kwarg conservation.** Introspection
  read six hf_dataset kwargs and silently dropped the rest. Probe of our own
  evals: commonsense_qa / mmlu_pro / race_h / paws / boolq pass `shuffle=True`
  (mmlu upstream even `seed=42`) — so commonsense_qa, paws, boolq had been
  imported with the shuffle dropped. Fix: every kwarg is now conserved —
  reproduced ({path,name,split,revision,sample_fields,shuffle,seed}), benign
  ({auto_id,trust,cached,retry}), or a named refusal (limit, shuffle_choices,
  data_dir, anything unknown). shuffle without a seed requires --shuffle-seed;
  an upstream seed is reproduced into the row. The three under-pinned boards
  gained policy seeds (20260917) + prose; regression pins:
  `test_boards_whose_eval_shuffles_carry_a_pinned_seed` + the refusal tests.
- **Should-fix 1** — positional hf_dataset args now signature-bound in the
  recorder (17/80 real call sites pass path positionally).
- **Should-fix 2** — data_dir no longer aliased to config: refused with "add
  the row by hand" (gsm8k's merged row was hand-verified; the module docstring
  example moved to arc_easy).
- **Should-fix 3** — the single-call fallback now requires the Task's dataset
  to still hold the recorder's stub; an HF fewshot load beside a local exam
  refuses instead of importing the fewshot split as the exam.
- **Should-fix 4** — injection guards: Hub-controlled strings (dataset, config,
  refs, license) are charset-refused; the captured revision must be a 40-hex
  sha at the tool; every composed file is ast.parse-verified before writing.
- **Incident during RED:** a main()-level test without --engine-src wrote fake
  rows into the real package (the CLI default). Removed; the test now pins an
  explicit tmp engine-src and an AIDEV-NOTE warns the next agent.
- **Deferred (flags-only follow-ups, unfiled):** non-literal scorer kwargs
  flag; multiple_choice params (multiple_correct/cot) emission; epochs /
  generation-config task settings; stage-2 network errors wrapped as
  ImporterError; the CI inspect-extra test lane (review Lane 7).

## Review round 2 — 2026-09-17 (all medium/auto-fixable; verified real)

- Applied: injection charsets anchored with `\Z` (+ trailing-newline refusal
  test); WHY-seed comments on the MMLU_PRO/RACE_H pins; provenance notes —
  winogrande "imported at fewshot=0", winogrande/race_h "filter_duplicate_ids
  wrapper verified content-preserving (0 duplicates) at this revision".
- Deferred to tickets (with round 1's list): conserve dataset WRAPPERS
  (filter/dedup) not just kwargs — filter_duplicate_ids passes the stub-holding
  fallback invisibly; record --task-arg list in generated pin provenance;
  GenerateConfig (temperature/max_tokens) neither reproduced nor flagged
  (bites cqa/race_h/winogrande as a comparability fact, accepted as policy).
