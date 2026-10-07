# Every hand-built bundle says where its Cases came from

Status: implemented 2026-10-07 · OME-1492 PR 3 of 3 · ledger
`docs/work/2026-10-07-hand-built-provenance.md` · builds on
`docs/spec/2026-10-06-OME-1492-bundle-provenance.md` (PR 1)

## TLDR

**Case Preparation** is the image-build step that fills each Benchmark's **bundle** (its folder
of Cases in the Engine image). #1268 made it leave a small label in every Imported bundle,
`provenance.json`: which dataset commit it read, any seed it forced, how many rows it loaded and
kept, and how long it took. The same block rides the bundle's summary line in the build log, and
the paid smoke's run page shows it per Benchmark under "Where the Cases came from".

The rule that must hold: every bundle on the run page says where its Cases came from, without
anyone re-running the build.

Where it fell short after #1268:

- the six **hand-built preparers** (draco, ifeval, healthbench, gdpval, medxpert, contracteval:
  the Benchmarks we wrote by hand, not imported from inspect) wrote no label;
- four Benchmarks read another Benchmark's bundle (draco-3pass, both HealthBench Benchmarks,
  gdpval-text), so the run page looked in a folder that doesn't exist.

The change: each hand-built preparer writes the same block, before `cases.json`, and adds it to
its summary. The file name, the summary key and the writer move into the Engine core, so both
kinds of preparer share them without core importing the inspect plugin. The run page maps the
four Benchmarks to their shared bundle and shows "—" for an inspect version a hand-built bundle
doesn't have. No Case text is ever written, and no Benchmark Revision moves.

## Before / After

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 440}}}%%
flowchart TB
  subgraph TODAY["TODAY — hand-built rows read 'not recorded'"]
    direction LR
    a1["🤖 GDPval preparer loads openai/gdpval<br/>at 11e7900c, keeps 102 of 220"] --> a2[("gdpval bundle<br/>cases.json only")]
    a2 --> a3["⚠️ run page row gdpval-text<br/>looks in gdpval-text/ — not recorded"]
  end
  subgraph AFTER["AFTER — every row names its source and counts"]
    direction LR
    b1["🤖 GDPval preparer loads openai/gdpval<br/>at 11e7900c, keeps 102 of 220"] --> b2[("gdpval bundle<br/>provenance.json, then cases.json")]
    b2 --> b3["✅ run page row gdpval-text reads gdpval/<br/>openai/gdpval @ 11e7900c · 102 of 220 (118 excluded)"]
  end
  TODAY ~~~ AFTER
  classDef bad   fill:#7f1d2b,stroke:#e5484d,color:#ffe8ea
  classDef good  fill:#14532d,stroke:#30a46c,color:#dcfce7
  classDef data  fill:#4c1d95,stroke:#a06ed4,color:#ede9fe
  classDef stage fill:#1e3a8a,stroke:#4a7fd4,color:#dbeafe
  class a1,b1 stage
  class a2,b2 data
  class a3 bad
  class b3 good
  style TODAY fill:#111827,stroke:#e5484d,color:#e5e7eb
  style AFTER fill:#111827,stroke:#30a46c,color:#e5e7eb
