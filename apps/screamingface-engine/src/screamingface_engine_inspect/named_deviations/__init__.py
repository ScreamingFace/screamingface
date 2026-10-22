"""Named Deviations in grading: our scorers for Imported Benchmarks whose inspect_evals scorer
is wrong.

Think of each package here as an erratum slipped into inspect_evals' exam: the questions stay
inspect_evals' own (the row's Task and Case Digest are untouched), and only the marking changes,
to a fix inspect_evals has merged or proposed after the version we pin. We stay on that version
and adopt the fix as our own Named Deviation, so the row's NAMED DEVIATION comment cites the
inspect_evals PR or issue and a tripwire test asserts the pinned version's old verdict. When a
pin bump brings the fix, the tripwire fails and says to point the row back at inspect_evals'
scorer.

One package per marking rule, because each package's ``.py`` source is hashed into the
revision of every row it grades (``local_tasks.scorer_source_pins``): editing a package moves
all of those rows and no other. A package may serve several rows: ``yes_no/`` marks both paws
and boolq, so an edit to it moves both revisions.

INVARIANT: a module here imports nothing from ``screamingface_engine`` or
``screamingface_engine_inspect`` outside its own package, so the hashed source is the whole
marking code (``test_scorer_source_pins`` checks every module).
"""
