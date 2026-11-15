# E20 shared-table revision plan

1. Update the PR's new tests for the user-approved shared table and ranks; use
   exact cell/attribute assertions and timezone-aware expected dates. Add top-50,
   tie, alternate-sort, empty, invalid-row and safe-link checks. Confirm RED.
2. Normalize external rows, merge and limit with community rows, and render in the
   same table with gray styling and source actions. Remove the separate section.
3. Run the full scoreboard gates and tests in four timezones. Visually inspect
   light/dark/mobile and mixed results using captured dev data.
4. Remove superseded committed screenshots. Update PR description to the final
   implementation, commit and push as FilipBolt. Do not merge or deploy.
