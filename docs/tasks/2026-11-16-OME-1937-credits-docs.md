---
id: OME-1937
linear_url: https://linear.app/openmined/issue/OME-1937/document-provider-credit-visibility-e5-p3-on-the-docs-site
status: In Progress
type: product-feature
priority: Medium
labels: [client-sf, agentic, autonomous]
parent_epic: OME-1294
assignee: Irina Bejan
created: 2026-11-16
closed:
---

# Document provider credit visibility (E5 P3) on the docs site

User-facing documentation for the E5 P3 provider-credit-visibility feature on `public-docs`:

- New API reference page `public-docs/src/pages/sf-client/api/CreditsPage.vue` (`sf.credits()` /
  `Client.credits()` / `AsyncClient.credits()`, `CreditStatus`, `CreditAmount`, states, reasons,
  management-key setters).
- Route + sidebar nav entry (API reference → Classes, after Connections).
- A `See your provider credit` section folded into the Connections guide
  (`/sf-client/guides/connections#see-your-provider-credit`), cross-linked with the API page.

Docs-only. Gates (type-check / lint / build) green. Follow-on rich-repr work: OME-1935.
Work ledger: `docs/work/2026-11-16-credits-docs.md`.
