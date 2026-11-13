# Review correction plan

Keep the row update and timestamp write in one transaction. Compute a nondecreasing timestamp after the upsert lock, at least the first-import time. Reject Unicode Cc/Cf/Cs in metric and attribution before trimming. Format validation diagnostics without rejected inputs or exception context. Add first-import, backward-clock, concurrent replacement, public/private read and CLI regressions.

Write regression tests and observe failures first, apply the minimal fixes, then run focused SQLite/PostgreSQL tests and full scoreboard gates. Commit and update the existing PR as FilipBolt. No Linear writes without separate approval.
