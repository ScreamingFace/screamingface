# Each paid-smoke dataset source links to its pinned commit, and the labels ship in the debug bundle

Status: implemented 2026-10-08 · OME-1524 (one PR) · ledger
`docs/work/2026-10-08-provenance-links.md` · builds on
`docs/spec/2026-10-06-OME-1492-bundle-provenance.md`. The design, the Before/After and the
source-kind table live in the Linear issue; this file records the decisions made while
building it.

## TLDR

Case Preparation writes a label, `provenance.json`, beside each bundle's Cases: for each
source it read, the place (`location`) and the exact version (`pin`). The paid smoke's run
page turns the labels into its "Where the Cases came from" table. Now each source also gets a
`url`, a browser link to that source, built by the code that read it: a Hugging Face or
GitHub source at its full commit, a plain web download at its own address.
The table draws a source with a link as that link, and the smoke copies each label into the
debug bundle as `provenance/<benchmark>.json`. No existing label field, Case or score
changes.

## Decisions

- **One link builder, in core.** `hugging_face_url` and `github_file_url` live in the core
  provenance module; the hand-built preparers call them directly, and the inspect plugin's
  fetch recorder imports them (core never imports a plugin, a plugin may import core).
- **A Hub or GitHub link only at a full 40-hex commit.** A branch, a tag or a short sha moves
  or is ambiguous; a link to it would claim more than the pin does. Such a source has no `url`
  key. A plain web download is different: it links to its own address whatever its pin (the
  ticket's source-kind table), because that address is the only place to look.
- **The plugin builds the link when it records the fetch.** The location text cannot say what
  it names: `TsinghuaC3I/MedXpertQA/Text` (a config) and
  `dgslibisey/MuSiQue/musique_ans_v1.0_dev.jsonl` (a file) have the same shape. A dataset
  load or snapshot links the repo's tree; a single-file download links the file's blob
  (`subfolder` joined in); an http(s) download links its own address.
- **`web_url()` is unchanged.** The importer writes it into a new declaration's
  `dataset_url` (the repo page, no commit); changing it would change import output.
- **The link is not part of a Case Source's identity** (`compare=False`): the call that fixed
  kind, location and pin also fixed the link, so de-duplication and every existing
  comparison are unchanged.
- **Hub links for dataset repos only.** A model or Space page lives at another address, and a
  wrong link is worse than none.
- **The run page escapes and filters.** `\`, `|`, `[` and `]` in the link text are escaped;
  the target is percent-encoded except URL punctuation, so `|`, `)` and spaces cannot break
  the row; only `http(s)://` targets become links (the label is build data).
- **The copy runs in the test, not as a workflow step,** so the local `just` twin produces the
  same files and the workflow is unchanged. It copies labels only, never `cases.json`.

## Known limitations

- A link 404s if the dataset owner deletes the repo or rewrites history; the pin, not the
  link, is the record.
- An unpinned web download (PIQA's `tests.jsonl` on yonatanbisk.com and its Cloud Storage zip)
  links to an address whose bytes can change after import (the Case Digest still refuses
  Cases built from changed bytes; the link alone would show them). Accepted for now: the cell still
  reads `@ unpinned`, so the link is never shown as a commit. Linking only a pinned URL source
  (a commit in the path or a sha256) is the follow-up if this misleads.
- Changing the provenance writers changes the asset cache key, so the first press after merge
  re-prepares every bundle once.
- The debug bundle's link text in the workflow still lists "stack logs, one Report per
  Benchmark, junit.xml"; the workflow is untouched by design, so it does not name the labels.
