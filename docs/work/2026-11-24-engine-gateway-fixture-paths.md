---
ticket: OME-2014
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-24
finished:
---

# engine-gateway-fixture-paths — run the Engine suite on every repo file an Engine test reads

## Intent

`screamingface-engine-tests.yml` runs only when its `paths:` filters match a change. Engine tests
also read files outside `apps/screamingface-engine` and `packages/url4`: Gateway fixtures and
source, SDK source and metadata, a scoreboard schema, the layering script and the SDLC card. Only
some of those paths are in the filters. A change to any other one alone does not run the Engine
suite, so a Gateway, SDK or scoreboard change that breaks an Engine contract twin merges green and
the break surfaces on the next unrelated Engine change. Known case:
`tests/unit/test_gateway_error_relay_contract.py:29` reads
`apps/aigateway/tests/fixtures/provider_error_relay/`, which no filter matches.

This unit adds every such path to both triggers' filters and a guard test in the Engine suite
that fails when an Engine test reads a repo path outside the filters, so the list cannot drift
again unnoticed. Owner decision in chat, 2026-11-24: the full list plus the guard.

The full list includes `packages/screamingface/src/**` (three Engine tests run the SDK package
in a subprocess) and `.github/workflows/*.yml` (one test checks every workflow that builds the
benchmark image). Over the four weeks before this unit, 45 SDK commits and 30 workflow commits
on `main` touched neither the Engine nor url4, and each would now run the whole workflow,
including the 30 to 45 minute image build. Second owner decision, 2026-11-24: add every path,
and run the `image`, `conformance` and `chart` jobs only when the change touches the Engine,
url4, the root `.dockerignore` or the workflow itself. A change outside them runs the `test`
job, which is where the contract twins live. The images build from `packages/url4` and
`apps/screamingface-engine`, and the root `.dockerignore` decides what they copy.

