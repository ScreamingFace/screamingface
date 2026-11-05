# Plan

1. Recheck pinned SAT-English sources and public board scope; publish the audit in
   the repo with remote evidence links and no local-only references.
2. Add failing import/read tests for missing evidence, incompatible scope, exact
   conversions, rollback, changed revisions and replaced observations.
3. Add a reviewed profile registry and a pure comparison validator. Wire it into
   the existing transactional importer and public read projection.
4. Add the fail-closed portal guard and regression cases to #1644.
5. Run both scoreboard gates, inspect the combined contract, commit and open the
   backend follow-up PR. Keep Linear unchanged pending owner permission.
