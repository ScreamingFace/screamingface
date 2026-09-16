# OME-1117 — Export a report in inspect's log format

Ticket: `OME-1117` · Parent: `OME-1111` · Landing: `packages/screamingface`
Ledger: `docs/work/2026-09-16-OME-1117-inspect-log-export.md`

## Problem / Solution

**Problem:** Our run results are written in a language only our own tools read.
Researchers who live in the inspect ecosystem cannot open them in the viewers and
scripts they already use — exactly the audience the imported benchmarks attract.

**Solution:** Teach the report to export a one-way copy in inspect's `.eval` log
format, clearly stamped as ours, so `inspect view` opens our results with nothing
new to install.

## 1 · What we take from inspect (and what we refuse)

| Take | Refuse |
| --- | --- |
| `inspect_ai.log.write_eval_log` — their own writer produces the `.eval` zip, so compatibility is theirs to define, not ours to reverse-engineer | Hand-rolling the `.eval` zip layout (journal members, summaries, header) — churns with their releases |
| The `EvalLog` document model, built via `EvalLog.model_validate(payload)` from a plain-dict payload we assemble | Any read path — `read_eval_log` never enters the SDK; the export is one-way by construction |
| The engine's exact pin `inspect-ai==0.3.263` (revision identity already hashes this pin engine-side) | `inspect-evals` — the export needs only the log model |

Verified against the pin (probe, 2026-09-16): `write_eval_log` → `.eval` →
`read_eval_log` round-trips; `EvalSample.model_validate` accepts plain-dict
messages/output/scores/usage; `ModelUsage.total_cost` exists for real metered cost;
`EvalSpec` requires `created, task, dataset, model, config`; `EvalSample` requires
`id, epoch, input, target`.

## 2 · Seam — one new format on the existing export

```python
report.export()                                   # unchanged: report.json
report.export(format="inspect")                   # report.eval, single-candidate report
report.export("runs/gsm8k.eval", format="inspect", candidate="fusion")
```

- `Report.export(path=None, *, format="json" | "inspect", candidate=None) -> Path`.
  `path=None` selects the format's default name (`report.json` / `report.eval`);
  the JSON branch is byte-identical to today's behavior.
- **One `.eval` file = one candidate's run** — that is inspect's own unit (a log is
  one task × one model). A single-candidate report exports directly; a
  multi-candidate report requires `candidate=<name>` and refuses otherwise, naming
  the candidates. Exporting all of them is a caller loop, not API surface (YAGNI).
- `format="inspect"` requires a `.eval` suffix, mirroring the `.json` guard.
- `candidate=` with `format="json"` is refused — the JSON document is whole-report.

**Public-surface consequence:** the `export` signature is pinned twice in
`tests/public_surface_snapshot.json`; the change regenerates the snapshot
(`UPDATE_SURFACE_SNAPSHOT=1`) and needs the owner's append-only sign-off.

## 3 · Module shape — mapping is pure, the dependency is quarantined

```
src/screamingface/_inspect_log/
  __init__.py     # re-exports write_inspect_log
  payload.py      # PURE: (Report, candidate name) -> JSON-safe EvalLog payload dict.
                  # Zero inspect imports. Fully covered by the default CI install.
  write.py        # find_spec("inspect_ai") gate -> lazy import -> model_validate -> write_eval_log.
                  # File-level pyright reportMissingImports=false (engine shim pattern).
```

- `report.py` imports `_inspect_log` lazily inside `export()` — no import-time cost,
  no cycle, and an extra-less install only pays when it asks for the format.
- Missing dependency → `ModuleNotFoundError` with the fix in the message:
  `pip install "screamingface[inspect]"`.
- New extra in `pyproject.toml`: `inspect = ["inspect-ai==0.3.263"]` — exact `==`
  to stay in lock-step with the engine's pin (`apps/screamingface-engine`), same
  reasoning: the format contract is version-shaped. Lockfile regenerated.
