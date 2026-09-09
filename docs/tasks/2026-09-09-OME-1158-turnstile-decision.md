---
id: OME-1158
linear_url: https://linear.app/openmined/issue/OME-1158/choose-the-turnstile-verification-flow-for-anonymous-notebook-reports
status: Backlog
type: design-session
priority: 3
labels: [py-screamingface, human, design-session]
created: 2026-09-09
closed:
---

# Choose the Turnstile verification flow for anonymous notebook reports

Parent: OME-1013. Assignee: Keelan Jordan. Milestone: Fusion Monsters Launch.
Related service work: OME-1011 and OME-1012.

## Decision needed

Choose where the Client runs Turnstile for anonymous notebook reports before finalizing the anonymous flow in `OME-1013`. This is an owner design decision, not approval to change Cloudflare settings or build a hosted page.

## Options

1. **Embedded in supported notebooks:** allow `localhost`, `127.0.0.1`, and `colab.googleusercontent.com` on the appropriate widget, then verify local Jupyter and Colab. Avoids a new tab; shared hostnames also allow other users' pages/notebooks to use the public widget. Does not automatically cover remote Jupyter/JupyterHub, Kaggle or VS Code.
2. **ScreamingFace-hosted verification:** run the challenge on an approved reporting hostname (dev: `reports.dev.screamingface.ai`; production hostname to confirm). Investigate embedding versus a new tab; securely bind and hand off the short-lived token to the initiating notebook. No report payload or credentials in URLs; keep explicit Send and honest cancellation/failure recovery.
3. **Any Hostname:** evaluate only if deliberately required. Cloudflare documents this as Enterprise-only and recommends additional server-side hostname validation and monitoring. It is not the default proposal.

## Evidence

- Owner supplied the anonymous public sitekey.
- Real Chrome localhost probe on 2026-09-09 loaded the widget and returned **110200: Domain not authorized**. No token issued and no report submitted.
- Colab output frames observed in Chrome use changing subdomains of `colab.googleusercontent.com`. Cloudflare accepts the base hostname without `*.` and includes its subdomains. This does not establish support for every Colab variant or successful token handoff.
- Internal browser sign-in reached the API's expected GET 405 response. Successful internal/anonymous POSTs, persistence, idempotency and delivery remain unverified.
- Allowing localhost is supported; Cloudflare recommends excluding local domains from production sitekeys. Keep dev and production policy explicit.

## Acceptance

- Owner records the chosen approach, initially supported notebook hosts and dev/production hostname policy.
- If hosted, decide page ownership and embedded/new-tab UX; specify secure token handoff, expiry, cancellation and unavailable-widget recovery.
- Identify the necessary real Jupyter/Colab acceptance checks, plus accepted dev POST and backend verification.
- Update `OME-1013` spec/plan with the resolution. Keep implementation there; create a separate service child only if hosted-service changes are chosen.
- Do not reopen duplicated `OME-1014`, mix this into analytics, or treat this ticket as a second Copy/Report implementation.

## References

- [Cloudflare hostname rules](https://developers.cloudflare.com/turnstile/additional-configuration/hostname-management/)
- [Local testing guidance](https://developers.cloudflare.com/turnstile/troubleshooting/testing/)
- [Any Hostname](https://developers.cloudflare.com/turnstile/additional-configuration/hostname-management/any-hostname/)
- Existing evidence: `docs/work/2026-09-07-OME-1013-report-auth-integration.md`