Base: `origin/main` `744f3b89b`.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_engine_ci_path_filters.py` (new): the guard and a
  synthetic self-test of its path resolver.
- `.github/workflows/screamingface-engine-tests.yml`: the missing paths in the `push` and
  `pull_request` `paths:` lists, each with a comment naming the test that reads it, as the
  existing entries do. A new `changes` job classifies the change, and `image`, `conformance`
  and `chart` depend on it and run only for an Engine change. A manual run or a base git cannot
  find counts as an Engine change. So does an empty diff, but only as a fail-safe of the script:
  GitHub never starts a path-filtered workflow for one. A new branch's first push, whose base is
  all zeros, is compared with where it left the default branch.
- `apps/screamingface-engine/tests/unit/test_engine_ci_heavy_jobs.py` (new): pins the gating,
  and runs the classifier's own shell script against a throwaway git repository.
- This ledger; at PR-open, the Linear leaf under `OME-1321` and its `docs/tasks/` mirror.
- Review fixes, 2026-11-25. An independent review of the PR found these gaps:
  - Both images build from the repo root, so the root `.dockerignore` decides what they copy.
    It joins both `paths:` lists and `ENGINE_PATHS`.
  - A push is classified by its two trees (`before..after`), as GitHub filters it. A pull
    request keeps `base...head`.
  - The guard counts a path that a test only tests for existence. A file must be matched. A
    directory needs one matched file under it. `.claude/sdlc.local.md`, the repo-root marker of
    `tests/unit/test_credit_contract.py`, joins both lists.
  - The guard resolves `.joinpath()` with literal segments, and the root that
    `next(p for p in X.parents if (p / marker).is_file())` finds. It fails on the repo root
    joined with a run-time name, because no filter can cover that.
  - `_READ_THROUGH` lists only directories. The files read there are the ones its readers name
    as string literals, so a new name is checked too.
  - The scan moves to `tests/unit/engine_ci_support.py`, which keeps the guard under 450 lines.
- Second review fixes, 2026-11-25. A second review of the uncommitted fixes found these gaps:
  - A name means what Python means by it. A name a function binds is that function's own, and
    leaves the module name of the same spelling alone. A name bound twice in one scope stands for
    both paths. Python's scopes move to `tests/unit/engine_ci_scopes.py`.
  - A repo path joined from literals counts even before it exists, so a test that waits for a
    future fixture still depends on it. The filters must then match the path itself and every
    file that can appear under it.
  - A read-through directory stands for the literal tail of each whole join, such as
    `project / "src" / "aigateway" / "main.py"`, not only for its single string literals.
  - `**/` matches no directory or any number of them, as GitHub documents. `?`, `+` and `[...]`
    follow the same cheat sheet.
  - The scan's own cases move to `tests/unit/test_engine_ci_path_scan.py`, which keeps the guard
    under 450 lines.
- Third review fixes, 2026-11-25. A third review found these gaps:
  - `Path("apps/...")` with a literal names a repo path even before it exists, when its first
    segment is a top-level entry of the repo.
  - A read-through join that a run-time value interrupts, such as `project / name / "main.py"`,
    stands for the whole directory under its literal tail.
  - An import binds a name like an assignment, so it shadows the outer one. A name imported
    from a module in the repo means what that module binds it to. A name imported from the
    standard library is not a repo path. A path built on a name imported from any other module
    fails the guard, unless the guard lists that module as a reviewed third-party package.
    Locating a module is static, so the result is the same in every environment.
    - New `apps/screamingface-engine/tests/unit/engine_ci_modules.py`: locating a module, reading
      the paths its names give, and telling a module outside the repo. It keeps the scan under
      450 lines.
    - A glob under a module outside the repo reports the module, instead of matching nothing.
    - `Path(x)` stands for the paths `x` stands for.
  - The full gates run on this branch merged with the current `main`. The branch takes `main`
    by a merge commit, not a rebase, so no force-push is needed.
- Fourth review fixes, 2026-11-25. A fourth review found these gaps:
  - An import cycle loses a name: the module read second finds the first one still empty. A
    module is registered before its names are bound, as Python registers it before it runs, and
    the modules one lookup reads are bound again until no name gains a path.
  - An import under `nonlocal` or `global` binds the name of the scope the statement names, as
    an assignment does.
  - `..` in a literal path, a string literal, a join or a glob match is resolved before the
    path is placed. So `Path("../aigateway/pyproject.toml")` names
    `apps/aigateway/pyproject.toml`. A join that leaves the repo above its root names no repo
    path, and its root is not a read of its own.
  - A test module named after a standard library module is looked up in the repo first, because
    pytest puts the test's directory first on `sys.path`.
  - A read-through directory stands for what each of its readers reaches through it:
    - where the scan sees the directory joined with a literal tail, that path, even before it
      exists;
    - where it sees the directory joined with a run-time name, the literals that name can be,
      when it loops over a literal table or is assigned a literal; otherwise the directory under
      the tail;
    - where the directory is passed on to a value the scan cannot follow, such as a container
      or a call, the whole directory, unless the guard lists that reader as reviewed. In a
      reviewed reader, each join on a root the scan cannot resolve counts as a join to the
      directory: a literal tail even before it exists, and a run-time name as above.
    - A reader that names the directory only through a glob match reaches all of it.
    - The guard checks that each reviewed reader still passes its directory on.
    - The read-through rules move to `engine_ci_read_through.py`, and the path arithmetic to
      `engine_ci_paths.py`, to keep each file under 450 lines.
  - `main` moved again, to `1cf0eff72`. It is merged into the branch by a merge commit, and the
    full gates run in the worktree itself.

## Test plan

- RED: the guard on the current workflow fails and names every uncovered path, at least
  `apps/aigateway/tests/fixtures/provider_error_relay`.
- The guard's resolver, on synthetic sources: a repo-relative string literal, a literal joined to
  a repo-root expression (`Path(__file__).resolve().parents[k]`, `.parent`), a name bound to such
  an expression and joined later, and an Engine-local path, which is not reported.
- The guard also requires the `push` and `pull_request` lists to be equal.
- Heavy jobs, RED first: `image`, `conformance` and `chart` need `changes` and run only on its
  `engine` output; `test` runs for every change; every build-context path the Engine
  Dockerfiles copy, and the workflow itself, is an Engine change; an SDK, Gateway or other
  workflow path is not. The classifier script, run against a throwaway repository: an SDK-only
  diff gives `false`; an Engine diff, a manual run, an empty diff (the fail-safe) and an
  all-zero base with no fork point give `true`; a new branch's all-zero base is compared with
  its fork point.
- GREEN: with the filters extended and the jobs gated, both tests pass; no prior test changes.
- Review fixes, RED first:
  - Each image's build-context `.dockerignore` is an Engine change and starts the workflow.
  - A push that drops an Engine commit runs the heavy jobs. A pull request whose base gained
    an Engine commit does not.
  - The scan finds each of these:
    - a `.joinpath()` read;
    - a root marker, as an existence dependency;
    - a read under a marker-found root;
    - the repo root joined with a run-time name.
  - The scan tells an existence check from a read.
  - A read-through directory stands for the files its readers name.
- Second review fixes, RED first against the scan as it stood after the first review:
  - The review's falsifier: a function binds `ROOT` to the SDK, and the module still reads
    `apps/aigateway/src/aigateway/main.py` through its own `ROOT`. Both paths are found.
  - A name bound twice; a function body that sees a module name bound below it; a path bound in
    a class body; a method that does not see its class body's names; a parameter; `global`;
    `nonlocal`; a comprehension's first iterable, which sees the enclosing name.
  - A repo path that does not exist yet, such as `apps/aigateway/tests/fixtures/new_contract`
    tested with `.exists()`. It is found, and the filters must match it and every file under it.
  - A literal that names no repo path is not one.
  - `project / "src" / "aigateway" / "main.py"` names that file under a read-through directory.
  - Each example of GitHub's filter pattern cheat sheet, and the review's
    `apps/*/deploy/**/*.sh` against `apps/example/deploy/run.sh`.
- Third review fixes, RED first:
  - The review's falsifier: `Path("apps/aigateway/tests/fixtures/new_contract")` tested with
    `.exists()` is found. A literal `Path` that names no repo path is not.
  - The review's falsifier: `project / name / "main.py"` makes the read-through directory
    itself a dependency. So does an f-string that carries a literal suffix.
  - A name imported from a repo module, whole or by name; `Path(module.__file__)`; a local import
    that shadows the module name; a name from the standard library; a name from a module the
    scan cannot find, which is reported so that the guard fails.
    - The review's own falsifier spells the path as one literal, which the existing literal rule
      already finds. The cases split the path into segments, or use a path that does not exist
      yet, so they fail without the fix.
  - The guard accepts a path from a listed third-party package and refuses any other.
  - Added while making the mutations bite: `import a.b`, `import a.b as x`, a module imported
    from its package, a relative import, a glob under a module outside the repo, an absolute
    `Path` literal and an Engine-relative one, and the arguments of `Path(...)`, which are not
    reads of their own.
- Fourth review fixes, RED first:
  - The review's falsifiers: an import cycle that re-exports a path; an import under `nonlocal`;
    `Path("../aigateway/pyproject.toml")`; a test module named `statistics`; an absent tail
    under a read-through directory; a read-through directory joined with a run-time name.
  - Added with them: `..` in a join, a cycle read in the other order, a run-time name that loops
    over a literal table, a reader that passes the directory on, reviewed or not.

## Acceptance

- The guard passes on the final workflow and fails when any one added entry is removed.
- The heavy-job test fails when any one heavy job loses its `if`.
- `run_gates.py screamingface-engine --base origin/main` all green on Python 3.12 and 3.13, the
  append-only check included.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the review fixes.
  - `.github/workflows/screamingface-engine-tests.yml`: 123 added lines and no removed line,
    measured against `main` at `0395e573f`. The added paths appear in both triggers. The
    `changes` job was added, and `image`, `conformance` and `chart` were gated on it.
  - In `apps/screamingface-engine/tests/unit/`, all new:
    - `engine_ci_support.py` (425 lines): the scan and the filter reader.
    - `engine_ci_paths.py` (135 lines): repo paths built from literals, `..` included.
    - `engine_ci_scopes.py` (170 lines): Python's name scopes, imports included, for the scan.
    - `engine_ci_modules.py` (246 lines): the modules a test imports, located in the repo
      without importing them, import cycles included.
    - `engine_ci_read_through.py` (345 lines): what a read-through directory stands for.
    - `test_engine_ci_path_filters.py` (410 lines): the guard.
    - `test_engine_ci_path_scan.py` (382 lines): the scan's own cases and the filter pattern
      cases.
    - `test_engine_ci_import_scan.py` (128 lines): the scan follows imports into repo modules,
      each case in a throwaway repo of its own.
    - `test_engine_ci_heavy_jobs.py` (243 lines).
  - This ledger and the mirror.
- **Commits:** these, then the PR and its merge, which are recorded at close-out:
  - `a99e099ae` `ci(screamingface-engine): run the Engine suite on every repo file an Engine
    test reads`;
  - `83cb2ad0f` `docs(tasks): file OME-2014 and mirror it`;
  - `ee7e88426`, a merge commit that takes `main` at `1cf0eff72`, with no rebase and no
    force-push;
  - the review-fix commit;
  - a merge commit that takes `main` at `0395e573f`, with #1937 in it.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` is all green on Python
  3.13.11 and 3.12.9: append-only, ruff check, ruff format, pyright, layering, and the full
  pytest suite with coverage. It ran on `main` at `0395e573f` with the branch's final files
  (see Combined trees). The four test modules of the guard give 98 passed on each Python, on
  the branch and on that tree.
