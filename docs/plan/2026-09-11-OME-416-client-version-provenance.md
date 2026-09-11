# OME-416 — Client implementation plan

1. Add failing tests for exact Engine request headers and deterministic notebook stamps.
2. Add a small shared header helper using the installed-version resolver; wire all four Engine
   HTTP client constructors. Keep existing auth, tracing, retries and request semantics.
3. Add source-project version metadata to the notebook builder and regenerate examples.
4. Run the new tests, full Client gates, and inspect notebook diffs for metadata-only changes.
5. Commit, push and create a draft PR. Update Linear description directly without comments;
   retain open status for Engine retention/returned provenance work.
