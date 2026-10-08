# streamed-atomic-report-export

Owner approved in the task conversation on 2026-10-05.

Extract the first independently mergeable client PR: case-streamed report.v1 serialization and durable atomic JSON export.

Original JSON bytes and public API remain unchanged; no persistence or notebook dependency enters this PR; all SDK gates pass.

All inherited tests remain intact. No paid model calls.

Throughput follow-up approved by the user: use standard JSON encoding within each
Case while streaming between Cases. Preserve byte compatibility and failure retention;
auxiliary export memory must not grow with the number of Cases.
