# E20 external-row UI plan

1. Add DOM behavior tests for the real page: external-only and mixed boards,
   missing data, native scores, safe URLs/text, source/date/caveats, and isolation
   from ranked rows, summary, sorting, copy buttons and charts. Confirm failure.
2. Add an external-results renderer and hidden semantic table in benchmark.html;
   call it from the existing leaderboard response. Use neutral design tokens.
3. Register the new Node test explicitly in CI and the local scoreboard gate.
4. Run scoreboard gates and visually check light/dark and narrow layouts using
   the captured dev API response. Review the diff, commit, and open a PR as FilipBolt.

The user authorized proceeding with the PR. No merge or shared deployment is part
of this step. The existing dev data import needs no code PR of its own.
