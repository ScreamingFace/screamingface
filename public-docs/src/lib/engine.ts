// The hosted SF Engine the documentation points at.
//
// Every code sample interpolates this constant, so replacing the value here
// updates all of them.
export const SF_ENGINE_URL = 'https://fusion.dev.screamingface.ai'

// The leaderboard paired with SF_ENGINE_URL. The SDK refuses a non-default engine without its
// scoreboard, so every sample that names SF_ENGINE_URL through sf.configure names this too.
export const SF_SCOREBOARD_URL = 'https://leaderboard.dev.screamingface.ai'
