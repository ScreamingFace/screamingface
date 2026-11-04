# Featured benchmark search — OME-1761

Approved scope: the existing ticket acceptance, authorized by Filip on 2026-10-30.

A nonblank query in the benchmark page's More benchmarks picker searches every
listed board, including featured tabs. Matching remains a trimmed, case-insensitive
literal substring of name or ID. A blank or whitespace-only query shows the current
nonfeatured overflow list. Featured tabs, catalog order, private exclusion, plain
navigation links and active-board indication retain their existing behavior.

The renderer passes its already visibility-filtered catalog into the picker. Search
uses that catalog once, avoiding duplicate featured results from concatenation.
No API, schema, dependency, homepage discovery, score filter or Escape behavior changes.

Regression coverage must drive the actual tab-strip renderer and search input handler,
not just the pure matcher with a hand-selected list.
