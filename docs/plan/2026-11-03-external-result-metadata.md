# External result metadata implementation

Spec: [metadata contract](../spec/2026-11-03-external-result-metadata.md).

1. Add failing tests for JSON validation, persistence, replacement semantics, server
   timestamps, legacy rows, rollback, public response and populated-db migration.
2. Share typed metric/date fields between import and read DTOs in a small module;
   attribution belongs only to import and storage, per owner option A.
3. Add nullable columns to the baseline model and a built-in Tortoise migration
   after `0021_score_metadata_objects`; do not upgrade dependencies or backfill.
4. Write provenance and server import time with the existing transactional upsert;
   return only the public fields through the existing baseline serializer.
   Update the privacy guard for the approved three-field addition and record its
   exact approved change; test attribution exclusion on public and private boards.
5. Document a complete import example and the meaning of missing values.
6. Run focused tests, then the full scoreboard gate runner and migration checks.
   Review the diff and commit locally. Request permission for the Linear child issue
   before opening a PR, as required by the owner and current repository workflow.
