# Recovery follow-up contract

Refs: OME-1448. User authorized fixing both remaining findings in this conversation.

Reject malformed evaluation identities, candidate lists and any declared benchmark/case count while loading a saved manifest. Discovery-only legacy membership remains readable, but explicit recovery of insufficient context returns a structured metadata error. Invalid siblings remain explicit missing results and healthy candidates remain available in partial_report.

While multiple renders/exports of one evaluation overlap in this process, its lifecycle remains pending until the last presentation operation finishes. Bookkeeping is protected by a lock and cleaned in finally. Discovery is still best effort, credentials are not persisted and no wire/export/public schema changes are required.
