# OME-416 — Report provenance implementation plan

1. Add regression tests for sequenced root log → run outcome → candidate result → exported JSON, including missing, malformed, conflicting and child evidence.
2. Validate the existing Engine token contract in a small Client helper. Keep stream decoding tolerant and public construction strict.
3. Carry optional client_version through _RunOutcome and CandidateResult. Never query the locally installed version while constructing or exporting a report.
4. Document the field and its distinction from cache-origin and notebook-generator versions. Leave Scoreboard submission identity unchanged.
5. Run all Client gates and review transport artifact materialization/replay preservation. Open a draft PR referencing OME-416. Do not merge or add Linear comments.
