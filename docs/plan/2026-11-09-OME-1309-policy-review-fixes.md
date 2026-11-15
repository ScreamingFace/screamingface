# Review correction plan

Reuse validate_storable_json after existing metadata size/depth checks. Exercise NUL and lone surrogates in comparison notes and arbitrary nested keys/values, valid Unicode, batch no-write behavior and legacy read exclusion. Carry the parent metadata fixes into this stacked PR.

Write regression tests and observe failures first, apply the minimal fixes, then run focused SQLite/PostgreSQL tests and full scoreboard gates. Commit and update the existing PR as FilipBolt. No Linear writes without separate approval.
