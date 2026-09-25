# Colab origins implementation

1. Record live output origin/ancestor evidence and reload comparison.
2. Add failing Python tests for bounded canonical origin matching and exact dynamic
   CSP; append Node tests for accepted Colab messages and hostile lookalikes.
3. Implement shared origin grammar, optional profile setting, dynamic page CSP,
   and strict JS matching without changing existing exact-origin behavior.
4. Add Helm profile wiring and append chart checks. Document the adapter URL and
   complete dev values; no changes to private deployment or public default enablement.
5. Run analytics gates/chart validation. Open PR, review and merge after green CI.
