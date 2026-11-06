# OME-1851: session filter preference

The homepage restores Has scores from `sessionStorage` before filtering its summary.
Only the exact saved string `false` disables it; missing or invalid values default to true.
Checkbox changes save the resulting choice. The checkbox is the only scored-filter control.
Remove the redundant include-unscored button. When scores hide all search matches,
the empty-state message directs the visitor to uncheck Has scores.
Read/write exceptions leave filtering functional, with the default on an unreadable reload.
Only this boolean is persisted. Search and page count retain their existing initialization.
No visual, API, database, dependency or permanent browser preference change.

Approved scope: the user's request to remember the checkmark when refreshing a session.
