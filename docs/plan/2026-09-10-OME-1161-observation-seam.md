# OME-1161 — Two sequential main-based PRs

1. Preserve the complete implementation at 01b3a0f1 on local branch
   `OME-1161-activity-preserved` before trimming existing PR 897.
2. Keep only Engine observation interfaces/dispatch, connector/executor/lifecycle hooks and
   explicit observer-factory injection with an empty default. Remove activity implementation,
   registration, deployment wiring and their tests from this PR, retaining them on that branch.
3. Keep generic fault/isolation tests. Add RED-first composition injection coverage, standalone
   unregistered execution, concurrent/cross-task cleanup and generic bridge-loss decoration.
4. Run full Engine gates and independent review. Rewrite PR/task descriptions for foundation
   scope. Push without force; do not merge automatically or open a second PR yet.
5. After the owner merges PR 897, create a fresh worktree/branch from origin/main. Restore the
   activity package, registration, deployment changes and activity-only tests from the preserved
   revision. Reconcile registration with explicit observer injection; retain all foundation tests.
   Relocate the two activity-only tests from the preserved `test_observation_seam.py` rather than
   overwriting the foundation file. Run independent gates/review and open the activity PR.

The approved feature contract remains unchanged. OME-1161 tracks the two deliveries and remains
open after the foundation merges. No stacked PRs are created.
