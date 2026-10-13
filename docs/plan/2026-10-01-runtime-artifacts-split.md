# Independent report/runtime split plan

1. Record source head 10354d58 and main ba1545d8; prepare isolated worktrees.
2. Move runtime tests without changing assertions; run against main to reproduce the missing behavior.
3. Transplant the three runtime modules, split README/changelog/spec ownership, and remove extracted runtime work from the SDK branch.
4. Audit original test-definition preservation and unchanged implementation ownership. Run all gates independently for both trees.
5. Verify both merge orders and independent reviews; commit/push each branch. Update #1156 and prepare the runtime ticket/PR under E5.
