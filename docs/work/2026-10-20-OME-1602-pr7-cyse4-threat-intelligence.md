---
ticket: OME-1602
stack: screamingface-engine
status: done
started: 2026-10-20
finished: 2026-10-20
---

# OME-1602-pr7-cyse4-threat-intelligence — import cyse4_threat_intelligence from the report mirror

## Intent

The last OME-1602 Benchmark. inspect_evals' `cyse4_threat_intelligence` asks 588 multi-answer
questions about 45 public threat-intelligence reports. 19 CrowdStrike reports come from
CrowdStrike's own GitHub zip at a pinned commit; the other 26 (CISA, FBI IC3, NSA) come from
web.archive.org, which refuses connections partway through a burst, so a build that fetches
them fails (seen 2026-10-02). The owner mirrored those 26 PDFs, byte-identical to upstream's
sha256 pins, at the public Hugging Face dataset `khoaguin/cyberseceval4-threat-intel-reports`
@ `ab38cf24125e38b88ef0f2dd866d5d3cc12965cb` (owner, 2026-10-20). This unit fills the replay's
cache from that mirror before the eval's loader runs (the Case Source prefetch, the seam SAD
uses; owner chose it over a local Task on 2026-10-20), adds pypdf for the text extraction,
and imports the row.

## Planned changes

- `case_source_prefetch.py`: `prefetch_cyse4_threat_intelligence`. It unpacks the CrowdStrike
  zip through upstream's own `download_threat_intel_data`, then fetches each of the 26 PDFs
  from the mirror into upstream's reports folder, checked by inspect's `download` against
  upstream's `THREAT_INTEL_PDF_SHA256`. Keyed on the threat_intelligence module only, so
  malware_analysis is untouched.
- `pyproject.toml` + `uv.lock`: `pypdf` pinned exactly, in the build-only `benchmarks` extra.
- Rows: `prepare.py` (`TaskReplayCasesSpec`) and `benchmarks.py` (`BenchmarkSpec`), written
  by the importer, prose and provenance by hand.
- Mirror `docs/tasks/2026-10-14-OME-1602-remaining-single-turn-imports.md`: PR 7 line, closed.

## Test plan

- `tests/unit/inspect/test_cyse4_threat_intelligence_prefetch.py` (new): the prefetch fetches
  every upstream-pinned report from the mirror at the pinned commit into upstream's reports
  folder; it unpacks CrowdStrike first, so the folder is never non-empty-but-incomplete; a
  PDF whose bytes differ from upstream's pin fails the replay; malware_analysis gets no
  prefetch.
- The existing row and conformance tests the importer's rows feed (named at PR time).

## Acceptance

- A replay of the row fetches nothing from web.archive.org and yields 588 Cases (or the
  declared count after excluded Samples), sealed by a Case Digest.
- The relevant unit tests, ruff and pyright on touched files are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `import_replay.py` (the import's first run calls the
  prefetch too) and five existing row tests that list every row (`test_benchmark_declaration`,
  `test_failure_policy_rows` count 82 → 83 and 65 → 66 withhold, `test_inspect_imported_benchmarks`,
  `test_letter_list_key_imports` multiple_correct list, plus a grading test for the new row).
- **Commits:** `feat(screamingface-engine): import cyse4_threat_intelligence from the report mirror`.
- **Gates:** run by hand on the touched code only (owner rule): 23 test files, 1,426 passed,
  covering every test that iterates the rows, the prefetch and import-replay tests and the
  new grading test; ruff check and format clean; pyright on the 9 touched files 0 errors in
  the extra-less venv. A mutation (multiple_correct off on the row) turns the grading test red.
- **End to end:** from a clean cache, prefetch then upstream's own loader contacted
  github.com once (the CrowdStrike zip) and huggingface.co 26 times, web.archive.org never;
  588 Samples built, prompts 8,134 to 163,513 characters (median 26,795). The importer's two
  runs sealed the same Case Digest, 587 Cases.
- **Deviations:**
  - The importer's first run did not call the prefetch, so it went to web.archive.org and
    was refused (`tenacity.RetryError`, as on 2026-10-02). It now prefetches before the
    recorder installs, as the image side does; SAD's import gets the same prefetch.
  - Question 361 (Scattered Spider, IC3 231116) keys A to F over five options, so Case
    Preparation refused it; excluded as a Named Deviation at the owner's call (587 Cases,
    not the ticket's 588).
  - The ticket's "fix one qakbot-onenote question" needs no change: question mX9pR4wN's
    `url_source` names the wrong PDF, but the Case reads `report_id`, which is right.
  - The whole-run headline: `--whole-run-metric mean`, as malware_analysis (the mean of
    "score" is the eval's accuracy).
  - Known gap, accepted with the prefetch seam (owner, 2026-10-20): the row's Case Sources
    list the 26 web.archive.org URLs the eval asks for, not the mirror, and omit the
    CrowdStrike zip, which the prefetch fetches before the recorder installs.
  - pypdf runs without fontTools (not in the lock, so not in the image either); some
    report fonts log a warning. Extraction is the same on every machine with this lock,
    and upstream's own extra installs pypdf alone.
- **Owner verify:** the frontier score (0.59, Claude 3.7 Sonnet) is read off Figure 10's line
  chart; the licence headline CC-BY-ND-4.0 with the per-source note.
