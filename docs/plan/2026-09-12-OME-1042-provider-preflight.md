# OME-1042 — proposed implementation sequence

Status: awaiting owner decision on cross-service scope.

1. Create a coordinating epic and separate Gateway and Engine units; retain
   OME-1042 as the Client unit. Link dependencies.
2. Gateway: design a no-inference access-check contract around existing execution
   credential resolution, including local connections, hosted profiles, and
   profileless providers. Return no secrets. Prove success/missing/error behavior.
3. Engine: relay the contract with the same caller and profile as execution;
   preserve typed upstream failures. Add contract tests.
4. Client: call the check once per evaluation for all required providers/models,
   after planning and before starting observers or dispatching Candidates.
   Cover sync and async, partial access, hosted access, and discovery failures.
5. Refresh mock Engine fixtures for the added request without weakening existing
   behavioral assertions. Follow the test-preservation approval rule if required.
6. Run each landing's full gates and open separate draft PRs with dependencies.

No Client implementation should hardcode provider names or infer execution access
from model datasheets or local credential absence.
