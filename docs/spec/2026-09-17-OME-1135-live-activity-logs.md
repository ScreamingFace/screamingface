# OME-1135 — Live activity within evaluation rows

Owner approved a Client implementation against Engine #980 with no older-Engine compatibility. The approved layout is one Candidate table, with stage-aware Status and independently expandable rows. There are no Evaluation/Logs tabs or compact/detailed switches.

## Researcher experience
Status uses Loading cases, Answering, Grading and Aggregating when received activity establishes the phase. Concurrent fresh phases are listed together. Stale observations are labelled Last observed; operation completion never implies a Case passed or the run succeeded. Authoritative final status, scores, Case counts and cost retain their existing meanings.

A keyboard-operable disclosure beside each Candidate opens a stable scroll box directly beneath its summary. All retained activity transitions are available with explicit case/model identity, parent stage, outcome and actionable supplied details. Groups are explicit stage occurrences; parent chains are resolved only within the same Candidate/run. Missing, evicted or cyclic parents remain Activity not identified. Late parent arrival may establish grouping. Never infer ownership from route names, model names, prose or timing.

The projection stores only allowlisted screamingface.activity.v1 fields, never raw Log bodies or private payloads. Supported kinds are case_loading, answering, grading, aggregation and model_call. Unsupported/malformed records do not affect callbacks or execution. The view discloses producer suppression, bridge loss, revision gaps and local truncation. Silence is no structured activity received, not proof of disabled policy or idle work.

## Bounded live state
A rolling history plus occurrence index retains at most 2,000 records / 8 MiB serialized data. Older routine history is evicted before unresolved or failure summaries; every category remains bounded. Each expansion renders a page of at most 100 retained events in receive order, with stage labels resolved from explicit parentage. Pagination and disclosure controls survive updates; scroll roots are never replaced. Fixed 200 ms update coalescing and a one-second quiet tick continue for the run lifetime, with no six-hour cutoff.

The decoder collision window retains at most 4,096 IDs / 1 MiB. Sequence cursors still reject old replay; ID uniqueness detection applies only within that bounded window. No durable archive, server storage, new URL4 capability or older-schema aliases.

Retained durations stay measured, never extrapolated provider progress; routine timing is omitted from the display. Stage freshness uses the approved conservative 30-second allowance / 180-second observation window; historical state is labelled rather than timed out. Missing completion is outcome not observed, and root termination ends incomplete displays without fabricated outcomes.

## Validation
Group interleaved calls, nested calls, late/missing parents, cycles and distinct Candidate/runs. Preserve expanded controls and bounded rendering on updates. Test malformed records, rolling decoder/history bounds, losses and days-long UI updates. Validate the widget in Jupyter using labelled simulated records, and keep real-provider runs under user control.

Expanded activity is flat terminal-style output: compact monospace stage and model-call lines in receive order, with no inner table, columns or grid.

The output sits in one bordered 280px-high scrolling well. Stage and model lines use the same compact rhythm, with status inline and no report headings or separated columns. Console-specific classes prevent older notebook-output styles changing the layout.

Presentation update: all log lines are flush left, with consistent compact text and no decorative separators. Model lines identify the supplied Case, explicit parent stage and model. Unknown Case stays explicitly unknown. Routine durations and normal stop reasons are omitted from the display; retries, failures, truncation and loss remain visible. Records retain safe structured details. Case ID display uses str(), preserving leading zeros, not an inferred ordinal.

## Approved chronological wording
The target log is a chronological sequence of lifecycle events, not only latest-operation summaries. Use “Synthesising with [model]” for an explicitly identified synthesis role. Case identity, execution stage and model role are separate facts: synthesis can occur within answering or grading and is not a fifth stage. Retain the four stages. Never infer roles from prompts, routes or model names; an unknown role falls back to “Calling [model]”. Programmatic grading must not claim a model call. Member identity and corrective-round number may enrich lines when explicitly supplied. Selected-case positions/totals require authoritative selection metadata, not arrival order or numeric parsing of case IDs. Whole-case completion must not be inferred from one grading endpoint returning. These are target presentation requirements; current producer attribution is incomplete.


## Selected-case numbering — 2026-09-18

Display authoritative case_position/case_count as [Case n/N]. Both must be positive integer facts with position <= count. Unknown positions retain existing Case ID fallback; never derive from event arrival order. Existing chronology, bounded history and safe payload rendering remain unchanged.
