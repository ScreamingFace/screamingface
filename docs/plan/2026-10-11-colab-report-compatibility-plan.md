# Colab report compatibility implementation

1. Verify the widget-7 route in the fresh live notebook; no runtime package mutation in library code.
2. Write failing host/delivery/dependency-contract regressions.
3. Add a small host adapter and native Colab delivery and Case selection callbacks; retain existing Jupyter branch and atomic snapshot writer.
4. Adjust optional dependency range, lock and README setup guidance. Verify widget 7 and widget 8 behavior.
5. Build wheel, repeat live browser interaction/download checks, run full SDK gates and two independent reviews.
6. Record evidence and update the existing draft PR. No merge and no GitHub comments.
