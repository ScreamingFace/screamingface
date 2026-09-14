# OME-1042 — Client implementation plan

1. Add failing tests at the model-details decoder and public Client.evaluate/AsyncClient.evaluate boundaries, including zero-dispatch proof and composed models.
2. Add optional validated access metadata to ModelDetails and decode the Gateway field.
3. Check that metadata in existing model preflight before parameter validation and Candidate dispatch; retain unknown compatibility.
4. Run focused tests, then all screamingface gates (including notebook/distribution checks).
5. Record wisdom/validation, commit, push with SSH keepalives, and open a Client-only draft PR linked to Gateway #932.
