# OME-981 — implementation plan

1. Add connector → URL4 error payload → IFEval aggregate regression tests; confirm RED.
2. Add a small IFEval-local exact diagnostic classifier and use it for anonymous
   collected failures. Update stale comments about URL4 diagnostic preservation.
3. Prove checker and ambiguous errors stay grading-stage; malformed records still
   abort. Keep all existing tests unchanged, including the generic provider_error fixture.
4. Run screamingface-engine gates, review the diff, commit and open a code draft PR.