- **Found during lock (2026-09-16):** `inspect-ai==0.3.263` (hard `aioboto3`
  dependency) and the runtime extra's `litellm==1.98.0` cannot co-install on any
  platform — their `boto3` windows never intersect. Declared as a genuine
  `[tool.uv] conflicts` pair rather than loosening either pin. Consequence: a
  local-runtime env exports via a separate env (e.g. `uvx`) holding the inspect
  extra; the hosted-notebook persona (the ticket's audience) is unaffected.

## 4 · Mapping — report.v1 → EvalLog payload

| inspect field | Source | Notes |
| --- | --- | --- |
| `eval.created` | `candidate.started_at` | ISO text |
| `eval.task` | `benchmark.id` | flat id (`draco`, `inspect-gsm8k`, …) |
| `eval.model` | `candidate.name` | free-form string is legal there; a fusion has no single provider model |
| `eval.dataset` | `{name: benchmark.id, samples: report.case_count}` | SELECTED size (root convention) |
| `eval.config` | `{}` | their run knobs; we did not run their loop |
| `eval.tags` | `["screamingface-export"]` | greppable in their tooling |
| `eval.metadata` | provenance block | see §5 |
| `samples[]` | one per `CaseResult`, `epoch=1` | id = `case_id` |
| `sample.input` | `case.conversation` turns as `{role, content}` dicts, else raw `case.input` | envelope-blind via the existing decoder |
| `sample.target` | `""` | the client never holds gold answers — grading already happened engine-side; the truth lives in `scores` |
| `sample.output` | ModelOutput dict from `case.output` | omitted when the case produced none |
| `sample.scores` | `{"screamingface": {value, answer, explanation}}` | from `CaseGrade.score` + first valid evidence explanation; absent when ungraded |
| `sample.metadata` | `{status, refusal?, finish_reason?, stop_reason?, rounds_executed?, failures[]}` | our vocabulary rides along verbatim |
| `sample.model_usage` | omitted | per-case usage is not attributed client-side (only per-operation accounting) |
| `results.scores[0]` | scorer `"screamingface"`, metrics `{score, coverage}` | candidate-level |
| `results.total/completed_samples` | case counts | completed = scored cases |
| `stats` | run window + `model_usage` | `{candidate.name: ModelUsage(tokens…, total_cost=float(cost_usd))}` — **the metered cost, passed through**; per-member rows added when member usage exists |
| `status` | `"success"` if `candidate.score is not None` else `"error"` | matches our scored/failed split |

## 5 · Provenance — stamped as ours, one-way by construction

`eval.metadata`:

```json
{
  "produced_by": "ScreamingFace engine",
  "source_schema": "screamingface.report.v1",
  "one_way_export": true,
  "benchmark_revision": "<report revision>",
  "run_id": "<candidate run_id>",
  "recipe_kind": "<kind>",
  "recipe_url4": "<canonical url4>",
  "answer_seed": null,
  "cost_usd": "<decimal text or null>"
}
```

- The label is the **exporter's** identity, not the board's upstream origin —
  `BenchmarkInfo` carries no `origin` field and threading one through report.v1 is
  a separate wire change this ticket refuses (scope). The board's provenance is
  already legible from `benchmark.id` (`inspect-*` prefix) + `benchmark_revision`.
- One-way: no reader API, no ingest surface, no `expression_sha` anywhere in the
  log — nothing in the leaderboard path can consume it (Don't-regress clause).

## 6 · Scope

- **Now:** `format="inspect"` on `Report.export`; the `inspect` extra; pure payload
  mapping + quarantined writer; opt-in live round-trip test.
- **Later:** the "export + submit upstream" one-click flow (gated on inspect's
  submission rules, per OME-1113 §7); exporting every candidate in one call.
- **Out (on purpose):** reading/importing `.eval` logs; leaderboard ingestion of
  exported logs; threading benchmark `origin` into report.v1.

## 7 · Acceptance (falsifiable)

1. A completed report exports to a `.eval` file that inspect's own reader opens
   (`read_eval_log` — the same reader `inspect view` uses); verified live at
   `inspect-ai==0.3.263`.
2. The log carries `produced_by` + `one_way_export` metadata and
   `stats.model_usage[*].total_cost` equal to the report's metered `cost_usd`.
3. `uv sync --extra notebook` (the CI install) runs the full suite green — the
   payload mapping is covered without inspect installed; `export(format="json")`
   behavior and its tests are untouched.
4. A multi-candidate report without `candidate=` fails with the candidate names in
   the message; unknown names fail loudly.
5. No module in `src/screamingface/` imports `inspect_ai` at module scope
   (`grep -rn "^import inspect_ai\|^from inspect_ai" src/screamingface/` is empty).
