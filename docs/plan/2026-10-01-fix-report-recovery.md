# Recovery follow-up plan

1. Append regression tests for malformed membership and overlapping actual Report presentation/export boundaries; confirm failure.
2. Add membership validation at manifest load and structured errors at recovery decode for incomplete legacy context.
3. Add a scoped presentation operation tracker; preserve mark_report compatibility and existing marker shape.
4. Run the screamingface quality gates and read-only review, record results, commit locally and provide an applicable patch. Do not post or push.
