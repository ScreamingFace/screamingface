"""Who is calling, and whether they may (spec §7).

Three modules and a decision function:

- :mod:`report_intake.identity.mesh_identity` — the mesh-injected address, and the ONLY module
  in this service that names the header it arrives on.
- :mod:`report_intake.identity.rate_limit` — the anonymous budget, keyed on a peer the caller
  cannot choose.
- :mod:`report_intake.identity.turnstile` — the bot gate.
- :mod:`report_intake.identity.gate` — the order they run in, which is the policy.
"""
