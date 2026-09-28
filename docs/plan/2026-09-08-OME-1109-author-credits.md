# OME-1109 — Implementation plan

## Frame

Change only the shared scoreboard author schema/publication seam. Preserve raw input and storage,
and make every public DTO inherit one duplicate/collision rule through the existing `Authors`
annotated serializer.

## Changes

1. Add failing schema tests for distinct-count validation, case-insensitive duplicate collapse,
   collision disambiguation, stable order, and unchanged non-collision redaction.
2. Add a failing persistence/export test proving raw author entries and casing survive while the
   same DTO's public JSON is collapsed and disambiguated.
3. Extract one case-folded full-address key and use it for both distinct-count validation and
   publication deduplication; retain a separate 4 KiB serialized-list envelope so repeated
   identities cannot create an unbounded public write.
4. Group the first-seen distinct authors by case-folded local part; publish the full stored
   address only for groups that collide.
5. Run the focused multiple-author suite and then the complete scoreboard gate.
6. Perform the wisdom/confidence review, finish the ledger, and commit with `Refs: OME-1109`.

## Non-goals

- modifying models, migrations, storage projections, portal code, or the Client package;
- folding OME-840, OME-969, or any other public-write contract into this unit;
- rebasing onto or copying changes from the unmerged OME-822/#841 branch.
