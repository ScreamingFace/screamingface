# Implementation plan

1. Confirm existing-test migration and validation boundary; create new failing integration tests.
2. Replace synthetic row metadata with native index and explicit total; convert at candidate boundary.
3. Move collection validation into existing cases handlers and remove selector registration.
4. Migrate obsolete selector assertions and expression fingerprints only after approval;
   cached replays must retain prompts, scores, status and coverage.
5. Full Engine/Client gates; review and push #988. Rebase #980 onto it, rerun its gates and
   verify preview Client behavior. Keep existing review status unless owner requests a change.
