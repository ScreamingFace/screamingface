# Fusion quorum rollout and repr follow-up — OME-1557

The user approved both nonblocking review corrections on PR #1340.

The README and PR description must require an Engine containing the patched URL4
scope propagation before using composed quorum Recipes. The Engine reporting
update must also be deployed to preserve member outputs and accounting. URL4
already supported quorum and optional-source execution; no new quorum feature is
being added by this follow-up.

Fusion repr must distinguish optional members from required members for Model,
Pipeline, and nested Fusion Recipes. Render each optional member using its Recipe
repr, preserving the existing name-only rendering for required members. This is a
diagnostic display change; executable URL4, public signatures, and replay stay as is.