- **Combined trees:**
  - `main` moved to `0395e573f` while the gates ran, with #1937 merged at `8a9df90f9`. The
    gates ran on a clean checkout of that `main` with the branch's final files and the
    workflow conflict resolved as the merge commit resolves it. Its own environments were
    synced from that tree's lock (`uv sync --frozen`).
  - Before that, the branch merged `main` at `1cf0eff72`, and the gates ran on that merged tree
    in the worktree itself. `main` changed none of the branch's files. The environments were synced
    again from the merged lock (`uv sync --frozen --dev`), so the full suite ran against
    `main`'s Engine code.
  - Before the merge, at the third review, the branch's files were copied onto a clean checkout
    of `main` at `d69e15a58` for the gates. The merge replaces that.
  - #1937's head `bc52c404` does not apply cleanly onto the new `main`, so its own tree was
    used, with this branch's final files and both sets of filter inserts. The guard reports
    one path: `packages/screamingface/tests/data/surface_parity.json`, which
    `_chat_corpus.py:18` reads. The other 64 tests pass. Whichever PR merges second adds the
    path to both lists.
  - After the third review fixes, #1937's head was `c4f472473`, which merges `main` at
    `d69e15a58`. With this branch's final files and both sets of filter inserts, #1937 lists
    `surface_parity.json` itself, and the guard reports two other paths from its new tests:
    `test_chat_docs_review2.py:58` reads `public-docs/src/pages/sf-client/api/ChatPage.vue`,
    which no filter matches; `test_chat_review2_ci_paths.py:37` joins the repo root with a
    loop variable (`.`). The scan from before the second review reports the same two. The
    other 79 tests pass. #1937 merged first, at `8a9df90f9`, with neither path, so this branch
    adds them in its merge of `0395e573f` (see Deviations).
  - On the real suite, the scan finds 86 paths at `1cf0eff72` and at `d69e15a58`, and 85 at
    the fork point `744f3b89b`. On each of these trees the scan from the first review finds
    one fewer, and every other path with the same reader and kind; the one more is the listed
    `<import inspect_evals>/threat_intel_reasoning/report_questions.json`. No filter entry
    changed. Earlier rounds reported 89; that count could not be reproduced, because their
    code was not kept, but the comparison above shows no path lost.
