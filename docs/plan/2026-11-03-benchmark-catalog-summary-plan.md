# Implementation plan

1. Add failing API parity/query-count tests and DOM controller tests.
2. Add compact schema and one grouped SQL query plus a bulk visibility recheck, wire a separate catalog router.
3. Extract homepage bootstrapping to catalog.js; reuse existing card renderer.
4. Add accessible controls and local filtering/paging; no caching.
5. Exercise SQLite and PostgreSQL; register tests in both CI lanes as applicable.
6. Capture public baseline; compare actual local app baseline/summary using the same
   dataset and controlled network profiles. Document unknown production DB size.
7. Run gates and browser smoke; record evidence and prepare reviewable change.
