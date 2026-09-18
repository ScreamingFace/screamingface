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
