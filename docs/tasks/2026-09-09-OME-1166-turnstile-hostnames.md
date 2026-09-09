---
id: OME-1166
linear_url: https://linear.app/openmined/issue/OME-1166/enable-turnstile-any-hostname-for-anonymous-reporting
status: Backlog
type: configuration
priority: 3
labels: [auth+subsidies, human, autonomous]
created: 2026-09-09
closed:
---

# Enable Turnstile Any Hostname for anonymous reporting

Assignee: Stephen. Parent: OME-1002. Related: OME-1158, OME-1013.

Please enable Cloudflare Turnstile **Any Hostname** for the anonymous reporting widget so reports can be submitted from localhost, Colab and other hosted notebooks.

Public sitekey: `0x4AAAAAAEjIHU_eaxfIZ-u6`. Localhost currently returns `110200 — Domain not authorized`.

Follow [Cloudflare’s Any Hostname documentation](https://developers.cloudflare.com/turnstile/additional-configuration/hostname-management/any-hostname/). Confirm Enterprise entitlement and the documented server-side validation/monitoring safeguards; flag any blocker before enabling.

Done when the configuration is confirmed and we can rerun localhost/Colab verification. Keep Turnstile token validation and rate limits enabled; internal Cloudflare Access reporting is unchanged.

Related decision: `OME-1158`.
