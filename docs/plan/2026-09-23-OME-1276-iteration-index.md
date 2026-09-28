# OME-1276 implementation plan

1. Add regression tests through actual SDK execution before production changes.
2. Enumerate selected MapNode items before scheduling. Bind the index in each immutable row
   scope and resolve it through shared reference handling. Keep independent row executions.
3. Exclude iteration-owned index references from enclosing dependency capture, while retaining
   normal name resolution outside iteration. Native index takes precedence inside iteration, as approved.
4. Cover nested outer capture and existing bindings; add SDK usage and compatibility notes.
5. Run URL4 lint/format/types/tests/coverage and independent spec/standards review. Commit,
   push and create a draft PR; leave Linear In Progress until review is requested.
