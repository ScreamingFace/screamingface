# External source availability

An outside result remains ranked and retains its Source button when its source cannot be checked. Show “Source unchecked” and “Last available <date>” beneath the button; if no check has succeeded, show “No successful check yet”. A successful recheck clears the notice. This checks reachability, not score correctness.

Store last attempt, last successful attempt, and current availability by exact source URL, separate from edit history. Unknown legacy status remains unknown. Public board reads expose only these facts, never perform network requests, and do not change eligibility.

Operator runs a board-scoped command after migration. Each distinct URL is requested once. Follow at most five redirects, reject non-public destinations at every hop, pin the connection to checked IPs with correct TLS hostname, send no credentials, ignore environment proxies, and stop within a per-source deadline. Stream headers without downloading bodies. Keep scores when any check fails.

Automated scheduling, score refresh, content verification, manual-entry forms, and source selection are outside this change.
