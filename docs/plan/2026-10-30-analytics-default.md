# OME-1768 implementation plan

Spec: ../spec/2026-10-30-analytics-default.md

1. Add failing SDK/service tests for conditional enrollment, disclosure order,
   first-operation waiting, and preservation of existing choices.
2. Service: add a conditional enrollment route and browser command, preserving
   the existing explicit accept and decline operations and event contract.
3. SDK: add conditional local storage, update the notice and display gate, hook
   import and evaluation, and add bounded automatic Colab setup.
4. Update obsolete opt-in expectations only where the authorized behavior changes;
   retain explicit-control, payload, and security assertions. Isolate test analytics.
5. Document the default and compatibility/deployment sequence; run both stack gates
   plus Node browser tests. Record any environmental limits in the work ledger.
6. Prepare the short decision-confirmation comment for Filip's approval; do not post.