- **The tests bite:** each mutation below was run against the final code, one at a time. A new
  test fails each time.
  - Workflow:
    - any one of these filter entries is removed: `packages/screamingface/src/**`,
      `apps/aigateway/tests/fixtures/provider_error_relay/**`,
      `apps/aigateway/src/aigateway/plugins/*/models.py`, `*/*/justfile`,
      `packages/screamingface/examples/*.ipynb`, `apps/aigateway/uv.lock`,
      `.claude/scripts/check_layering.py`, `.claude/sdlc.local.md`, `.dockerignore`;
    - `.dockerignore` is dropped from `ENGINE_PATHS`;
    - the `image` job loses its `if`;
    - the empty-diff guard (`-s`) is dropped;
    - the all-zero-base fork-point fallback is removed;
    - a push is compared with three dots;
    - a pull request is compared with two dots.
  - Scan and guard:
    - an existence-checked directory needs full coverage;
    - the read-through literals name nothing;
    - `relative_to` arguments count as reads;
    - a whole checked expression counts as existence-only;
    - `.joinpath()` arguments count as reads;
    - the marker file is not recorded.
  - Scan, second review:
    - a name is looked up in the module scope only; a name is bound there only;
    - a method sees its class body's names;
    - names bind in source order alone, not module code first;
    - a second binding replaces the first;
    - a path bound in a class body is not counted as read;
    - a path that does not exist yet is dropped;
    - a string literal counts without an existing path;
    - `global` is ignored; `nonlocal` is ignored; parameters are not bound;
    - a comprehension's first iterable runs in the comprehension's own scope.
  - Guard, second review:
    - a join is read without its nested part; a tail keeps only its first string; the inner
      parts of a join count as joins of their own;
    - a tail that a run-time name finishes names no directory;
    - a path that does not exist yet needs only itself matched, or itself or its tree, or only
      its tree when absent.
  - Filter patterns: `**/` needs one directory; `?` is any character; `+` is literal; `[...]`
    is literal.
  - Each mutation was run against the final code. One more, a guard condition that dropped a
    join rooted at a string literal, survived. Such a join cannot run, so the condition was
    removed. A comprehension mutation also survived at first, and its case was added.
  - Third review, rerun with every mutation above on the final code: 71 of 71 caught.
    - `Path` literals: dropped; required to exist; any first segment counts; an absolute path
      counts; the Engine is not checked first; the arguments of `Path(...)` count as reads;
      `Path(name)` is not resolved.
    - Imports: not bindings; their values ignored; a module attribute ignored; `__file__`
      ignored; `import a.b` binds `a.b`; `import a.b as x` binds `a`; a module imported from
      its package is the package; a relative import is one level off; only the importer's
      directory is searched; the standard library counts as outside.
    - Modules outside the repo: not reported as a root, bare or under `Path(...)`; `.parent`
      drops the module; a glob under one is silent; the guard covers any of them, or none, or
      no longer lists `inspect_evals`.
    - Read-through joins: an interrupted join names nothing; a bare run-time operand names the
      whole directory; the empty tail is dropped; an f-string counts as a plain operand.
  - Fourth review: 102 mutations, all caught.
    - Import cycles: no second reading; the early read never noted; no guard on a name a module
      asks itself for; the module registered only after its names are bound; a reading that
      adds to the last one instead of starting again; a cycle that builds ever longer paths
      read on in silence.
    - An import under `nonlocal` kept in the inner scope.
    - `..`: kept; a path above the repo root kept; a module outside the repo dropped by it;
      not resolved in a `Path` literal, a string literal or a glob match; a join that leaves
      the repo counted as a read of its root.
    - The standard library looked up before the repo.
    - Read-through: an absent tail dropped; a join with a run-time name reaching nothing; the
      literals a name loops over ignored; the unpacking position ignored; a reader that passes
      the directory on reaching nothing; the review ignored, or every reader reviewed; a reader
      with no site reaching nothing; a `.joinpath()` on the directory not followed; a join
      read one step deep; `passes_on` always or never true; a table bound to a name not
      followed; a parameter, an import or another binding form taken for a literal binding;
      a reviewed reader's joins on a resolvable root taken for joins on the directory; the
      reviewed reader dropped from `_READ_THROUGH`.
    - The earlier rules this round rewrote, in their new form: the read-through literals name
      nothing; a string literal counts without an existing path; a run-time rest reaches
      nothing; a `Path` literal must exist, or any first segment counts; the tail before a
      run-time rest is dropped; the empty tail is dropped.
    - The 62 earlier mutations whose code is still there, rerun against the new layout.
    - One survived at first: a glob match spelled with `..`. The case's pattern was itself a
      literal path, which the literal rule found anyway. The pattern now ends in `?`.
  - The merge of `0395e573f`: 5 mutations, all caught. The repo root not read through; the
    root's sites looked up as `.`; a name bound to a list followed; a list inside a tuple
    followed; the `ChatPage.vue` entry removed. The first and the last were run on the
    combined tree, where #1937's tests read those paths.
