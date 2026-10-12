# Recovery Unicode correction plan

1. Add RED regressions for surrogate corruption and grouped recovery isolation.
2. Scan JSON escape tokens in bounded chunks before indexing. Require high and low surrogate escapes to be adjacent pairs; reject lone surrogates.
3. Check valid Unicode, escaped literal text, and token splits at read boundaries.
4. Run focused tests and SDK card gates; record results in the work ledger.
