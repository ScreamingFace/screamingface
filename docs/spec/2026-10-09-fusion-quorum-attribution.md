# Fusion quorum attribution correction — OME-1557

The user requested the fix for the reproduced PR #1340 review finding.
An optional member that fails must not inherit another member's output or finish
reason merely because both operations use the same route and parameters.

Keep the existing route/parameter attribution and unique-binding accounting.
Track model bindings inside optional source subtrees, including complete composite
members. When multiple bindings claim a fingerprint and any claimant may be absent,
leave their outputs and finish reasons null: identical observed answers or a matching
call count cannot prove every claimant executed. Retries can produce multiple calls
from one successful operation. Required-only ambiguous fingerprints retain their
existing identical-output policy. No request identity, prompt retention, wire shape,
SDK compilation, or runtime execution changes are needed.

Regressions must cover optional direct and composite sources, multiple identical
calls, distinct fingerprints, and actual FrontierScience gateway dispatch/reporting.
