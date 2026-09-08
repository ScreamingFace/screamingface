# OME-885 — Public portal source-hygiene plan

1. Append an HTTP-level regression test that enumerates the mounted portal tree, confirms every
   file is served, and scans raw responses for forbidden internal markers.
2. Run that test alone and retain the expected failure as the RED signal.
3. Audit every reported match. Rewrite present-behavior rationale in public-safe language and move
   internal history or future-work reasoning into the work ledger.
4. Re-run the focused test, the complete static-portal test module, and the portal Node suites.
5. Run `uv run .claude/scripts/run_gates.py scoreboard --base origin/main`.
6. Review the final served tree for behavior changes, update the ledger outcome, and commit with
   `Refs: OME-885`.
