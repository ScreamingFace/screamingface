# OME-1135 implementation plan

1. Bound decoder ID collision tracking, preserving sequence replay semantics.
2. Decode safe current activity fields into a bounded rolling projection.
3. Resolve stage parentage by Candidate/run occurrence; test missing, late and cyclic links.
4. Use stage-aware status and independent, stable per-Candidate disclosure/scroll controls. No tabs.
5. Test actual #980 producer records through the decoder, validate Jupyter rendering, and run Client gates.
6. Open draft PR with concrete justifications; keep Linear In Progress until PR ready for review.

Presentation refinement: replace inner tables with escaped monospace log lines; preserve grouped parentage and scroll/pagination controls.

Case-aware refinement: show explicit IDs/model/stage in flush-left prose; omit routine times/stops, retain retry/failure/truncation signals. Use local #980+#988 preview if hosted preview is disabled. Verify real Engine records and Jupyter before final gates.

Chronological-log follow-up: source case position/total from Engine selection, propagate case identity to stage events in #980, and render event transitions in #983. Verify explicit role attribution before enabling “Synthesising” on real calls; use “Calling” when unavailable. Cover concurrent/interleaved cases, programmatic/model grading, nested synthesis and corrective rounds without adding stages or inferring whole-case completion. The notebook wording prototype is illustrative only.


## Selected-case numbering — 2026-09-18

Add focused decoder/rendering tests, accept and validate the new optional pair, render the prefix, verify a native Engine producer preview and run full Client gates.


## Dynamic operation lines — approved implementation

Write latest-state, stable-order, parent-aware suppression, failure/staleness and pagination tests. Change the rendering projection and persistent scroll layout; migrate presentation assertions to the approved behavior while retaining decoder/loss/bounds tests. Run Client gates, exercise actual widgets in a fresh notebook, and push draft #983. Engine numbering migration and role attribution remain deferred.


The Status cell keeps stage-only wording. While a fresh stage supplies explicit case_position/case_count, Cases displays that active position (3 / 5), not the completed count (2 / 5). Internal completion accounting and final results remain unchanged. Concurrent active positions stay distinct; missing numbering retains the existing count fallback. Tests cover fresh, missing, concurrent, terminal and stale activity.

Use a full-summary native toggle hit area, with the existing HTML summary underneath and a shared bordered container around summary/details. Remove the separate header spacer. Preserve stable widget/scroll roots and verify pointer, keyboard and log-selection behavior in Jupyter.


Owner requested timestamps: show a quiet HH:MM:SS UTC first-observed time per operation, fixed across updates. Full date and timezone in tooltip; bounded index evicts with latest operation. Invalid calendar dates must not break rendering. Duplicate Grading lines remain distinct operations pending Engine case-level grouping.

Owner requested completed wording: Answered, Graded and Scores aggregated on success; active and failure wording remain distinct. Same dynamic operation line and timestamp.


Owner approved discrete case Grading lines: consume scope=case grading records, join numbering only by explicit candidate/run/case ID from retained answering facts, preserve ID-only fallback. Hide routine endpoint grading rows once case-phase records exist in that run; keep model calls, failures, unknown outcomes and raw history. Terminal revision wins over delayed starts; no execution or timing inference.

## Copy displayed activity — 2026-09-18
Owner requested a Copy control at the top right of each log box. Add a native keyboard-accessible button within the log viewport, pinned above its displayed page. Copy only rendered, safe text (timestamps, messages and partial-history notices), never raw event payloads or other candidates. Show Copied only on successful browser clipboard write; show an actionable failure label if unavailable. Reuse existing notebook HTML/clipboard pattern, no dependencies or Engine changes. Test button semantics and candidate isolation, then verify actual clipboard output in Jupyter and run Client gates.

## Neutral call wording — 2026-09-21
Owner approved Calling MODEL → Completed MODEL call on the same logical line, Retrying MODEL call and MODEL call failed. Retain first-observed timestamps, icons, operation identity, case numbering and stage status. Avoid implying member/synthesiser/judge roles. Client-only presentation change in #983. Migrate only the existing wording assertions authorized by this request; preserve behavioral assertions. Add lifecycle/role-neutral regression coverage, run full gates with the explicit append-only migration exception, and keep draft/In Progress.
