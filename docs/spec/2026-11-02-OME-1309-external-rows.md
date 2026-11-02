# E20: display imported external results

Approved scope: show the two imported dev SAT-English records through the existing
baseline API. This is a first UI increment, not completion of the epic.

Use a separate, unranked “External results” table below community submissions on
the same benchmark page. Each gray row shows model, native score, “External · Not
reproducible”, import date, source link, and a text comparison note when supplied.
No recipe action, rank, win styling, cost invention, or inclusion in summaries and
charts. Preserve the existing empty community-table state when only baselines exist.

Render source text through DOM text nodes and validate external URLs with the
existing HTTP(S) allowlist. Missing source/date/note stays explicitly unknown;
never infer model version, coverage, or compatibility. Render finite native scores,
including zero and negative values. Do not relabel arbitrary scores as percentages.

Hide the external section for absent/empty data and load errors. No new API,
migration, dependencies, benchmark-specific hardcoding, import history, editing UI,
source-health checks, or ranking policy. History and final ranking/comparability
policy remain separate E20 work. Linear changes require the user's prior approval.
