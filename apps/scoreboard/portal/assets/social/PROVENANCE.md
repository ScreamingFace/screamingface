# Link-preview card — vendored asset

`sf-og-1200x630.png` is the image Slack, X, LinkedIn and iMessage show when someone shares a
leaderboard link. Every portal page points its `og:image` and `twitter:image` at it.

## Source

| | |
|---|---|
| Upstream | `https://brand.screamingface.ai/assets/social/downloads/sf-og-1200x630.png` |
| Fetched | 2026-10-15 |
| Shipped | PNG RGB, 1200 × 630, 74,769 bytes, unchanged from upstream |
| sha256 | `028a6df4e52e123814dcd67f822236463663afdca05ef3d3ba38627cefdec5f7` |

It is the brand guide's own link card (the mark above the `ScreamingFace.ai` wordmark), the same
file the earlier screamingface.ai landing page used. It ships app-local so a preview never depends
on another host.

## Re-syncing

```sh
curl -sS https://brand.screamingface.ai/assets/social/downloads/sf-og-1200x630.png -o sf-og-1200x630.png
```

Update the byte count and sha256 here in the same change. Crawlers need an absolute URL, so the
pages name `https://leaderboard.screamingface.ai/...`; if the board moves host, update the meta tags.
