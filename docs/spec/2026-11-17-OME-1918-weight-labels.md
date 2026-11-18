# OME-1918 — Weight label contract

The leaderboard labels are `open`, `closed`, and `hybrid`, without a weights suffix.
Hybrid means every declared model is recognized and the set includes both open and closed models. Use the existing registry, including routed model names. An operator override wins; unknown routes retain the conservative closed classification and missing declarations remain unidentified.

Keep the API's existing `openness` field and frontier statistics unchanged. Add `is_hybrid: true` only for confirmed hybrid ranked entries. Omit the flag otherwise for compatibility with existing responses. No model lists are exposed. The portal falls back to existing openness when the flag is absent, and only honors it for closed entries.

The current neutral styling and unknown dash remain. User explicitly requested implementation on 2026-11-17; lowercase overrides the general sentence-case design guidance for these labels.
