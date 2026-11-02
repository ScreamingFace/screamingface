# Served-cost repair — OME-1517

1. Add failing HTTP regressions for both read surfaces and all three cost columns.
2. Read narrow raw projections through the existing safe decoder; preserve valid
   history parts and translate unreadable parts only for served history rows.
3. Verify healthy sums, null savings, owner filters and export bytes; check PostgreSQL.
4. Run gates, review the diff, record results, commit and open a linked PR.

## Review follow-up — 2 November 2026

Replace driver-message regex matching with the structured PostgreSQL exception and SQLSTATE. Add explicit public-history corrupt-cost coverage and a projection/schema consistency guard. Preserve production behavior and all existing assertions except the authorized stronger error assertion.
