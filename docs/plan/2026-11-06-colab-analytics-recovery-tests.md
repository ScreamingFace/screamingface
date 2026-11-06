---
ticket: OME-1768
---

# Plan: failing Colab recovery tests

1. Add an isolated test module using the existing Colab browser fixture.
2. Simulate only the browser exchange boundary; call real Client.evaluate and
   AsyncClient.evaluate with invalid inputs and assert the expected TypeError.
3. Cover setup state/ID failures, delivery failures, and actual setup expiration.
   Synchronize with worker notifications/events, not guesses about completion.
4. Add healthy delivery and opt-out controls. Block unexpected network access.
5. Run the new tests against current main and the published 0.1.11 wheel.
   Confirm failures occur at recovery assertions, not fixture or import errors.
6. Run existing Colab analytics tests and lint/format checks. Leave new regression
   tests intentionally failing; do not change product code. Filip subsequently
   requested publishing this state as a draft PR with the red results disclosed.

## Authorized implementation

7. Retry unknown Colab consent from normal entry points; retain the five-second
   bound and deduplicate concurrent setup.
8. Keep recovery generations, waiter expiration and operation consent revisions
   consistent so stale work cannot revive tracking.
9. Add safe local diagnostics and tests for malformed/late responses, thread start,
   queues, concurrent evaluations, explicit controls and opt-out races.
10. Run targeted tests, SDK and repo gates, package checks and CI. Update the
    existing PR and provide a small Colab verification cell for the patched build.

