# Bounded notebook report pagination and navigation

User authorized the next #1156 slice and before/after screenshots on 2026-10-11 after #1345 merged. This is the planned pagination/navigation slice; lifecycle discovery/notices remain later work.

Render 25 Case results per page in a live notebook with previous/next, an exact Case-ID field, all/candidate filtering and linked Candidate names. Preserve integer and string identities (including padding and collisions), grouping shared IDs across Candidates while retaining distinct results. Navigation uses compact identities, and reads only the requested page payloads after initial accounting derivation. Keep the existing answer/grading and cost panels.

Only current page payloads enter widget state. Static HTML shows a bounded first-page preview and caps oversized panes and inline JSON. Notebook full downloads use the existing streaming atomic export on demand with a file-backed link; failures permit retry. Async navigation/export must keep the kernel responsive and avoid stale publication and duplicate work. No automatic model runs or recovery downloads.

Preserve all merged report fields, Named Scores, archive savings, exact JSON export and accounting output. Add DOM click events only to the optional notebook extra; without widget dependencies, fall back to static HTML. Preserve the existing rejection of empty Reports/Candidates. Bad Case IDs and disk errors must keep controls usable. No lifecycle integration or Engine work.

Before/after screenshots use the same representative report and actual SDK rendering. Inspect light and dark and demonstrate navigation to a later page.