- **Deviations:**
  - The scope grew with the second owner decision, which added the `changes` job, the gating
    and `test_engine_ci_heavy_jobs.py`.
  - The fork-point fallback came out of a design review after the first heavy-job tests. It was
    written into the workflow before its test. Its RED was then shown by removing it.
  - No workflow linter was run on the YAML. The tests parse the workflow, and they run the
    classifier script itself.
  - The branch's required-check list could not be read from here. A job skipped by its `if`
    reports success, so a skipped heavy job does not block a merge. The first SDK-only pull
    request after the merge should confirm this.
  - The first run of the removal checks used a pattern that never matched, so it removed
    nothing. Those checks were redone with an exact line removal.
  - An independent review returned the PR as not ready, with the gaps listed under Planned
    changes. The fixes changed tests of this same unmerged unit, and no test from an earlier
    unit:
    - Two scan cases now expect an existence-checked path, as the review asked: the bound
      `SDK.exists()` and the `.claude/scripts/check_layering.py` root marker.
    - The `COPY` source check no longer joins a run-time name to the repo root, which the
      guard now refuses. It matches the source itself or a file under it.
    - `_READ_THROUGH` became a set of directories.
  - The review suggested a reviewed exception list for optional existence probes. None was
    needed. A directory that a test only tests for existence counts as covered when one matched
    file under it exists. Every such probe in the suite passes that rule, and one file,
    `.claude/sdlc.local.md`, was added.
  - The scan resolves only roots built from the test file. A path rooted at an imported
    module's `__file__`, or at a name another module exports, is not modelled. No Engine test
    reads outside the Engine that way today. The third review fixes replaced this limit.
  - `origin/main` moved to `83d157f26` during the review, then to `d69e15a58`. The append-only
    check diffs the worktree against its base, so the gates ran against the fork point
    `744f3b89b`. Against the new `main`, the check would treat `main`'s own test changes as
    removals.
  - The first RED for the scan cases used the old scan behind the new names, through a
    temporary shim. The shim was removed before the implementation.
  - The second review fixes:
    - The review allowed scope-aware names or a failure on an ambiguous name. Scope-aware
      names were chosen, with every path a name can stand for kept, so no read is lost and a
      test that reuses a name still passes.
    - A path bound in a class body counts as read, because a method reads it as an attribute.
      A wider rule, that any unused binding counts as read, would also have made an unused
      marker root count, against an earlier case. It was narrowed to class bodies.
    - The scope model binds names by assignment, parameters, `global` and `nonlocal`. Another
      binding form, such as an import, a `def` name or an `except ... as` name, lets a lookup
      reach the enclosing scope. That claim was wrong for imports, as the third review showed. A
      local `from m import REPO as ROOT` let the lookup reach an outer `ROOT` bound to another
      path, so the read through it was lost. Imports are modelled since then.
    - The review asked that a path that does not exist yet be kept. The guard also asks more
      of it than of an existing path: the filters must match the path and every file under
      it, because it can appear as either.
    - `?`, `+` and `[...]` were fixed beyond the finding, from the same GitHub cheat sheet.
      They were matched literally before.
    - The scan's cases moved to `test_engine_ci_path_scan.py` verbatim. Both modules are new
      on this branch, so no test from an earlier unit changed.
    - The RED was shown by running the new cases against the scan as it stood after the first
      review: 18 failed. The guard's new cases were shown RED by the mutations above.
    - On the real Engine suite, the scan before and after these fixes finds the same 89 paths,
      so no filter entry was added.
  - The third review fixes:
    - The review allowed failing closed on an imported root, or a reviewed exception. Failing
      closed on every imported root would have failed the guard at 7 places in the real suite,
      all of them resolvable. So repo modules are read, the standard library is not a repo
      path, and only a module found in neither fails, with a reviewed list for the exceptions.
      The list holds one entry, `inspect_evals`.
    - Modules are located from the repo, not with `importlib.util.find_spec`, whose answer
      depends on the environment: `inspect_evals` is not installed in the dev environment.
    - The review's falsifiers that spell the path as one literal already pass, through the
      literal rule. The RED cases split the path or use one that does not exist yet. Against the
      code as it stood after the second review fixes, 7 tests failed: 5 scan cases and both new
      guard tests.
    - The cases added while making the mutations bite pass with the fix. Their RED is the
      mutations that remove the code they cover.
    - A glob under a module outside the repo and `Path(name)` were fixed beyond the findings.
    - Reading imported modules made the scan slower: about 8 s for the first full scan and 5 s
      for the next. A cache of module lookups took it from 21 s, and the guard scans the suite
      once for both of its tests.
    - On the real suite, the scan finds the same 89 paths, plus
      `<import inspect_evals>/threat_intel_reasoning/report_questions.json`, which the list
      covers. No filter entry was added.
    - Not modelled: a path from a call the scan does not know, such as `Path.cwd()` or
      `importlib.resources.files()`; a star import, which lint forbids; and a `def`, `class`,
      `except` or `match` binding. These err toward more paths: a `def`, a `class` or an
      `except` target binds no path, and a `match` subject is reported itself.
  - The fourth review fixes:
    - The RED was 11 failed tests: 3 scan cases, 4 import cases, and the 4 new guard tests.
      The cases added while making the mutations bite pass with the fix; their RED is the
      mutations that remove the code they cover.
    - The review allowed three ways for a join to a read-through directory with a run-time
      value: fail closed, a reviewed exception, or the whole directory. All three are used:
      - a join whose name loops over literals reaches those files, and any other run-time
        join reaches the directory under its tail;
      - a reader that passes the directory on reaches all of it;
      - unless it is reviewed. `test_tortoise_pin_conformance.py` is: it keeps each project in
        `_PROJECTS`, a dict, and reads one only by `project / "pyproject.toml"` and
        `project / "uv.lock"`. The whole of `apps/aigateway` and `packages/screamingface` in
        the filters would run the Engine suite on every Gateway and SDK change. A new test
        fails when a reviewed reader no longer passes its directory on.
    - An import cycle is read again until no module changes, from the first statement each
      time, so `X = X / "a"` stays finite. That runs only when a module asked a module still
      in its first reading. A cycle that builds a longer path on every reading fails after 32
      readings instead of hanging.
    - `..` was fixed beyond the finding: in a string literal, a join and a glob match too. A
      join above the repo root names no repo path, and its root is not a read of its own.
    - The standard library module name rule is kept for `<import M>`: a module that is neither
      in the repo nor in the standard library is still reported.
    - The scan's string literal rule now returns an Engine path, which the guard leaves out as
      local, instead of dropping it in place. The result is the same; the Engine directory is
      tried first, so `"../aigateway/uv.lock"` leaves it.
    - In a reviewed reader, only joins on a root the scan cannot resolve count as joins on the
      directory. Before, every join did, so `REPO / "uv.lock"` would have named a file under
      the directory.
    - The path arithmetic moved to `engine_ci_paths.py`, the read-through rules to
      `engine_ci_read_through.py`, and the cases that build their own repo to
      `test_engine_ci_import_scan.py`, to keep each file under 450 lines.
  - The merge of `main` at `0395e573f`:
    - `main` moved while the gates ran. #1937 and this branch both added filter lines at the
      same place in the workflow, so the merge conflicts there. Both sets are kept.
    - On the merged tree the guard reports the two paths recorded under Combined trees.
      `public-docs/src/pages/sf-client/api/ChatPage.vue` is added to both lists.
      `test_chat_review2_ci_paths.py:37` joins the repo root with a name that loops over a
      tuple of literals. #1937's test is not changed. The guard now reads the repo root
      through, like a listed directory with no reviewed reader, so that join reaches the two
      files the tuple names, which both lists match. A join on the root with a name the scan
      cannot read still reaches the root itself, which no filter covers.
    - The scan itself does not resolve the name. That would also resolve
      `WORKFLOWS / kind / "main.yml"`, whose case of this round expects the whole directory.
    - Fixed while doing it: a name bound to a list was followed as a table. A list grows in
      place or through another name, so only a tuple of literals and tuples is followed now.
      The two real tables, in `test_declared_models_match_aigateway.py`, are tuples.
    - The RED was the 2 new guard tests. The root read through and the `ChatPage.vue` entry
      were shown RED on the combined tree by removing each.
    - The first full gates on the tree merged at `1cf0eff72` hung for 4 h 43 min in one test of
      `main`, `test_worker_claim.py::test_a_cancel_during_the_spawn_window_is_answered_and_enacted`,
      with the other 11175 passed. Alone it passed 20 times out of 20, and its file in 6 s. This
      branch does not change it or the Engine source. The gates run under a 25-minute watchdog
      since.