```

## Architecture / Design

**How to read this section.** The circled numbers ① to ⑦ in every diagram here are the
Architecture map's boxes, so "③" is the same code in Data Flow, the Failure-modes table and the
Review order (③a, ③b are parts of one box). Read Data Flow first: it follows one example, GDPval,
from the Hub to its run-page row (*how* it works). Then Failure modes, rows F1 to F5 (*what
breaks*, and who notices). Keep the Architecture map (*where*: which files, new vs changed) open
beside the Review order while reading the diff. In each diagram, read the HOW TO READ key first,
then follow the numbers top to bottom.

### Data Flow

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 460}}}%%
flowchart TB
  KEY["HOW TO READ — colours here mean the kind of step, not change status as in the Architecture map<br/>blue box = a step that runs code · purple cylinder = where data rests · green = what a human sees<br/>dashed arrow = a network hop to the named party · ① to ⑦ = Architecture map boxes<br/>tags: ⏱ time · 💾 space · 🌐 moving · 🔐 trust · 🧩 meaning"]
  KEY ~~~ S4
  S4["①+② INPUT · the image build or the paid smoke prepare step runs the GDPval preparer<br/>python -m screamingface_engine.benchmarks.prepare --bundle gdpval<br/>example used in every box: e.g. bundle: gdpval"]
  HUB(["Hugging Face Hub"])
  S2a["③a load the pinned rows · load_rows · gdpval/prepare.py<br/>e.g. dataset: openai/gdpval · revision: 11e7900c · rows loaded: 220<br/>🌐 MOVING: pinned to a commit, so the same rows every build"]
  S2b["③b keep the frozen selection, fetch its reference files · emit, _build_reader<br/>e.g. kept: 102 · reference files fetched: 58, for 36 of the Cases<br/>🌐 MOVING: the files come from the dataset's main branch, no hash"]
  S1["④+③c build the label · hand_built_provenance, _case_sources<br/>e.g. sources: openai/gdpval @ 11e7900c, reference_files (58 files) @ unpinned<br/>e.g. samples: yielded 220 · excluded 118 · kept 102 · pins: none<br/>🔐 TRUST: counts, commits and locations only, never a Case's text"]
  D1[("③ provenance.json in the gdpval bundle, written FIRST<br/>💾 SPACE: under 1 KB · lives in the image and the paid smoke's asset cache")]
  D2[("③ cases.json, written LAST · the 'bundle finished' marker<br/>⏱ TIME: a crash between the two leaves an unfinished bundle, re-prepared next run")]
  S6["⑥ press-page helper finds the label · provenance_markdown · _case_provenance.py<br/>e.g. Benchmark: gdpval-text → shared bundle folder: gdpval<br/>🧩 MEANING: four Benchmarks read another Benchmark's folder"]
  S7["⑦ OUTPUT · 'Where the Cases came from' row on the paid smoke run page<br/>e.g. gdpval-text · openai/gdpval @ 11e7900c + reference_files (58 files) @ unpinned · 102 of 220 (118 excluded) · inspect-evals —"]
  S4 --> S2a
  S2a -. "downloads the rows at the pinned commit" .-> HUB
  S2a --> S2b
  S2b -. "downloads 58 reference files from main" .-> HUB
  S2b --> S1
  S1 -- "writes the label" --> D1
  D1 -- "then the Cases" --> D2
  D2 -- "the paid smoke reads the bundle folder" --> S6
  S6 --> S7
  classDef stage fill:#1e3a8a,stroke:#4a7fd4,color:#dbeafe
  classDef data  fill:#4c1d95,stroke:#a06ed4,color:#ede9fe
  classDef good  fill:#14532d,stroke:#30a46c,color:#dcfce7
  classDef plain fill:#374151,stroke:#9ca3af,color:#f3f4f6
  class S4,S2a,S2b,S1,S6 stage
  class D1,D2 data
  class S7 good
  class KEY,HUB plain
```

### Failure modes

| Row | Fault | Who notices | Outcome: image build | Outcome: paid smoke press |
| -- | -- | -- | -- | -- |
| F1 | the preparer dies after `provenance.json`, before `cases.json` (③) | the next prepare step | bundle has no parseable `cases.json`, so it is not served | the prepare step deletes the folder and prepares it again |
| F2 | a bundle has no `provenance.json` (cached before this change, or a new shared bundle missing from the map) (⑥) | whoever reads the run page | none | its row reads "not recorded"; the rest of the page renders |
| F3 | the file is garbled or holds `NaN` seconds (⑥) | whoever reads the run page | none | its row reads "unreadable provenance.json"; the rest of the page renders |
| F4 | GDPval's reference files change on the Hub's main branch (③b) | nothing refuses: hand-built Benchmarks have no Case Digest | the new text is prepared | the label says `unpinned`, so on-call keeps the files on the suspect list |
| F5 | a preparer's dataset pin is bumped in its declaration (③a) | the reviewer of that PR | the label carries the new revision | the row shows the new commit |

### Architecture

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 440}}}%%
flowchart TB
  KEY["HOW TO READ — colours here mean change status<br/>green = ✅ NEW in this PR · blue = ✏️ CHANGED · grey = unchanged neighbour<br/>solid arrow = who calls or reads whom · dashed = imports from · numbers ① to ⑦ are shared by every diagram on this page"]
  KEY ~~~ A1
  A1["① the image build, or the paid smoke workflow's prepare step and asset cache · screamingface-paid-benchmark-smoke.yml<br/>unchanged: the cache key covers this code, so the first press after merge re-prepares"]
  A2["② the prepare CLI · benchmarks.prepare<br/>unchanged: runs each bundle's preparer"]
  A3["③ the six hand-built preparers · benchmarks/draco, ifeval, healthbench, gdpval, medxpert, contracteval/prepare.py<br/>✏️ CHANGED: build the label, write it before cases.json, read it back into the summary"]
  A4["④ the label writer and the Case Source words · bundle_provenance.py (Engine core)<br/>✅ NEW: moved here from the plugin, plus hand_built_provenance and hugging_face_source"]
  A5["⑤ the inspect plugin's replay label and fetch recorder · replay_provenance.py, case_sources.py<br/>✏️ CHANGED: import the writer and the words from core"]
  A6["⑥ the press-page helper · tests/paid/_case_provenance.py (SDK)<br/>✏️ CHANGED: shared-bundle map for four Benchmarks; a dash when there is no inspect version"]
  A7["⑦ the 'Where the Cases came from' section on the run page<br/>unchanged: published by the paid smoke under its overview"]
  A1 --> A2 --> A3 --> A4
  A5 -. "imports" .-> A4
  A4 -- "each bundle now holds a label; the press reads it" --> A6
  A6 --> A7
  classDef good  fill:#14532d,stroke:#30a46c,color:#dcfce7
  classDef stage fill:#1e3a8a,stroke:#4a7fd4,color:#dbeafe
  classDef plain fill:#374151,stroke:#9ca3af,color:#f3f4f6
  class A4 good
  class A3,A5,A6 stage
  class A1,A2,A7,KEY plain
