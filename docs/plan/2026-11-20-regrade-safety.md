# Regrade safety implementation

1. Add journal and discovery regression tests reproducing all six review findings.
2. Add SDK tests for expected-target refusal before execution and before submission, sync
   and async, while preserving the existing unpinned API behavior.
3. Implement typed escaped journal keys and durable tail recovery; add persistent sidecar
   locking and pathname checks; make identical owner-resolution retries idempotent.
4. Add SDK expected-target checks and batch result validation, including already-regraded
   results. Require explicit source revision metadata during discovery.
5. Run focused tests, SDK/repo gates and an internal review. Reconcile #1993 after it merges.
6. Open the safety follow-up under OME-1958, document validation and leave rollout open.
   Stop before deployment or production regrading.
