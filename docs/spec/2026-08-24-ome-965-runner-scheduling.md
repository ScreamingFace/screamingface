# OME-965 — Runner Job scheduling specification

## Problem

`K8sJobRunner` creates Pods without node selectors or tolerations. A deployment
can schedule the Engine control plane on a dedicated node pool, but its Runner
Jobs do not inherit that placement.

The Preview platform requires `openmined.org/pool=preview` and the
`workload=preview:NoSchedule` toleration. Admission rejects Runner Jobs that do
not carry both fields.

## Decision

The existing top-level Helm `nodeSelector` and `tolerations` values define
scheduling for both the Engine control plane and its Runner Jobs.

The chart serializes both values as JSON settings. The factory passes them to
`K8sJobRunner`. The adapter copies them into each Runner Pod specification.

The Engine code stays environment-neutral. It does not contain Preview labels,
taints, or toleration values.

## Constraints

- Empty scheduling values must omit both Job fields.
- The adapter must copy caller-owned mappings and lists.
- Runner Jobs must keep `automountServiceAccountToken: false`.
- No RBAC, Secret, image, or public API contract changes.
