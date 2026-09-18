# OME-1135 implementation plan

1. Bound decoder ID collision tracking, preserving sequence replay semantics.
2. Decode safe current activity fields into a bounded rolling projection.
3. Resolve stage parentage by Candidate/run occurrence; test missing, late and cyclic links.
4. Use stage-aware status and independent, stable per-Candidate disclosure/scroll controls. No tabs.
5. Test actual #980 producer records through the decoder, validate Jupyter rendering, and run Client gates.
6. Open draft PR with concrete justifications; keep Linear In Progress until PR ready for review.

Presentation refinement: replace inner tables with escaped monospace log lines; preserve grouped parentage and scroll/pagination controls.

Case-aware refinement: show explicit IDs/model/stage in flush-left prose; omit routine times/stops, retain retry/failure/truncation signals. Use local #980+#988 preview if hosted preview is disabled. Verify real Engine records and Jupyter before final gates.
