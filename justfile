# Repo-root entry point. Each component keeps its own justfile; this only makes them
# reachable from the root, so `just` never depends on which directory you happen to be in.
#
# A module runs its recipes IN the module's directory, so the recipes need no path
# awareness and still work when invoked from inside the component:
#
#   just screamingface local-stack-notebooks   # from the repo root
#   just local-stack-notebooks                 # from packages/screamingface
#
# Add a component here when it grows a justfile; never re-implement its recipes.

set default-list := true

mod screamingface 'packages/screamingface'
