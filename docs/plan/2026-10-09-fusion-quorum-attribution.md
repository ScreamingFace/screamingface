# Fusion quorum attribution correction

1. Append tests demonstrating false attribution for optional shared fingerprints,
   including nested composite members and repeated calls. Add a Client-generated
   candidate fixture and a FrontierScience regression using a failed shared route.
2. Mark bindings under optional sources and suppress uncertain shared attribution
   while preserving unique-binding output/accounting and required-only behavior.
3. Run focused regressions, the original review reproduction, and all Engine card
   gates. Record the outcome and push the fix to PR #1340's existing branch.
