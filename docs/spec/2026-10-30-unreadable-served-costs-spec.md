# Unreadable served costs — OME-1517

A malformed or non-finite run cost or either cache saving makes the served cost
unknown in my_submissions and spec history. Preserve other entries and all access
filters, ordering and history limits. A missing saving is still distinct from an
unreadable saving. Valid costs follow the existing reproduction_cost rule.

Use the existing raw decoding/degradation policy. Avoid ORM decoding the bad
amount before that policy runs. Keep history's narrow projection and leave
_score_to_schema, stored rows, receipts, private export and deletion untouched.
