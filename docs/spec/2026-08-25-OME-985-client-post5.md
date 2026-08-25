# OME-985 — ScreamingFace Client 0.1.1.post5

Status: approved (owner, 2026-08-25) · Stack: screamingface

## Problem

Client changes merged after `0.1.1.post4` need a new installable release. The automated
release-please line remains behind the manually published post-release sequence.

## Contract

- The Client package version becomes `0.1.1.post5` in both manifest and lockfile.
- Dependencies, source, public API, and runtime behavior do not change.
- The existing release-automation reconciliation warning remains explicit.

## Acceptance

- Manifest and lockfile agree on `0.1.1.post5`.
- A fresh package build reports `0.1.1.post5`.
- The complete ScreamingFace package and distribution gates pass.
