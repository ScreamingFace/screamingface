# OME-1525 spec — portal logo links home; one consistent breadcrumb

## Problem

On `origin/main` the portal top bar (`.rail`) is inconsistent:

| Page | Breadcrumb today |
|---|---|
| index.html | leaderboard |
| about.html | leaderboard / about |
| benchmark.html | portal / leaderboard |
| data.html | portal / data |
| spec.html | portal / leaderboard / spec |

The home page has two names, and "leaderboard" names both the home page and the benchmark page. The `😱 screamingface` brand is a `<span>`, so it doesn't link anywhere.

## Decision (owner, 2026-10-08)

"Logo is home." The brand links to `index.html`, and the breadcrumb only shows where you are below home:

| Page | Breadcrumb |
|---|---|
| index.html | 😱 screamingface |
| about.html | 😱 screamingface / about |
| benchmark.html | 😱 screamingface / *benchmark name* |
| data.html | 😱 screamingface / data |
| spec.html | 😱 screamingface / *benchmark name* / spec |

## Out of scope

- The right-hand site nav (benchmarks · about · github · docs) is already the same on every page.
- Page titles (`.masthead`), copy, and the vendored `style.css`.
