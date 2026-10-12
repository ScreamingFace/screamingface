# Interrupted report lifecycle and recovery notice

Final SDK slice from #1156; base main 8e0c0a29 after the four prior slices. Keep the already merged result storage/recovery, atomic export, accounting and notebook browser implementations.

Record the current owner PID and running state in newly prepared evaluation manifests. Mark returned or handled failed evaluations ready even if no Candidate result decodes. Cancellation or unexpected process death must retain unfinished state. Record rendering/exporting operations and keep outstanding operations visible until the last finishes, including overlapping operations and handled errors. Existing legacy manifests lacking owner metadata remain unmodified.

Explicit recovery runs inside a running marker and settles ready for successful or handled incomplete recovery. Destination recovery must retain discovery metadata on both stores, without changing grouping, partial reports or corrupt-sibling safeguards.

At persisted sync/async Client startup in an active notebook, inspect retained completed records for this Engine only. For unfinished evaluations whose owner demonstrably exited, show one shared informational recovery notice per store/evaluation, with an escaped explicit sf.reports.get command. The notice must not claim all artifacts are available or start recovery/model runs. Headless startup, healthy/active/legacy records, inaccessible owners and other Engines stay silent. Optional unreadable/malformed lifecycle metadata or display failures cannot prevent startup or discard usable reports. Paths must stay inside the store's evaluation directory.

No new dependencies or Engine/runtime changes. Preserve transport default persistence opt-out and public Client persistence opt-in defaults. #1217 remains independent. Document retained-artifact limits and POSIX liveness limits. Capture actual notice before/after screenshots and run all SDK gates, append-only inherited tests and independent reviews.

The prepared evaluation scope itself counts as active work, including while a saved Candidate is recovered, exported or displayed before the evaluation returns. Finishing any of those operations cannot settle an evaluation still in progress. Only success or handled candidates_failed evaluation failures settle; other errors and cancellation remain unfinished, and transport cleanup always runs.

When multiple local notebook processes share a store, coordinated marker updates preserve every unfinished owner. Completing saved Candidate access in one process cannot settle another process's evaluation, recovery, export or rendering. Death of an outstanding owner remains discoverable; successful explicit recovery may clear dead-owner interruptions, but cannot clear live foreign work.

Recovery tracking includes Candidate selection. A handled candidates_failed error caused by all corrupt Candidate manifests settles the canonical evaluation ready for both sync and async APIs, without changing named failure details or starting model calls. Direct corrupt saved-key lookup retains its preexisting result_metadata_invalid error and unfinished lifecycle state. Invalid/unknown report selection does not create an unrelated marker.

Supported recovery aliases (evaluation ID, saved key and run ID) track the canonical evaluation in both source and destination stores, including successful settlement and cancellation. Alias resolution preserves existing ambiguity/missing errors and selection-time handling for corrupt candidates.