```

- **④ lives in core** because the hand-built preparers are core and core never imports the
  inspect plugin; the plugin imports core instead, so both kinds of bundle use one writer and one
  set of Case Source words.
- **③ writes the label before `cases.json`** because the workflow, the just recipe and the paid
  conftest all treat a parseable `cases.json` as "bundle finished" (F1).
- **③c counts `excluded` as loaded minus kept** so GDPval's row accounts for all 220 rows, not
  only the 7 unreadable tasks the summary already counts.
- **⑥ keeps its own four-entry map** because the SDK test venv cannot import the Engine (see
  Known limitations).

## Known limitations of this design

- **gdpval's reference files are listed as one line, not pinned.** 58 files behind 36 of the 102
  Cases come from URLs on the dataset's moving branch, with no hash. They show as one `unpinned`
  url source with the file count, so the label never reads fully pinned; pinning their bytes
  would need a per-file hash in the declaration, which waits until a swap actually happens.
- **ifeval's nltk data is left out.** The tokenizer data is downloaded unpinned, but it feeds the
  verifier, never a Case.
- **The shared-bundle map is a copy.** The run page's four-entry map repeats the Engine's
  `builtins.py` pairs, because the SDK test venv can't import the Engine. A new Benchmark on a
  shared bundle reads "not recorded" until the map gains its line.
- **gdpval's `excluded` (118) is not the summary's `excluded_tasks` (7).** The summary keeps its
  own count of unreadable tasks; the block counts every row the frozen selection drops.
- **A bundle prepared before this change has no file** until its cache is rebuilt; its row reads
  "not recorded", as in #1268.

## What each preparer records

`seeds_applied` and `pins` are `{}` for all six: none forces a seed, none runs inspect.
`excluded` is always `yielded − kept`, as in #1268, so the run page's "kept of yielded
(excluded)" accounts for every row.

| Bundle | Sources | yielded | kept | excluded on purpose |
| -- | -- | -- | -- | -- |
| draco | `perplexity-ai/draco` @ revision `ce076749…` | rows loaded (100) | Cases written (100) | none |
| ifeval | `google/IFEval` @ revision `966cd895…`; the vendored official file `josejg/instruction_following_eval/instruction_following_eval/data/input_data.jsonl` @ commit `0c495b2f…` | rows loaded (541) | Cases written (541) | none |
| healthbench | `openai/healthbench-professional` @ revision `349962fd…` | rows loaded (525) | Cases written (525) | none: worst-30% is a selection at serve time |
| gdpval | `openai/gdpval` @ revision `11e7900c…`; its reference files as one `url` source, `openai/gdpval/reference_files (58 files)` @ `unpinned` | rows loaded (220) | Cases written (102) | 118: every task outside the frozen text subset, the 7 unreadable ones included |
| medxpert | `TsinghuaC3I/MedXpertQA/Text` @ revision `7e7c465a…` | rows loaded (2450) | Cases written (2450) | none |
| contracteval | `theatticusproject/cuad-qa` @ revision `d9c4ee02…` | rows loaded (4182) | Cases written (4182) | none |

Why the ifeval official file counts as a source: the preparer checks every Hub row against it and
its text wins on key 2785, so that Case's prompt comes from the file.

`seconds` runs from the start of the preparer's `prepare`, download included, to the moment it
writes the block.

## Acceptance

1. Each of the six hand-built bundles holds `provenance.json` written before `cases.json`, with
   the declared revision as its pin and `samples.kept` equal to the Cases written; the summary
   carries the same block (one test per preparer).
2. No fixture Case text appears in the file (same tests).
3. The run page shows the shared bundle's block for draco-3pass, both HealthBench Benchmarks and
   gdpval-text, and a block with empty `pins` renders.
4. `check_layering.py` and both stacks' `run_gates.py` green; no Benchmark Revision changes.
