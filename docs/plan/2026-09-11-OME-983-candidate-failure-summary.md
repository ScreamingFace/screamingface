# OME-983 — Implementation plan

1. Add regression tests using existing Candidate/Case fixtures and observe the original failure.
2. Derive summary lines by iterating Report Candidates and grouping their failures independently.
3. Escape the complete resulting text through the existing rendering boundary.
4. Run existing and added tests, stack gates, and render the user's example in light/dark themes.
5. Show the local preview; wait for user satisfaction before starting Linear or opening a draft PR.

Approved refinement: use a Candidate heading and indented failure list per Candidate, preserving
existing error wording. Direct Linear description/status updates authorized; no comments.
