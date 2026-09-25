# The 😱 mark — vendored asset

The ScreamingFace mark, set **as the lowercase "o"** in the landing hero
(`Fusi[mark]ns, ranked and reproducible.`) via `.o-mark` in `style.css`.

## Why an image and not the emoji

`style.css` is explicit, from the system's own kerning audit (2026-07-17):

> Never set the raw OS emoji inside display type — its glyph box word-spaces the letters apart
> and dips below baseline like a descender.

So `Fusi😱ns` typed literally is a brand violation, not a shortcut. The mark is an `<img>`.

## Source

| | |
|---|---|
| Upstream | `https://brand.screamingface.ai/assets/mark/sf-mark-640.png` |
| Fetched | 2026-08-18 |
| Original | PNG RGBA, 608 × 640, 415,559 bytes |
| Source sha256 | `cdf5d9dbce79a8e9a2cb04eaec551de1c333c1c58af5589d8c2c35e68a5e56d8` |
| Shipped | `sf-mark-128.png` — PNG RGBA, 121 × 128, 26,410 bytes |

Only the 640 px PNG exists upstream. Other filenames (`sf-mark-128.png`, `sf-mark.svg`, …) return
`200` with an identical 211,712-byte body — a fallback page, not an image. Do not "restore" them by
copying that response.

## Resample

```sh
curl -sS https://brand.screamingface.ai/assets/mark/sf-mark-640.png -o sf-mark-640.png
sips -Z 128 sf-mark-640.png --out sf-mark-128.png
```

Resampling is not redrawing — the brand rule forbids recolouring, boxing or redrawing the mark, none
of which this does. 128 px is a 2× cushion: the mark renders at `.46em` of a `clamp(44px…76px)`
hero, so ~35 px tall at most.

Assets stay **app-local** under `portal/` — no CDN, no external host — so the public board
never depends on another origin at render time.

## Re-syncing

If the brand repo reissues the mark, re-run the two commands above and update the byte counts here
in the same change.
