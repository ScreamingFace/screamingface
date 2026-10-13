# Fusion quorum review fixes — OME-1557

The user approved fixing both PR #1340 review findings and pushing the result.

Nested quorum panels must receive enclosing binding values as resolved data. They
must not re-execute an upstream operation or count upstream input as a member success.
The URL4 AST lowerer currently drops incoming reference edges for Expressions. Capture
those values in the existing required GuardNode scope boundary, matching the lazy
text path's reference frame without changing the SDK's compiled expression.

Recipe export and replay must reject disagreement between executable quorum/member
dispositions and metadata. Default-valued metadata does not establish absence of
executable policy. Trigger the existing canonical comparison when either side carries
policy; preserve the established validation path for legacy compiled Recipes.

Permanent regressions must inspect real dispatched model request contents and reject
both omitted and explicitly defaulted policy metadata. Gateway/provider and judge
responses remain simulated; no paid verification is necessary for these defects.
