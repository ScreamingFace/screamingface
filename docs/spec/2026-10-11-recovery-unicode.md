# Recovery Unicode correction — OME-1503

The user requested fixing PR #1269's reproduced Unicode review finding.

Reject unpaired JSON Unicode surrogate escapes before the incremental parser can silently replace them. Preserve valid surrogate pairs and literal escaped backslashes. Validation must use bounded memory and reads. Invalid candidate results settle through the existing named failure and partial-report contract in sync and async recovery. No dependency, metadata schema, public API, or Engine change.

Use a sequential pre-check of JSON escape tokens rather than switching the entire parser to the slower Python backend. This adds one bounded sequential read on recovery, including when a derivative index is reusable. Checking reused indices is necessary because an older index and receipt can both describe already altered values. Escaped backslashes are consumed as whole tokens so literal text such as `\\ud800` is not mistaken for a Unicode escape.
