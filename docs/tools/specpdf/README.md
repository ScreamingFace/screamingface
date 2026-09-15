# specpdf — the OME-1110 url4 topology PDF build

One markdown source renders as two PDFs in the SFDS dark register:

| | |
|---|---|
| **core** | `§0–§9` + Appendix C — the settled definitions |
| **open-work** | `§10–§13` + Appendix A/B/D — the questions, the spec deltas, the crosswalk |

```sh
uv run build.py --part all          # both, into docs/spec/
uv run build.py --part core         # just one
uv run build.py --part all --html   # keep the intermediate HTML, to debug the CSS
uv run --with pytest python3 -m pytest tests/
```

`pandoc` must be on `PATH` (`brew install pandoc`). Everything else — WeasyPrint, the IBM Plex
faces — is pinned or vendored here, so the build does not depend on what happens to be installed.
On macOS `build.py` re-executes itself with Homebrew's `lib` on `DYLD_LIBRARY_PATH`, because
WeasyPrint dlopens `libgobject`/`libpango` by bare name and the loader will not find them
otherwise.

## Why this exists

The 2026-09-08 render of this document was produced by a script in a session scratchpad, and the
PDFs were committed without it. When Kevin's Part A §1.4 refresh landed a week later the pipeline
was gone — the tmp reaper had emptied the directory — and the document could not be revised at
all. See ledger deviation (2) in `docs/work/2026-09-04-OME-1110-url4-topology-reframing.md`.

## The pieces

| File | What it owns |
|---|---|
| `split.toml` | which sections land in which PDF, and each part's title page |
| `build.py` | markdown → HTML → PDF, plus the checks below |
| `sfds-print.css` | the print register: page furniture, type scale, tables, figures, callouts |
| `fonts/` | IBM Plex Sans + Mono, vendored (OFL 1.1) |

## What the build refuses to do

These all produce a document that renders but is quietly wrong, so they are errors, not warnings:

- **A section claimed by no part, or by two.** It would vanish from both PDFs, or print twice.
- **An unescaped `|` inside a code span in a table row.** GFM reads it as a cell separator even
  inside backticks, so the row keeps rendering with every later column shifted one to the left.
  This silently cost §12's "Non-HTTP credentials" row its resolution cell. Write `` `a \| b` ``.
- **A missing dark diagram.** The markdown embeds the light SVGs so it reads on GitHub; the PDF
  swaps in the `-dark` twin, and a missing one would otherwise render as a blank box.

## Conventions worth knowing

- **Cross-references.** `§7` becomes an internal link when §7 is in the *same* PDF, and stays
  plain text when it is in the companion — a dead link is worse than none. `§29.2.1` is left
  alone: dotted references are spec anchors, not sections of this document.
- **Matrix tables.** A table whose first header cell is empty uses column 1 for row labels. Auto
  layout starves that column and the labels overlap their neighbour, which is how "Three
  candidate mechanisms" rendered as "Whereredentialslive". `build.py` tags such tables and the
  stylesheet gives the column a width.
- **Headings do not end a page.** `break-after: avoid` keeps a heading with its content; without
  it, a figure that will not fit leaves 40% of the sheet blank, as on core p6 and p8.
