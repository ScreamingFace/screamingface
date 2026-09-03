# OME-984 — Colab theme detection for every notebook surface

Status: approved (owner, 2026-08-25) · Stack: screamingface

## Problem

OME-955 made the shared `.sf-ui` token block follow Colab's explicit `html[theme]` state, but
Leaderboards, notices, and connection provider-logo variants own independent theme rules. They can
still follow the browser or OS preference and render dark inside light Colab, or the reverse.

## Contract

- One internal helper generates the browser fallback, Colab, JupyterLab, and VS Code theme matrix.
- Shared widgets, Leaderboards, notices, and provider-logo variants use that matrix.
- Each surface retains its existing SFDS light and dark declarations exactly.
- Explicit host themes override the browser fallback; JupyterLab and VS Code behavior remains
  authoritative where their selectors are present.

## Acceptance

- Every independent notebook theme block contains explicit light and dark Colab selectors.
- Leaderboards, notices, and connection logos follow Colab's active theme.
- No visual token, data, API, or runtime behavior changes.
- Focused and complete ScreamingFace quality gates pass.
