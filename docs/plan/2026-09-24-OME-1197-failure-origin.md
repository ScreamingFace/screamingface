# OME-1197 — Plan

1. Rewrite the draft's regressions around actual candidate execution and existing error.kind; prove RED.
2. Revert draft URL4 changes and connector stamps. Add Engine-owned CandidateExecutionError around candidate recipe execution, preserving diagnostics.
3. Classify IFEval orphan errors by kind, retaining protected grading precedence and unknown-error fallback.
4. Run Engine gates and IFEval replay; update existing draft description. No merge, new ticket or Linear comments.
