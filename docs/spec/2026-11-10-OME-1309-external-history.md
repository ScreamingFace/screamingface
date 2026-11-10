# External result history

Owner chose A/A: save changed manual/import observations, omit identical repeat versions, and expose an Updated link opening prior scores, dates and source URLs. Actor attribution stays internal. All observation fields (including source-read date, comparison metadata and internal attribution) participate in change detection; last-import server timestamps do not. Initial imports are not edits.

Keep the existing benchmark/model/source identity. Store immutable snapshots with increasing revision numbers inside the current import transaction and row lock. Seed a legacy row's current state before its first edit; do not invent when that state began. Keep current result ranking and comparison validation unchanged. Preserve atomic batch rollback and import timestamps.

Expose bounded newest-first history, including the current version marked as such, with cursor pagination. External observations are already public on private boards; history follows that existing policy and never includes attached_by. A dedicated history page linked from Updated keeps old values outside rankings. No public edit API, restore action, production import, Linear write or unrelated Source-button redesign.
