---
id: OME-1679
linear_url: https://linear.app/openmined/issue/OME-1679/image-support-benchmark-path-give-the-fusion-synthesizer-the-cases
status: done
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1271
created: 2026-10-20
closed: 2026-10-27
---

# IMAGE SUPPORT - BENCHMARK PATH: Give the Fusion synthesizer the Case's inline pictures

A Fusion's synthesizer reads one JSON text, `{"input": <the Case input>, "outputs": …}`, which
url4 renders at run time. On a picture Case that text held the pictures as base64, so the
synthesizer never saw them.

- The engine connector now reads that text structurally: a JSON object of the Fusion shape the
  combine parser reads (`input`, exactly one of `outputs`/`panel`, no other key, no key twice)
  whose `input` is a v2 Case. Any other JSON is sent as written. It sends the Case's picture and file parts first, then today's text with each picture
  shown as a placeholder (`placeholder`, `index`, `media_type`, `size`, `filename` when named). The shared
  placeholder also carries a `sha256`, which the synthesizer's text leaves out: the model can't
  hash the picture, and results keep it so an opened picture can be checked against it.
- Reducer signal calls read the same object (with `panel`) and get the pictures too.
- Text-only Fusions send the same bytes as before, so goldens replay. On a grading call, a
  Fusion context holding a picture Case is refused by name, since a judge reads text only; what a
  grader reads of a picture Case is OME-1271 PR 3.
- A picture is accepted in one spelling only (lower-case type, no parameters, padded base64 with
  no spaces), at the envelope reader and the placeholder builder alike, so the connector never
  forwards a spelling the gateway refuses.
- Not covered: a Fusion used as another Fusion's synthesizer; its last synthesizer gets url4 text,
  not JSON, so the picture stays base64 there (OME-1741).
- One placeholder builder in the engine's envelope module (`media_placeholder`); the SDK's copy is
  pinned by a conformance test in each lane.

Owner verify: a picture Fusion end to end needs the importer (OME-1271 PR 2) and a vision model
behind the gateway. Review by someone other than Khoa (acceptance 4).

Ledger: `docs/work/2026-10-23-fusion-synthesizer-pictures.md`.
