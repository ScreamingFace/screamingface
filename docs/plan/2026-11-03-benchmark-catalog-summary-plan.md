# Implementation plan

1. Add failing API parity/query-count tests and DOM controller tests.
2. Add compact schema and one bulk top-candidate SQL query plus a bulk visibility recheck, wire a separate catalog router.
3. Extract homepage bootstrapping to catalog.js; reuse existing card renderer.
4. Add accessible controls and local filtering/paging; no caching.
5. Exercise SQLite and PostgreSQL; register tests in both CI lanes as applicable.
6. Capture public baseline; compare actual local app baseline/summary using the same
   dataset and controlled network profiles. Document unknown production DB size.
7. Run gates and browser smoke; record evidence and prepare reviewable change.

Review follow-up: add corrupt top-row tests before changing the query; replace the
scalar MAX with a bounded top-candidate projection per benchmark so the row decoder
can make the same readability decision as the board. Repeat performance measurements
because the query shape changes. Remove copied baseline assets from evidence and
retrieve them by the recorded main commit instead; make PR links independent of branch.
