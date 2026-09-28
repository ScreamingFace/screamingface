# Verified Colab origin support

Owner authorized origin verification, implementation, tests and merge.

Observed in the live experiment notebook on 25 September: output origin
`https://6ernmmrpvem-496ff2e9c6d22116-0-colab.googleusercontent.com`, with
`https://colab.research.google.com` as its sole ancestor and referrer. Saved earlier
probes contain different random prefixes with the same Colab-specific suffix.
[Google's Colab FAQ](https://research.google.com/colaboratory/faq.html) describes separate origins for secure rich output, but does not
promise this precise hostname grammar. Treat it as a tested integration rule,
fail closed on future changes, and record reload evidence in the work ledger.

Add an explicit optional Colab profile alongside existing exact-origin support.
Match canonical HTTPS origins only, one bounded DNS label with alphanumeric random
prefix, 16 lowercase hexadecimal digits, numeric frame index, and `-colab` suffix
under googleusercontent.com. Reject credentials, paths, ports, nested hosts,
lookalike suffixes, null and global wildcards.

The iframe URL for this profile carries `parent_origin=<location.origin>`. The
service validates it before putting the exact output origin and Colab top origin
in frame-ancestors. This avoids a broad *.googleusercontent.com CSP: CSP cannot
express a wildcard within a DNS label. No analytics identifier is in this query;
proxy logs must omit queries as already required. Missing/invalid parent does not
open up CSP. JS also validates the same source-origin rule; replies stay exact.

Keep global bridge default disabled. Provide a complete opt-in Colab configuration
profile so the private dev deployment can enable it without per-notebook allowlists.
The SDK adapter must build the validated parent-origin URL when it is implemented.

Reload evidence: `https://1ruu7u27wb7-496ff2e9c6d22116-0-colab.googleusercontent.com`
with the same sole top-level ancestor; the live output-host prefix changed.
