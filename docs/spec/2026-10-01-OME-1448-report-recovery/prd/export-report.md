# PRD: Export a Report with bounded memory (option D)

**Source:** prompt (option D) / ans:Q1 · **Priority:** P1
**Lifecycle:** existing (characterize + delta) · **Owner:** @ionesio

## 1. Summary and user story

As a researcher with a large Report in memory, I want `report.export()` to write the file without
a second full copy in memory, so that the export itself does not kill the kernel (F2).
`[stated prompt]`

## 2. Background and constraints

- "⑥ builds the whole JSON as one string, then writes it." `[stated prompt]`
- "`report.json` written by `Report.export()` stays byte-identical." `[stated prompt]`
- Uses: `prd/report-json-writer.md` (the byte-identity invariant and the streaming encoder).

### 2.1 Current behavior

- `export(path="report.json", *, format="json", candidate=None)`.
  `[existing packages/screamingface/src/screamingface/report.py:467]`
- For JSON: refuses `candidate`, refuses a suffix other than `.json`, creates the parent
  directories, then `selected.write_text(self.to_json(), encoding="utf-8")`. An existing file is
  replaced. `[existing packages/screamingface/src/screamingface/report.py:467]`
- `write_text` truncates the target first. A crash mid-write leaves a truncated file. `[implied]`
- `write_text` follows a symlink and writes the target file. The new file gets mode
  `0o666 & ~umask`. `[implied]`

**Delta:** the JSON branch writes through the streaming writer into a sibling temporary file,
then `fsync`, then `os.replace`. The public signature, the path rules, and the bytes do not
change. `[stated ans:Q1]`, `[proposed]`

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**EX-H1. Same bytes.** `[stated prompt]`
Given any Report that fits in memory,
When `report.export(path)` runs,
Then the file bytes equal today's output (`to_json()` as UTF-8).

**EX-H2. Bounded extra memory.** `[stated prompt]`
Given a Report of 11 Candidates,
Then export adds at most one Candidate's `to_dict()` plus 1 MiB to the peak (RW §4).

### 3.2 Error paths

**EX-E1. Path rules are unchanged.** `[existing packages/screamingface/src/screamingface/report.py:467]`
Given `path="report.txt"` or `candidate="x"` with `format="json"`,
Then the same `ValueError` messages as today.

### 3.3 Derived scenarios (risk order)

**EX-D1. A crash mid-export keeps the old file.** `[proposed — gap §per-connection/data]` · H × M
Given an existing `report.json`, and an export that dies after Candidate 4 of 11,
Then the old `report.json` is unchanged and complete. Only a temporary sibling is left, named
`.report.json.<uuid>.tmp`.

**EX-D2. Disk full.** `[proposed — gap §per-connection/data]` · M × L
Given `ENOSPC` during the write,
Then the `OSError` reaches the caller, the temporary file is removed, and the old file stays.

**EX-D3. A symlink target.** `[proposed — gap §per-flow/boundary]` · M × L
Given `path` is a symlink to `/data/out.json`,
Then `/data/out.json` gets the new content, and the symlink stays a symlink (the same visible
result as today's `write_text`).

**EX-D4. File mode.** `[proposed — gap §per-flow/boundary]` · L × M
Given no existing file, Then the new file has mode `0o666 & ~umask`, as today.
Given an existing file with mode `0640`, Then the replaced file keeps `0640`.

**EX-D5. Inspect format is unchanged.** `[implied]` · L × L
Given `format="inspect"`, Then the export takes today's path to `_inspect_log` unchanged.

## 4. Non-functional requirements

- Memory: as in EX-H2. Time: within 20 % of today for a 50 MB Report (RW §4). `[proposed]`

## 5. Out of scope

- Streaming the inspect export. `[proposed]`
- A Report loader. `[proposed]`

## 6. Open questions

None.

## 7. TDD plan

Characterization first, then the delta, in risk order.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| EX-0 | CHAR existing export tests (`test_report.py:183`, `:470`, `:489`, `:709`) stay green unchanged | unit | §2.1 | — | none |
| EX-1 | `crash_mid_export_keeps_previous_file_intact` (writer iterator raises on Candidate 4) | unit | EX-D1 | H×M | temporary sibling + `os.replace` |
| EX-2 | `export_bytes_equal_to_json_for_property_generated_reports` | unit | EX-H1 | H×H | call the writer |
| EX-3 | `export_peak_memory_is_bounded_by_one_candidate` (tracemalloc) | unit | EX-H2 | H×M | stream |
| EX-4 | `disk_full_removes_temp_and_keeps_old_file` | unit | EX-D2 | M×L | cleanup on error |
| EX-5 | `symlink_target_is_replaced_and_link_survives` | unit | EX-D3 | M×L | resolve the path before staging |
| EX-6 | `new_and_replaced_file_modes_match_today` | unit | EX-D4 | L×M | `chmod` from umask or from the old file |
| EX-7 | `inspect_export_path_is_unchanged` | unit | EX-D5 | L×L | no change |
