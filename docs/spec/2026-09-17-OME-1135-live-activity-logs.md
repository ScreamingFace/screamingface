# OME-1135 — Live activity within evaluation rows

Owner approved a Client implementation against Engine #980 with no older-Engine compatibility. The approved layout is one Candidate table, with stage-aware Status and independently expandable rows. There are no Evaluation/Logs tabs or compact/detailed switches.

## Researcher experience
Status uses Loading cases, Answering, Grading and Aggregating when received activity establishes the phase. Concurrent fresh phases are listed together. Stale observations are labelled Last observed; operation completion never implies a Case passed or the run succeeded. Authoritative final status, scores, Case counts and cost retain their existing meanings.

A keyboard-operable disclosure beside each Candidate opens a stable scroll box directly beneath its summary. All retained model-call summaries are available with model identity, outcome, measured duration and safe supplied details. Groups are explicit stage occurrences; parent chains are resolved only within the same Candidate/run. Missing, evicted or cyclic parents remain Activity not identified. Late parent arrival may establish grouping. Never infer ownership from route names, model names, prose or timing.

The projection stores only allowlisted screamingface.activity.v1 fields, never raw Log bodies or private payloads. Supported kinds are case_loading, answering, grading, aggregation and model_call. Unsupported/malformed records do not affect callbacks or execution. The view discloses producer suppression, bridge loss, revision gaps and local truncation. Silence is no structured activity received, not proof of disabled policy or idle work.

## Bounded live state
A rolling history plus occurrence index retains at most 2,000 records / 8 MiB serialized data. Older routine history is evicted before unresolved or failure summaries; every category remains bounded. Each expansion renders a page of at most 100 selected operations, with enclosing group headings as context. Pagination and disclosure controls survive updates; scroll roots are never replaced. Fixed 200 ms update coalescing and a one-second quiet tick continue for the run lifetime, with no six-hour cutoff.

The decoder collision window retains at most 4,096 IDs / 1 MiB. Sequence cursors still reject old replay; ID uniqueness detection applies only within that bounded window. No durable archive, server storage, new URL4 capability or older-schema aliases.

Durations stay measured, never extrapolated provider progress. Stage freshness uses the approved conservative 30-second allowance / 180-second observation window; historical state is labelled rather than timed out. Missing completion is outcome not observed, and root termination ends incomplete displays without fabricated outcomes.

## Validation
Group interleaved calls, nested calls, late/missing parents, cycles and distinct Candidate/runs. Preserve expanded controls and bounded rendering on updates. Test malformed records, rolling decoder/history bounds, losses and days-long UI updates. Validate the widget in Jupyter using labelled simulated records, and keep real-provider runs under user control.

Expanded activity is flat terminal-style output: compact monospace model-call lines beneath plain stage headings, with no inner table, columns or grid.

The output sits in one bordered 280px-high scrolling well. Stage and model lines use the same compact rhythm, with status/timing inline and no report headings or separated columns. Console-specific classes prevent older notebook-output styles changing the layout.
