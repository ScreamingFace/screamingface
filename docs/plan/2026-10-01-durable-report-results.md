# Implementation plan

1. Add durable storage, versioned metadata codec, atomic writes, and indexed case access.
2. Persist transport outcomes before downloads; share verified streaming download logic
   with recovery using existing authenticated transport. Keep credentials out of storage.
3. Wire incremental decoding through Report validation and export; audit eager consumers.
4. Expose listing, reopening/recovery, and explicit cleanup with clear partial/error states.
5. Simplify pagination and refresh the notebook demonstration.
6. Run recovery/integrity/memory tests and SDK gates; update existing draft PR 1156.

Do not mark either ticket resolved until its acceptance evidence exists.
