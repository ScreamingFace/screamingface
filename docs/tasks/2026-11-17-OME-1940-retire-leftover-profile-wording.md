---
id: OME-1940
linear_url: https://linear.app/openmined/issue/OME-1940/name-the-credential-not-a-retired-profile-in-provider-errors-and
status: done
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-11-17
closed: 2026-11-17
---

# Name the credential, not a retired Profile, in provider errors and comments

The close review of `OME-1138` found Profile wording that the close-out did not cover. The
missing-tokens and rejected-refresh errors of the Anthropic, Antigravity, Codex and Gemini plugins
said "profile" and sent the caller to the retired desktop app; they now name the credential and ask
to reconnect the provider. The Gemini 401 without any credential now asks for a connected OAuth or
API-key credential. Gateway comments that described Profiles as present now name Connections; the
retired history stays. Eight gateway test doubles drop the `mutate` method that nothing calls since
the store port lost it. The SDK fixture part is `OME-1941`, in the same PR.

- Spec: `docs/spec/2026-11-16-ome-1138-leftover-profile-wording.md`
- Plan: `docs/plan/2026-11-16-ome-1138-leftover-profile-wording.md`
- Ledger: `docs/work/2026-11-16-retire-leftover-profile-wording.md`
- 2026-11-17: filed under `OME-1138` with `OME-1941`; the PR opened. In Review.
- 2026-11-17: PR #1874 merged as `d76e6a414`; Linear Done with the close-comment.
