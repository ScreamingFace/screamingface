---
id: OME-2042
linear_url: https://linear.app/openmined/issue/OME-2042/prove-packaged-sdk-runtime-upstream-attempt-counts
status: In Review
type: task
priority: high
labels: [client-sf, autonomous, task]
parent: OME-1306
created: 2026-11-26
closed:
---

# Prove packaged SDK runtime upstream-attempt counts

Router Recipe extension Unit 5.1 requires a compatibility proof against the LiteLLM version shipped
by the Client SDK's `runtime` extra. The proof boots the packaged runtime Gateway, replaces only the
physical provider transport with deterministic HTTP fakes, and compares independently observed sends
with `X-AIGW-Upstream-Attempts`.

Hugging Face and Ollama each cover one physical send and LiteLLM's hidden resend with taxonomy
accounting enabled and disabled. A negative control removes the observed-client injection and proves
that a false zero cannot satisfy the check. The test uses no provider credentials or paid calls and is
discovered by the existing Python 3.12 E2E Replay workflow without a workflow change.

Spec: `docs/spec/2026-11-16-router-recipe-extension/` C7 and test plan section 4.
Plan: `docs/plan/2026-11-16-router-recipe-extension.md` section 6.
Ledger: `docs/work/2026-11-26-sdk-runtime-upstream-attempts.md`.
Branch: `OME-2042-sdk-runtime-upstream-attempts`.
